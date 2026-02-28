"""
SRE Dashboard — Real-time monitoring & agent activity visualization.
Flask + SocketIO server.
"""
import os
import sys
import time
import json
import threading
import requests
from flask import Flask, render_template, jsonify, request, Response
from flask_socketio import SocketIO

# Thêm project root vào path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

app = Flask(__name__)
app.config["SECRET_KEY"] = "sre-demo-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Service registry ---
SERVICES = {
    "api-gateway": {"port": 80, "type": "gateway", "health_url": "http://localhost:80/health"},
    "order-service": {"port": 5001, "type": "business", "health_url": "http://localhost:5001/health"},
    "product-service": {"port": 5002, "type": "business", "health_url": "http://localhost:5002/health"},
    "payment-service": {"port": 5003, "type": "business", "health_url": "http://localhost:5003/health"},
}

# --- Internal Docker URLs (dashboard → service containers) ---
# Nếu dashboard chạy trong Docker cùng network thì dùng service name
# Nếu dashboard chạy trên host thì dùng localhost
INTERNAL_URLS = {
    "api-gateway": os.getenv("GATEWAY_URL", "http://localhost:80"),
    "order-service": os.getenv("ORDER_SERVICE_URL", "http://localhost:5001"),
    "product-service": os.getenv("PRODUCT_SERVICE_URL", "http://localhost:5002"),
    "payment-service": os.getenv("PAYMENT_SERVICE_URL", "http://localhost:5003"),
}

# --- Agent activity log (in-memory) ---
agent_logs = []


def check_service_status(name, info):
    """Check health of a single service."""
    try:
        r = requests.get(info["health_url"], timeout=3)
        return {
            "name": name,
            "status": "healthy" if r.status_code == 200 else "unhealthy",
            "http_code": r.status_code,
            "type": info["type"],
        }
    except Exception:
        return {"name": name, "status": "down", "http_code": 0, "type": info["type"]}


def background_monitor():
    """Background thread: poll service health every 3 seconds."""
    while True:
        statuses = []
        for name, info in SERVICES.items():
            statuses.append(check_service_status(name, info))
        socketio.emit("service_status", {"services": statuses, "timestamp": time.strftime("%H:%M:%S")})
        time.sleep(3)


# =============================================
# Dashboard pages
# =============================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """REST endpoint for current service status."""
    statuses = []
    for name, info in SERVICES.items():
        statuses.append(check_service_status(name, info))
    return jsonify({"services": statuses})


# =============================================
# Proxy routes — Dashboard forward tới services
# Browser gọi dashboard:8888/proxy/... → dashboard forward tới service thật
# =============================================

