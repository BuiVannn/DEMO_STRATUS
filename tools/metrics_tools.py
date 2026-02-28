"""Metrics tools - Query Prometheus cho SRE Agent."""
import requests
from langchain_core.tools import tool

PROMETHEUS_URL = "http://localhost:9090"


def _query_prometheus(query: str) -> dict:
    """Helper: query Prometheus instant query API."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=10)
        data = resp.json()
        if data.get("status") == "success":
            return data.get("data", {})
        return {"error": data.get("error", "Unknown error")}
    except Exception as e:
        return {"error": str(e)}


@tool
def query_prometheus(promql_query: str) -> str:
    """
    Thực thi PromQL query trên Prometheus.
    Args:
        promql_query: PromQL query string (vd: 'up', 'rate(order_requests_total[1m])')
    """
    result = _query_prometheus(promql_query)
    if "error" in result:
        return f"Prometheus query error: {result['error']}"

    results = result.get("result", [])
    if not results:
        return "No data returned"

    lines = []
    for r in results:
        metric = r.get("metric", {})
        value = r.get("value", [None, None])
        label_str = ", ".join(f'{k}="{v}"' for k, v in metric.items() if k != "__name__")
        name = metric.get("__name__", "unknown")
        lines.append(f"{name}{{{label_str}}}: {value[1]}")

    return "\n".join(lines)


@tool
def get_service_error_rate(service_name: str) -> str:
    """
    Tính error rate (tỷ lệ lỗi) của 1 service dựa trên Prometheus metrics.
    Args:
        service_name: Tên service (order, product, payment)
    """
    # Total requests rate
    total_query = f'sum(rate({service_name}_requests_total[1m]))'
    error_query = f'sum(rate({service_name}_requests_total{{status=~"4..|5.."}}[1m]))'

    total_data = _query_prometheus(total_query)
    error_data = _query_prometheus(error_query)

    total_results = total_data.get("result", [])
    error_results = error_data.get("result", [])

    total_rate = float(total_results[0]["value"][1]) if total_results else 0
    error_rate = float(error_results[0]["value"][1]) if error_results else 0

    if total_rate > 0:
        pct = (error_rate / total_rate) * 100
        return f"Service '{service_name}': error_rate={pct:.2f}% ({error_rate:.4f}/{total_rate:.4f} req/s)"
    else:
        return f"Service '{service_name}': no traffic detected (total_rate=0)"


@tool
def get_service_latency(service_name: str) -> str:
    """
    Lấy latency percentiles (P50, P95, P99) của 1 service.
    Args:
        service_name: Tên service (order, product, payment)
    """
    results = []
    for p in ["0.5", "0.95", "0.99"]:
        query = f'histogram_quantile({p}, sum(rate({service_name}_request_duration_seconds_bucket[1m])) by (le, endpoint))'
        data = _query_prometheus(query)
        query_results = data.get("result", [])
        if query_results:
            for r in query_results:
                endpoint = r["metric"].get("endpoint", "all")
                val = float(r["value"][1])
                results.append(f"  P{int(float(p)*100)} {endpoint}: {val*1000:.1f}ms")

    if results:
        return f"Latency for '{service_name}':\n" + "\n".join(results)
    return f"No latency data for '{service_name}'"


@tool
def get_all_services_metrics() -> str:
    """
    Lấy tổng quan metrics của tất cả services: request rate, error rate, up status.
    """
    lines = []

    # Check UP status
    up_data = _query_prometheus("up")
    up_results = up_data.get("result", [])
    lines.append("=== Service UP Status ===")
    for r in up_results:
        job = r["metric"].get("job", "unknown")
        val = r["value"][1]
        status = "UP ✅" if val == "1" else "DOWN ❌"
        lines.append(f"  {job}: {status}")

    # Request rates per service
    lines.append("\n=== Request Rates (req/s, last 1m) ===")
    for svc in ["order", "product", "payment"]:
        query = f'sum(rate({svc}_requests_total[1m]))'
        data = _query_prometheus(query)
        results = data.get("result", [])
        rate = float(results[0]["value"][1]) if results else 0
        lines.append(f"  {svc}-service: {rate:.4f} req/s")

    return "\n".join(lines)
