"""
Order Service - Bounded Context: Quản lý đơn hàng & Orchestration
Orchestrate gọi Product Service và Payment Service theo sequence.
"""
import os
import time
import uuid
import logging
import requests as http_requests
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
resource = Resource.create({"service.name": "order-service"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("order-service")

# --- Prometheus Metrics ---
REQUEST_COUNT = Counter("order_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("order_request_duration_seconds", "Request latency", ["endpoint"])
ORCHESTRATION_ERRORS = Counter("order_orchestration_errors_total", "Orchestration errors", ["step"])

# --- Service URLs ---
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://product-service:5002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:5003")

# --- In-memory Order Database ---
ORDERS = {
    "ORD-SEED0001": {
        "order_id": "ORD-SEED0001",
        "product_id": "P001",
        "qty": 1,
        "customer_name": "Nguyễn Văn A",
        "total_amount": 25000000,
        "txn_id": "TXN-SEED0001",
        "status": "confirmed",
        "created_at": "2026-02-28 10:30:00",
    },
    "ORD-SEED0002": {
        "order_id": "ORD-SEED0002",
        "product_id": "P002",
        "qty": 2,
        "customer_name": "Trần Thị B",
        "total_amount": 60000000,
        "txn_id": "TXN-SEED0002",
        "status": "confirmed",
        "created_at": "2026-02-28 14:15:00",
    },
    "ORD-SEED0003": {
        "order_id": "ORD-SEED0003",
        "product_id": "P003",
        "qty": 3,
        "customer_name": "Lê Hoàng C",
        "total_amount": 18000000,
        "txn_id": "TXN-SEED0003",
        "status": "confirmed",
        "created_at": "2026-03-01 09:00:00",
    },
}


@app.route("/health", methods=["GET"])
def health():
    """Health check — kiểm tra cả dependency services"""
    deps = {"product-service": "unknown", "payment-service": "unknown"}
    try:
        r = http_requests.get(f"{PRODUCT_SERVICE_URL}/health", timeout=3)
        deps["product-service"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        deps["product-service"] = "unreachable"

    try:
        r = http_requests.get(f"{PAYMENT_SERVICE_URL}/health", timeout=3)
        deps["payment-service"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        deps["payment-service"] = "unreachable"

    all_healthy = all(v == "healthy" for v in deps.values())
    status = "healthy" if all_healthy else "degraded"
    code = 200 if all_healthy else 503

    return jsonify({"status": status, "service": "order-service", "dependencies": deps}), code


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/orders", methods=["GET"])
def list_orders():
    start = time.time()
    
    # Filtering
    status_filter = request.args.get("status")
    customer = request.args.get("customer", "").lower()
    
    orders = list(ORDERS.values())
    if status_filter:
        orders = [o for o in orders if o["status"] == status_filter]
    if customer:
        orders = [o for o in orders if customer in o.get("customer_name", "").lower()]
    
    # Sort by created_at descending (newest first)
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    REQUEST_COUNT.labels(method="GET", endpoint="/orders", status="200").inc()
    REQUEST_LATENCY.labels(endpoint="/orders").observe(time.time() - start)
    return jsonify({
        "orders": orders,
        "total": len(orders),
    }), 200

@app.route("/orders/stats", methods=["GET"])
def order_stats():
    """Thống kê đơn hàng — dashboard hiển thị hoặc agent phân tích"""
    total = len(ORDERS)
    confirmed = sum(1 for o in ORDERS.values() if o["status"] == "confirmed")
    failed = sum(1 for o in ORDERS.values() if o["status"] == "failed")
    total_revenue = sum(o.get("total_amount", 0) for o in ORDERS.values() if o["status"] == "confirmed")
    
    return jsonify({
        "total_orders": total,
        "confirmed": confirmed,
        "failed": failed,
        "total_revenue": total_revenue,
        "success_rate": round(confirmed / max(total, 1) * 100, 1),
    }), 200

@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    """Chi tiết 1 đơn hàng"""
    order = ORDERS.get(order_id)
    if not order:
        return jsonify({"error": f"Order {order_id} not found"}), 404
    return jsonify(order), 200

@app.route("/orders", methods=["POST"])
def create_order():
    """
    Tạo đơn hàng — Orchestration pattern:
    1. Check stock tại Product Service
    2. Xử lý thanh toán tại Payment Service
    3. Reserve stock tại Product Service
    """
    start = time.time()

    with tracer.start_as_current_span("create-order") as span:
        data = request.get_json() or {}
        product_id = data.get("product_id")
        qty = data.get("qty", 1)
        customer_name = data.get("customer_name", "Anonymous")

        if not product_id:
            REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="400").inc()
            return jsonify({"error": "product_id is required"}), 400

        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        span.set_attribute("order.id", order_id)
        span.set_attribute("order.product_id", product_id)
        span.set_attribute("order.qty", qty)

        logger.info(f"[Order {order_id}] Starting order creation for product={product_id}, qty={qty}")

        # === Step 1: Check Stock (Product Service) ===
        with tracer.start_as_current_span("step1-check-stock"):
            try:
                logger.info(f"[Order {order_id}] Step 1: Checking stock at Product Service...")
                resp = http_requests.get(
                    f"{PRODUCT_SERVICE_URL}/products/{product_id}/check-stock",
                    params={"qty": qty},
                    timeout=10
                )
                if resp.status_code != 200:
                    ORCHESTRATION_ERRORS.labels(step="check-stock").inc()
                    REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="404").inc()
                    return jsonify({"error": "Product not found", "order_id": order_id, "status": "failed"}), 404

                stock_data = resp.json()
                if not stock_data.get("available"):
                    ORCHESTRATION_ERRORS.labels(step="check-stock").inc()
                    REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="409").inc()
                    return jsonify({"error": "Insufficient stock", "order_id": order_id, "status": "failed"}), 409

                price = stock_data.get("price", 0)
                total_amount = price * qty
                logger.info(f"[Order {order_id}] Stock OK. Price={price}, Total={total_amount}")

            except http_requests.exceptions.RequestException as e:
                ORCHESTRATION_ERRORS.labels(step="check-stock").inc()
                logger.error(f"[Order {order_id}] Product Service unreachable: {e}")
                REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="503").inc()
                return jsonify({"error": "Product Service unavailable", "order_id": order_id, "status": "failed"}), 503

        # === Step 2: Process Payment (Payment Service) ===
        with tracer.start_as_current_span("step2-payment"):
            try:
                logger.info(f"[Order {order_id}] Step 2: Processing payment...")
                resp = http_requests.post(
                    f"{PAYMENT_SERVICE_URL}/payments",
                    json={"order_id": order_id, "amount": total_amount, "customer_name": customer_name},
                    timeout=15
                )
                if resp.status_code != 200:
                    ORCHESTRATION_ERRORS.labels(step="payment").inc()
                    logger.error(f"[Order {order_id}] Payment failed: {resp.text}")
                    REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="402").inc()
                    return jsonify({"error": "Payment failed", "order_id": order_id, "status": "failed"}), 402

                payment_data = resp.json()
                txn_id = payment_data.get("txn_id")
                logger.info(f"[Order {order_id}] Payment OK. TXN={txn_id}")

            except http_requests.exceptions.RequestException as e:
                ORCHESTRATION_ERRORS.labels(step="payment").inc()
                logger.error(f"[Order {order_id}] Payment Service unreachable: {e}")
                REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="503").inc()
                return jsonify({"error": "Payment Service unavailable", "order_id": order_id, "status": "failed"}), 503

        # === Step 3: Reserve Stock (Product Service) ===
        with tracer.start_as_current_span("step3-reserve-stock"):
            try:
                logger.info(f"[Order {order_id}] Step 3: Reserving stock...")
                resp = http_requests.post(
                    f"{PRODUCT_SERVICE_URL}/products/{product_id}/reserve",
                    json={"qty": qty},
                    timeout=10
                )
                if resp.status_code != 200:
                    ORCHESTRATION_ERRORS.labels(step="reserve-stock").inc()
                    logger.warning(f"[Order {order_id}] Stock reservation failed: {resp.text}")
                    # Payment đã thành công nhưng stock fail → cần handle (simplified for demo)

            except http_requests.exceptions.RequestException as e:
                ORCHESTRATION_ERRORS.labels(step="reserve-stock").inc()
                logger.error(f"[Order {order_id}] Reserve stock failed: {e}")

        # === Order Confirmed ===
        order = {
            "order_id": order_id,
            "product_id": product_id,
            "qty": qty,
            "customer_name": customer_name,
            "total_amount": total_amount,
            "txn_id": txn_id,
            "status": "confirmed",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        ORDERS[order_id] = order

        logger.info(f"[Order {order_id}] ✅ Order confirmed!")
        REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="201").inc()
        REQUEST_LATENCY.labels(endpoint="/orders").observe(time.time() - start)

        return jsonify(order), 201


if __name__ == "__main__":
    logger.info("Order Service starting on port 5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
