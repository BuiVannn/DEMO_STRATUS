"""Tracing tools - Query Jaeger cho Distributed Tracing."""
import requests
from langchain_core.tools import tool

JAEGER_URL = "http://localhost:16686"


@tool
def get_recent_traces(service_name: str, limit: int = 5) -> str:
    """
    Lấy các traces gần đây của 1 service từ Jaeger.
    Args:
        service_name: Tên service (vd: order-service, product-service, payment-service)
        limit: Số traces tối đa (mặc định 5)
    """
    try:
        resp = requests.get(
            f"{JAEGER_URL}/api/traces",
            params={"service": service_name, "limit": limit, "lookback": "1h"},
            timeout=10
        )
        data = resp.json()
        traces = data.get("data", [])

        if not traces:
            return f"No traces found for '{service_name}' in last 1h"

        lines = [f"Found {len(traces)} traces for '{service_name}':"]
        for t in traces:
            trace_id = t["traceID"]
            spans = t.get("spans", [])
            total_spans = len(spans)

            # Tìm root span
            root_span = None
            for s in spans:
                if not s.get("references"):
                    root_span = s
                    break
            if not root_span and spans:
                root_span = spans[0]

            if root_span:
                op = root_span.get("operationName", "unknown")
                duration_us = root_span.get("duration", 0)
                duration_ms = duration_us / 1000

                # Check for errors
                has_error = any(
                    tag.get("key") == "error" and tag.get("value") == True
                    for s in spans
                    for tag in s.get("tags", [])
                )
                error_flag = " ❌ ERROR" if has_error else ""

                lines.append(
                    f"  [{trace_id[:12]}] {op} | {total_spans} spans | {duration_ms:.1f}ms{error_flag}"
                )

                # List spans
                for s in spans:
                    svc = s["processID"]
                    process = t.get("processes", {}).get(svc, {})
                    svc_name = process.get("serviceName", "unknown")
                    s_op = s.get("operationName", "?")
                    s_dur = s.get("duration", 0) / 1000

                    s_error = any(
                        tag.get("key") == "error" and tag.get("value") == True
                        for tag in s.get("tags", [])
                    )
                    err_mark = " ⚠️" if s_error else ""
                    lines.append(f"    → {svc_name}/{s_op}: {s_dur:.1f}ms{err_mark}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error querying Jaeger: {str(e)}"


@tool
def get_error_traces(service_name: str, limit: int = 5) -> str:
    """
    Lấy các traces có lỗi (error spans) từ Jaeger.
    Args:
        service_name: Tên service
        limit: Số traces tối đa
    """
    try:
        resp = requests.get(
            f"{JAEGER_URL}/api/traces",
            params={"service": service_name, "limit": limit * 3, "lookback": "1h", "tags": '{"error":"true"}'},
            timeout=10
        )
        data = resp.json()
        traces = data.get("data", [])

        # Filter traces that have error spans
        error_traces = []
        for t in traces:
            spans = t.get("spans", [])
            for s in spans:
                has_error = any(
                    tag.get("key") == "error" and tag.get("value") == True
                    for tag in s.get("tags", [])
                )
                if has_error:
                    error_traces.append(t)
                    break

        if not error_traces:
            return f"No error traces found for '{service_name}'"

        lines = [f"Found {len(error_traces)} error traces for '{service_name}':"]
        for t in error_traces[:limit]:
            trace_id = t["traceID"]
            spans = t.get("spans", [])
            for s in spans:
                has_error = any(
                    tag.get("key") == "error" and tag.get("value") == True
                    for tag in s.get("tags", [])
                )
                if has_error:
                    svc = s["processID"]
                    process = t.get("processes", {}).get(svc, {})
                    svc_name = process.get("serviceName", "unknown")
                    op = s.get("operationName", "?")
                    dur = s.get("duration", 0) / 1000

                    # Get error logs
                    error_logs = []
                    for log in s.get("logs", []):
                        for field in log.get("fields", []):
                            if field.get("key") in ("message", "error", "error.message"):
                                error_logs.append(field.get("value", ""))

                    err_msg = "; ".join(error_logs) if error_logs else "no error message"
                    lines.append(
                        f"  [{trace_id[:12]}] {svc_name}/{op}: {dur:.1f}ms — {err_msg}"
                    )

        return "\n".join(lines)
    except Exception as e:
        return f"Error querying Jaeger: {str(e)}"


@tool
def get_services_from_jaeger() -> str:
    """Liệt kê tất cả services đang gửi traces về Jaeger."""
    try:
        resp = requests.get(f"{JAEGER_URL}/api/services", timeout=10)
        data = resp.json()
        services = data.get("data", [])
        if not services:
            return "No services found in Jaeger"
        return "Services in Jaeger:\n" + "\n".join(f"  - {s}" for s in services)
    except Exception as e:
        return f"Error querying Jaeger services: {str(e)}"