def _proxy_request(target_url):
    """Forward request từ browser → service thật, trả response JSON."""
    try:
        if request.method == "GET":
            resp = requests.get(target_url, timeout=10)
        elif request.method == "POST":
            resp = requests.post(
                target_url,
                json=request.get_json(silent=True),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        elif request.method == "PUT":
            resp = requests.put(
                target_url,
                json=request.get_json(silent=True),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        elif request.method == "DELETE":
            resp = requests.delete(target_url, timeout=10)
        else:
            return jsonify({"error": f"Unsupported method: {request.method}"}), 405

        # Forward response as-is
        try:
            data = resp.json()
            return jsonify(data), resp.status_code
        except ValueError:
            # Response không phải JSON
            return Response(resp.text, status=resp.status_code, content_type=resp.headers.get("Content-Type", "text/plain"))

    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Service unreachable", "target": target_url}), 502
    except requests.exceptions.Timeout:
        return jsonify({"error": "Service timeout", "target": target_url}), 504
    except Exception as e:
        return jsonify({"error": str(e), "target": target_url}), 500


# --- Nginx Gateway proxy routes ---
@app.route("/proxy/gateway/health", methods=["GET"])
def proxy_gateway_health():
    return _proxy_request(f"{INTERNAL_URLS['api-gateway']}/health")


@app.route("/proxy/gateway/products", methods=["GET"])
def proxy_gateway_products():
    """Proxy: thử qua gateway, fallback trực tiếp product-service"""
    url = f"{INTERNAL_URLS['api-gateway']}/api/products"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code < 500:
            try:
                return jsonify(resp.json()), resp.status_code
            except ValueError:
                pass
    except Exception:
        pass
    # Fallback: gọi trực tiếp
    fallback_url = f"{INTERNAL_URLS['product-service']}/products"
    return _proxy_request(fallback_url)


@app.route("/proxy/gateway/orders", methods=["GET", "POST"])
def proxy_gateway_orders():
    """Proxy: thử qua gateway, fallback trực tiếp order-service"""
    url = f"{INTERNAL_URLS['api-gateway']}/api/orders"
    try:
        if request.method == "GET":
            resp = requests.get(url, timeout=5)
        else:
            resp = requests.post(
                url,
                json=request.get_json(silent=True),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
        if resp.status_code < 500:
            try:
                return jsonify(resp.json()), resp.status_code
            except ValueError:
                pass
    except Exception:
        pass
    # Fallback
    fallback_url = f"{INTERNAL_URLS['order-service']}/orders"
    return _proxy_request(fallback_url)


# --- Order Service direct proxy ---
@app.route("/proxy/order-service/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_order_service(subpath):
    url = f"{INTERNAL_URLS['order-service']}/{subpath}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"
    return _proxy_request(url)


# --- Product Service direct proxy ---
@app.route("/proxy/product-service/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_product_service(subpath):
    url = f"{INTERNAL_URLS['product-service']}/{subpath}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"
    return _proxy_request(url)


# --- Payment Service direct proxy ---
@app.route("/proxy/payment-service/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_payment_service(subpath):
    url = f"{INTERNAL_URLS['payment-service']}/{subpath}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"
    return _proxy_request(url)


# =============================================
# Agent log & workflow endpoints
# =============================================

@app.route("/api/agent-log", methods=["POST"])
def add_agent_log():
    """Nhận log từ SRE agent workflow (gọi từ main_v2.py)."""
    data = json.loads(request.data) if request.data else {}
    entry = {
        "timestamp": time.strftime("%H:%M:%S"),
        "agent": data.get("agent", "unknown"),
        "action": data.get("action", data.get("message", "")),
        "phase": data.get("phase", ""),
        "type": data.get("type", "action"),
    }
    agent_logs.append(entry)
    if len(agent_logs) > 200:
        agent_logs.pop(0)
    socketio.emit("agent_event", entry)
    return jsonify({"ok": True})


@app.route("/api/agent-logs")
def get_agent_logs():
    return jsonify({"logs": agent_logs[-50:]})


@app.route("/api/start-agent", methods=["POST"])
def start_agent():
    """Trigger SRE agent workflow trong background thread."""
    def run_agent():
        try:
            from dotenv import load_dotenv
            load_dotenv()
            from langchain_openai import ChatOpenAI
            from graph import build_sre_graph, set_event_callback

            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
            )

            # Register callback: mỗi event từ graph sẽ emit qua SocketIO
            def on_agent_event(event: dict):
                entry = {
                    "timestamp": event.get("timestamp", time.strftime("%H:%M:%S")),
                    "agent": event.get("agent", "unknown"),
                    "action": event.get("action", ""),
                    "phase": event.get("phase", ""),
                    "type": event.get("type", "action"),
                }
                agent_logs.append(entry)
                socketio.emit("agent_event", entry)

            set_event_callback(on_agent_event)

            graph = build_sre_graph(llm)

            initial_state = {
                "symptoms": [],
                "triage_summary": "",
                "overall_status": "",
                "services_health": [],
                "container_logs": "",
                "metrics_data": "",
                "tracing_data": "",
                "pre_fix_health": "",
                "mitigation_plan": None,
                "mitigation_result": None,
                "actions_taken": [],
                "attempt_count": 0,
                "max_retries": 3,
                "current_phase": "",
                "workflow_events": [],
            }

            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": "🚀 SRE Agent Workflow bắt đầu...",
                "phase": "start",
                "type": "action",
            })

            # Stream graph — events sẽ tự emit qua callback trong các node
            for step in graph.stream(initial_state, stream_mode="updates"):
                pass

            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": "✅ SRE Agent Workflow hoàn tất!",
                "phase": "done",
                "type": "tnr_commit",
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": f"❌ Error: {str(e)}",
                "phase": "error",
                "type": "circuit_breaker",
            })

    # Reset logs
    agent_logs.clear()
    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()
    return jsonify({"status": "Agent workflow started"})


@socketio.on("connect")
def handle_connect():
    """Khi client connect, gửi trạng thái hiện tại."""
    statuses = []
    for name, info in SERVICES.items():
        statuses.append(check_service_status(name, info))
    socketio.emit("service_status", {"services": statuses, "timestamp": time.strftime("%H:%M:%S")})
    socketio.emit("agent_logs_init", {"logs": agent_logs[-50:]})


if __name__ == "__main__":
    print("🖥️  SRE Dashboard starting on http://localhost:8888")
    print("   📊 Prometheus: http://localhost:9090")
    print("   🔍 Jaeger UI:  http://localhost:16686")
    print("   🔀 Proxy routes: /proxy/gateway/*, /proxy/order-service/*, etc.")

    monitor_thread = threading.Thread(target=background_monitor, daemon=True)
    monitor_thread.start()

    socketio.run(app, host="0.0.0.0", port=8888, debug=False, allow_unsafe_werkzeug=True)


'''
"""
SRE Dashboard — Real-time monitoring & agent activity visualization.
Flask + SocketIO server.
"""
import os
import sys
import time
import json
import threading
import requests
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

# Thêm project root vào path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

app = Flask(__name__)
app.config["SECRET_KEY"] = "sre-demo-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Service registry ---
SERVICES = {
    "api-gateway": {"port": 80, "type": "gateway", "health_url": "http://localhost:80/"},
    "order-service": {"port": 5001, "type": "business", "health_url": "http://localhost:5001/health"},
    "product-service": {"port": 5002, "type": "business", "health_url": "http://localhost:5002/health"},
    "payment-service": {"port": 5003, "type": "business", "health_url": "http://localhost:5003/health"},
}

# --- Agent activity log (in-memory) ---
agent_logs = []


def check_service_status(name, info):
    """Check health of a single service."""
    try:
        r = requests.get(info["health_url"], timeout=3)
        return {
            "name": name,
            "status": "healthy" if r.status_code == 200 else "unhealthy",
            "http_code": r.status_code,
            "type": info["type"],
        }
    except Exception:
        return {"name": name, "status": "down", "http_code": 0, "type": info["type"]}


def background_monitor():
    """Background thread: poll service health every 3 seconds."""
    while True:
        statuses = []
        for name, info in SERVICES.items():
            statuses.append(check_service_status(name, info))
        socketio.emit("service_status", {"services": statuses, "timestamp": time.strftime("%H:%M:%S")})
        time.sleep(3)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """REST endpoint for current service status."""
    statuses = []
    for name, info in SERVICES.items():
        statuses.append(check_service_status(name, info))
    return jsonify({"services": statuses})


@app.route("/api/agent-log", methods=["POST"])
def add_agent_log():
    """Nhận log từ SRE agent workflow (gọi từ main_v2.py)."""
    data = json.loads(request.data) if request.data else {}
    entry = {
        "timestamp": time.strftime("%H:%M:%S"),
        "agent": data.get("agent", "unknown"),
        "message": data.get("message", ""),
        "level": data.get("level", "info"),
        "phase": data.get("phase", ""),
        "type": data.get("type", "action"),
    }
    agent_logs.append(entry)
    if len(agent_logs) > 200:
        agent_logs.pop(0)
    socketio.emit("agent_event", entry)
    return jsonify({"ok": True})


@app.route("/api/agent-logs")
def get_agent_logs():
    return jsonify({"logs": agent_logs[-50:]})


@app.route("/api/start-agent", methods=["POST"])
def start_agent():
    """Trigger SRE agent workflow trong background thread."""
    def run_agent():
        try:
            from dotenv import load_dotenv
            load_dotenv()
            from langchain_openai import ChatOpenAI
            from graph import build_sre_graph, set_event_callback

            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
            )

            # Register callback: mỗi event từ graph sẽ emit qua SocketIO
            def on_agent_event(event: dict):
                entry = {
                    "timestamp": event.get("timestamp", time.strftime("%H:%M:%S")),
                    "agent": event.get("agent", "unknown"),
                    "action": event.get("action", ""),
                    "phase": event.get("phase", ""),
                    "type": event.get("type", "action"),
                }
                agent_logs.append(entry)
                socketio.emit("agent_event", entry)

            set_event_callback(on_agent_event)

            graph = build_sre_graph(llm)

            initial_state = {
                "symptoms": [],
                "triage_summary": "",
                "overall_status": "",
                "services_health": [],
                "container_logs": "",
                "metrics_data": "",
                "tracing_data": "",
                "pre_fix_health": "",
                "mitigation_plan": None,
                "mitigation_result": None,
                "actions_taken": [],
                "attempt_count": 0,
                "max_retries": 3,
                "current_phase": "",
                "workflow_events": [],
            }

            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": "🚀 SRE Agent Workflow bắt đầu...",
                "phase": "start",
                "type": "action",
            })

            # Stream graph — events sẽ tự emit qua callback
            for step in graph.stream(initial_state, stream_mode="updates"):
                pass  # Events đã được emit trong các node qua emit_event()

            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": "✅ SRE Agent Workflow hoàn tất!",
                "phase": "done",
                "type": "tnr_commit",
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": f"❌ Error: {str(e)}",
                "phase": "error",
                "type": "circuit_breaker",
            })

    # Reset logs
    agent_logs.clear()
    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()
    return jsonify({"status": "Agent workflow started"})


@socketio.on("connect")
def handle_connect():
    """Khi client connect, gửi trạng thái hiện tại."""
    statuses = []
    for name, info in SERVICES.items():
        statuses.append(check_service_status(name, info))
    socketio.emit("service_status", {"services": statuses, "timestamp": time.strftime("%H:%M:%S")})
    socketio.emit("agent_logs_init", {"logs": agent_logs[-50:]})


if __name__ == "__main__":
    print("🖥️  SRE Dashboard starting on http://localhost:8888")
    print("   📊 Prometheus: http://localhost:9090")
    print("   🔍 Jaeger UI:  http://localhost:16686")

    monitor_thread = threading.Thread(target=background_monitor, daemon=True)
    monitor_thread.start()

    socketio.run(app, host="0.0.0.0", port=8888, debug=False, allow_unsafe_werkzeug=True)
'''

'''
"""
SRE Dashboard — Real-time monitoring & agent activity visualization.
Flask + SocketIO server.
"""
import os
import sys
import time
import json
import threading
import requests
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

# Thêm project root vào path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

app = Flask(__name__)
app.config["SECRET_KEY"] = "sre-demo-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Service registry ---
SERVICES = {
    "api-gateway": {"port": 80, "type": "gateway", "health_url": "http://localhost:80/"},
    "order-service": {"port": 5001, "type": "business", "health_url": "http://localhost:5001/health"},
    "product-service": {"port": 5002, "type": "business", "health_url": "http://localhost:5002/health"},
    "payment-service": {"port": 5003, "type": "business", "health_url": "http://localhost:5003/health"},
}

# --- Agent activity log (in-memory) ---
agent_logs = []


def check_service_status(name, info):
    """Check health of a single service."""
    try:
        r = requests.get(info["health_url"], timeout=3)
        return {
            "name": name,
            "status": "healthy" if r.status_code == 200 else "unhealthy",
            "http_code": r.status_code,
            "type": info["type"],
        }
    except Exception:
        return {"name": name, "status": "down", "http_code": 0, "type": info["type"]}


def background_monitor():
    """Background thread: poll service health every 3 seconds."""
    while True:
        statuses = []
        for name, info in SERVICES.items():
            statuses.append(check_service_status(name, info))

        socketio.emit("service_status", {"services": statuses, "timestamp": time.strftime("%H:%M:%S")})
        time.sleep(3)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """REST endpoint for current service status."""
    statuses = []
    for name, info in SERVICES.items():
        statuses.append(check_service_status(name, info))
    return jsonify({"services": statuses})


@app.route("/api/agent-log", methods=["POST"])
def add_agent_log():
    """Nhận log từ SRE agent workflow (gọi từ main_v2.py)."""
    data = json.loads(request.data) if request.data else {}
    entry = {
        "timestamp": time.strftime("%H:%M:%S"),
        "agent": data.get("agent", "unknown"),
        "message": data.get("message", ""),
        "level": data.get("level", "info"),
        "phase": data.get("phase", ""),
        "type": data.get("type", "action"),
    }
    agent_logs.append(entry)
    if len(agent_logs) > 200:
        agent_logs.pop(0)

    # Emit qua SocketIO để dashboard real-time update
    socketio.emit("agent_event", entry)
    return jsonify({"ok": True})


@app.route("/api/agent-logs")
def get_agent_logs():
    return jsonify({"logs": agent_logs[-50:]})


@app.route("/api/start-agent", methods=["POST"])
def start_agent():
    """Trigger SRE agent workflow trong background thread."""
    def run_agent():
        try:
            from dotenv import load_dotenv
            load_dotenv()
            from langchain_openai import ChatOpenAI
            from graph import build_sre_graph

            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
            )
            graph = build_sre_graph(llm)

            initial_state = {
                "symptoms": [],
                "triage_summary": "",
                "overall_status": "",
                "services_health": [],
                "container_logs": "",
                "metrics_data": "",
                "tracing_data": "",
                "pre_fix_health": "",
                "mitigation_plan": None,
                "mitigation_result": None,
                "actions_taken": [],
                "attempt_count": 0,
                "max_retries": 3,
                "current_phase": "",
                "workflow_events": [],
            }

            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": "🚀 SRE Agent Workflow bắt đầu...",
                "phase": "start",
                "type": "action",
            })

            for step in graph.stream(initial_state, stream_mode="updates"):
                for node_name, node_output in step.items():
                    events = node_output.get("workflow_events", [])
                    if isinstance(events, list):
                        for ev in events:
                            socketio.emit("agent_event", {
                                "timestamp": ev.get("timestamp", time.strftime("%H:%M:%S")),
                                "agent": ev.get("agent", node_name),
                                "action": ev.get("action", ""),
                                "phase": ev.get("phase", ""),
                                "type": ev.get("type", "action"),
                            })
                            time.sleep(0.8)  # Visual delay

            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": "✅ SRE Agent Workflow hoàn tất!",
                "phase": "done",
                "type": "tnr_commit",
            })

        except Exception as e:
            socketio.emit("agent_event", {
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": "System",
                "action": f"❌ Error: {str(e)}",
                "phase": "error",
                "type": "circuit_breaker",
            })

    # Reset logs
    agent_logs.clear()
    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()
    return jsonify({"status": "Agent workflow started"})


@socketio.on("connect")
def handle_connect():
    """Khi client connect, gửi trạng thái hiện tại."""
    statuses = []
    for name, info in SERVICES.items():
        statuses.append(check_service_status(name, info))
    socketio.emit("service_status", {"services": statuses, "timestamp": time.strftime("%H:%M:%S")})
    socketio.emit("agent_logs_init", {"logs": agent_logs[-50:]})


if __name__ == "__main__":
    print("🖥️  SRE Dashboard starting on http://localhost:8888")
    print("   📊 Prometheus: http://localhost:9090")
    print("   🔍 Jaeger UI:  http://localhost:16686")

    monitor_thread = threading.Thread(target=background_monitor, daemon=True)
    monitor_thread.start()

    socketio.run(app, host="0.0.0.0", port=8888, debug=False, allow_unsafe_werkzeug=True)

'''

