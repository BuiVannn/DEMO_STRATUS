"""
Product Service - Bounded Context: Quản lý sản phẩm & tồn kho
"""
import time
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
resource = Resource.create({"service.name": "product-service"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("product-service")

# --- Prometheus Metrics ---
REQUEST_COUNT = Counter("product_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("product_request_duration_seconds", "Request latency", ["endpoint"])

# --- In-memory Product Database ---
PRODUCTS = {
    "P001": {"id": "P001", "name": "Laptop Dell XPS 15", "price": 25000000, "stock": 10, "category": "electronics", "image": "💻"},
    "P002": {"id": "P002", "name": "iPhone 16 Pro", "price": 30000000, "stock": 5, "category": "electronics", "image": "📱"},
    "P003": {"id": "P003", "name": "AirPods Pro 3", "price": 6000000, "stock": 20, "category": "accessories", "image": "🎧"},
    "P004": {"id": "P004", "name": "Samsung Galaxy S25", "price": 22000000, "stock": 8, "category": "electronics", "image": "📱"},
    "P005": {"id": "P005", "name": "MacBook Air M4", "price": 32000000, "stock": 3, "category": "electronics", "image": "💻"},
    "P006": {"id": "P006", "name": "Bàn phím Keychron K8", "price": 2500000, "stock": 15, "category": "accessories", "image": "⌨️"},
    "P007": {"id": "P007", "name": "Màn hình LG 27'' 4K", "price": 8000000, "stock": 7, "category": "electronics", "image": "🖥️"},
    "P008": {"id": "P008", "name": "Chuột Logitech MX Master", "price": 2000000, "stock": 12, "category": "accessories", "image": "🖱️"},
}


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "product-service"}), 200


@app.route("/metrics", methods=["GET"])
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/products", methods=["GET"])
def list_products():
    start = time.time()
    
    # Query params cho filtering & search
    category = request.args.get("category")
    search = request.args.get("search", "").lower()
    in_stock = request.args.get("in_stock")  # "true" để chỉ lấy còn hàng
    
    filtered = list(PRODUCTS.values())
    
    if category:
        filtered = [p for p in filtered if p["category"] == category]
    if search:
        filtered = [p for p in filtered if search in p["name"].lower()]
    if in_stock == "true":
        filtered = [p for p in filtered if p["stock"] > 0]
    
    logger.info(f"Listing products: {len(filtered)} results (category={category}, search={search})")
    REQUEST_COUNT.labels(method="GET", endpoint="/products", status="200").inc()
    REQUEST_LATENCY.labels(endpoint="/products").observe(time.time() - start)
    
    return jsonify({
        "products": filtered,
        "total": len(filtered),
        "filters": {"category": category, "search": search or None, "in_stock": in_stock},
    }), 200

@app.route("/products/categories", methods=["GET"])
def list_categories():
    """Danh sách categories — hữu ích cho demo UI"""
    categories = list(set(p["category"] for p in PRODUCTS.values()))
    return jsonify({"categories": categories}), 200

@app.route("/products/stats", methods=["GET"])
def product_stats():
    """Thống kê tồn kho — agent có thể dùng để phát hiện anomaly"""
    total_products = len(PRODUCTS)
    total_stock = sum(p["stock"] for p in PRODUCTS.values())
    out_of_stock = sum(1 for p in PRODUCTS.values() if p["stock"] == 0)
    total_value = sum(p["price"] * p["stock"] for p in PRODUCTS.values())
    
    return jsonify({
        "total_products": total_products,
        "total_stock_units": total_stock,
        "out_of_stock_count": out_of_stock,
        "total_inventory_value": total_value,
        "avg_price": round(sum(p["price"] for p in PRODUCTS.values()) / total_products),
    }), 200

@app.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    start = time.time()
    product = PRODUCTS.get(product_id)
    if not product:
        REQUEST_COUNT.labels(method="GET", endpoint="/products/{id}", status="404").inc()
        return jsonify({"error": f"Product {product_id} not found"}), 404
    REQUEST_COUNT.labels(method="GET", endpoint="/products/{id}", status="200").inc()
    REQUEST_LATENCY.labels(endpoint="/products/{id}").observe(time.time() - start)
    return jsonify(product), 200


@app.route("/products/<product_id>/check-stock", methods=["GET"])
def check_stock(product_id):
    """Kiểm tra tồn kho — được gọi bởi Order Service"""
    start = time.time()
    with tracer.start_as_current_span("check-stock") as span:
        qty = request.args.get("qty", 1, type=int)
        product = PRODUCTS.get(product_id)

        if not product:
            span.set_attribute("stock.available", False)
            REQUEST_COUNT.labels(method="GET", endpoint="/check-stock", status="404").inc()
            return jsonify({"error": "Product not found"}), 404

        available = product["stock"] >= qty
        span.set_attribute("product.id", product_id)
        span.set_attribute("stock.requested", qty)
        span.set_attribute("stock.current", product["stock"])
        span.set_attribute("stock.available", available)

        logger.info(f"Check stock: {product_id}, requested={qty}, current={product['stock']}, available={available}")

        status = "200" if available else "200"
        REQUEST_COUNT.labels(method="GET", endpoint="/check-stock", status=status).inc()
        REQUEST_LATENCY.labels(endpoint="/check-stock").observe(time.time() - start)

        return jsonify({
            "product_id": product_id,
            "available": available,
            "current_stock": product["stock"],
            "price": product["price"]
        }), 200


@app.route("/products/<product_id>/reserve", methods=["POST"])
def reserve_stock(product_id):
    """Trừ tồn kho — được gọi bởi Order Service sau khi payment thành công"""
    start = time.time()
    with tracer.start_as_current_span("reserve-stock") as span:
        data = request.get_json() or {}
        qty = data.get("qty", 1)
        product = PRODUCTS.get(product_id)

        if not product:
            REQUEST_COUNT.labels(method="POST", endpoint="/reserve", status="404").inc()
            return jsonify({"error": "Product not found"}), 404

        if product["stock"] < qty:
            span.set_attribute("reserve.success", False)
            REQUEST_COUNT.labels(method="POST", endpoint="/reserve", status="409").inc()
            return jsonify({"error": "Insufficient stock", "reserved": False}), 409

        product["stock"] -= qty
        span.set_attribute("product.id", product_id)
        span.set_attribute("reserve.qty", qty)
        span.set_attribute("reserve.remaining", product["stock"])
        span.set_attribute("reserve.success", True)

        logger.info(f"Reserved: {product_id}, qty={qty}, remaining={product['stock']}")

        REQUEST_COUNT.labels(method="POST", endpoint="/reserve", status="200").inc()
        REQUEST_LATENCY.labels(endpoint="/reserve").observe(time.time() - start)

        return jsonify({"reserved": True, "remaining_stock": product["stock"]}), 200


if __name__ == "__main__":
    logger.info("Product Service starting on port 5002")
    app.run(host="0.0.0.0", port=5002, debug=False)
