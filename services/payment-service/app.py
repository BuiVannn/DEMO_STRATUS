"""
Payment Service - Bounded Context: Xử lý thanh toán
"""
import os
import time
import uuid
import logging
from flask import Flask, jsonify, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource

# --- OpenTelemetry Setup ---
resource = Resource.create({"service.name": "payment-service"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("payment-service")

# --- Prometheus Metrics ---
REQUEST_COUNT = Counter("payment_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("payment_request_duration_seconds", "Request latency", ["endpoint"])

# --- Config (có thể inject lỗi qua env) ---
SIMULATE_DELAY = float(os.getenv("SIMULATE_DELAY", "0"))  # seconds
SIMULATE_FAILURE = os.getenv("SIMULATE_FAILURE", "false").lower() == "true"

# --- In-memory Transaction Log ---
TRANSACTIONS = {
    "TXN-SEED0001": {
        "txn_id": "TXN-SEED0001",
        "order_id": "ORD-SEED0001",
        "amount": 25000000,
        "customer_name": "Nguyễn Văn A",
        "status": "success",
        "processed_at": "2026-02-28 10:30:05",
    },
    "TXN-SEED0002": {
        "txn_id": "TXN-SEED0002",
        "order_id": "ORD-SEED0002",
        "amount": 60000000,
        "customer_name": "Trần Thị B",
        "status": "success",
        "processed_at": "2026-02-28 14:15:12",
    },
    "TXN-SEED0003": {
        "txn_id": "TXN-SEED0003",
        "order_id": "ORD-SEED0003",
        "amount": 18000000,
        "customer_name": "Lê Hoàng C",
        "status": "success",
        "processed_at": "2026-03-01 09:00:08",
    },
}


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "payment-service"}), 200


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/payments", methods=["POST"])
def process_payment():
    """Xử lý thanh toán — được gọi bởi Order Service"""
    start = time.time()

    with tracer.start_as_current_span("process-payment") as span:
        data = request.get_json() or {}
        order_id = data.get("order_id", "unknown")
        amount = data.get("amount", 0)
        customer_name = data.get("customer_name", "Anonymous")

        span.set_attribute("payment.order_id", order_id)
        span.set_attribute("payment.amount", amount)

        logger.info(f"[Payment] Processing payment for order={order_id}, amount={amount}")

        # Simulate delay (for fault injection demo)
        if SIMULATE_DELAY > 0:
            logger.warning(f"[Payment] ⚠️ Simulating delay: {SIMULATE_DELAY}s")
            time.sleep(SIMULATE_DELAY)

        # Simulate failure (for fault injection demo)
        if SIMULATE_FAILURE:
            logger.error(f"[Payment] ❌ Simulated payment failure for order={order_id}")
            span.set_attribute("payment.success", False)
            REQUEST_COUNT.labels(method="POST", endpoint="/payments", status="500").inc()
            return jsonify({"error": "Payment processing failed", "order_id": order_id}), 500

        # Normal processing
        txn_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        transaction = {
            "txn_id": txn_id,
            "order_id": order_id,
            "amount": amount,
            "customer_name": customer_name,
            "status": "success",
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        TRANSACTIONS[txn_id] = transaction

        span.set_attribute("payment.txn_id", txn_id)
        span.set_attribute("payment.success", True)

        logger.info(f"[Payment] ✅ Payment OK: TXN={txn_id}, amount={amount}")
        REQUEST_COUNT.labels(method="POST", endpoint="/payments", status="200").inc()
        REQUEST_LATENCY.labels(endpoint="/payments").observe(time.time() - start)

        return jsonify(transaction), 200


@app.route("/payments", methods=["GET"])
def list_transactions():
    start = time.time()
    
    status_filter = request.args.get("status")
    txns = list(TRANSACTIONS.values())
    if status_filter:
        txns = [t for t in txns if t["status"] == status_filter]
    
    txns.sort(key=lambda x: x.get("processed_at", ""), reverse=True)
    
    REQUEST_COUNT.labels(method="GET", endpoint="/payments", status="200").inc()
    REQUEST_LATENCY.labels(endpoint="/payments").observe(time.time() - start)
    return jsonify({
        "transactions": txns,
        "total": len(txns),
    }), 200

@app.route("/payments/stats", methods=["GET"])
def payment_stats():
    """Thống kê thanh toán"""
    total = len(TRANSACTIONS)
    success = sum(1 for t in TRANSACTIONS.values() if t["status"] == "success")
    failed = sum(1 for t in TRANSACTIONS.values() if t["status"] != "success")
    total_amount = sum(t.get("amount", 0) for t in TRANSACTIONS.values() if t["status"] == "success")
    
    return jsonify({
        "total_transactions": total,
        "success": success,
        "failed": failed,
        "total_amount_processed": total_amount,
        "success_rate": round(success / max(total, 1) * 100, 1),
        "simulate_delay": SIMULATE_DELAY,
        "simulate_failure": SIMULATE_FAILURE,
    }), 200

@app.route("/payments/<txn_id>", methods=["GET"])
def get_transaction(txn_id):
    """Chi tiết 1 transaction"""
    txn = TRANSACTIONS.get(txn_id)
    if not txn:
        return jsonify({"error": f"Transaction {txn_id} not found"}), 404
    return jsonify(txn), 200

if __name__ == "__main__":
    logger.info("Payment Service starting on port 5003")
    app.run(host="0.0.0.0", port=5003, debug=False)
