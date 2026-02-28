"""
Undo Agent - TNR (Transactional No-Regression) pattern.
Validate sau mitigation → rollback nếu hệ thống tệ hơn.
"""
import time
from models.states import SystemState
from tools.docker_tools import check_all_services_health, rollback_nginx_config


def validation_oracle(state: SystemState) -> dict:
    """
    Validation Oracle — kiểm tra hệ thống sau mitigation.
    So sánh trạng thái trước/sau để quyết định rollback.
    """
    print("\n" + "="*60)
    print("🧪 [Validation Oracle] Kiểm tra kết quả mitigation...")
    print("="*60)

    print("   ⏳ Chờ 3s để services ổn định...")
    time.sleep(3)

    # Health check hiện tại
    current_health = check_all_services_health.invoke({})
    print(f"\n   📋 Trạng thái hiện tại:")
    for line in current_health.split("\n"):
        emoji = "✅" if "HEALTHY" in line or "HTTP_200" in line or "RUNNING" in line else "❌"
        print(f"   {emoji} {line}")

    # Kiểm tra có lỗi không
    unhealthy_markers = ["UNHEALTHY", "UNREACHABLE", "NOT_FOUND", "CONTAINER_STOPPED", "CONTAINER_EXITED"]
    has_issues = any(marker in current_health.upper() for marker in unhealthy_markers)

    # Check HTTP status
    import requests
    try:
        r = requests.get("http://localhost/api/products", timeout=5)
        gateway_ok = r.status_code == 200
    except Exception:
        gateway_ok = False

    is_healthy = not has_issues and gateway_ok
    print(f"\n   {'✅ Hệ thống HEALTHY' if is_healthy else '❌ Hệ thống vẫn có vấn đề'}")

    return {
        "overall_status": "healthy" if is_healthy else "degraded",
    }

def validation_oracle_v2(state: SystemState) -> dict:
    """
    Validation Oracle — kiểm tra hệ thống sau mitigation.
    3 Oracles: System Health + Gateway HTTP + Service Metrics
    """
    print("\n" + "="*60)
    print("🧪 [Validation Oracle] Kiểm tra kết quả mitigation...")
    print("="*60)

    print("   ⏳ Chờ 3s để services ổn định...")
    time.sleep(3)

    oracles = []

    # Oracle 1: System Health Check
    print("   🔍 Oracle 1: System Health Check...")
    current_health = check_all_services_health.invoke({})
    for line in current_health.split("\n"):
        emoji = "✅" if "HEALTHY" in line or "HTTP_200" in line or "RUNNING" in line else "❌"
        print(f"   {emoji} {line}")

    unhealthy_markers = ["UNHEALTHY", "UNREACHABLE", "NOT_FOUND", "CONTAINER_STOPPED", "CONTAINER_EXITED"]
    health_ok = not any(marker in current_health.upper() for marker in unhealthy_markers)
    oracles.append(("System Health", health_ok))
    print(f"   Oracle 1: {'✅ PASS' if health_ok else '❌ FAIL'}")

    # Oracle 2: Gateway HTTP Test
    print("   🔍 Oracle 2: Gateway HTTP Test...")
    import requests
    gateway_ok = False
    try:
        r = requests.get("http://localhost/api/products", timeout=5)
        gateway_ok = r.status_code == 200
        print(f"   GET /api/products → {r.status_code}")
    except Exception as e:
        print(f"   Request failed: {e}")
    oracles.append(("Gateway HTTP", gateway_ok))
    print(f"   Oracle 2: {'✅ PASS' if gateway_ok else '❌ FAIL'}")

    # Oracle 3: Services Responding (kiểm tra từng service trực tiếp)
    print("   🔍 Oracle 3: Service Direct Check...")
    services_ok = True
    for svc_name, port in [("order-service", 5001), ("product-service", 5002), ("payment-service", 5003)]:
        try:
            r = requests.get(f"http://localhost:{port}/health", timeout=3)
            ok = r.status_code == 200
            if not ok:
                services_ok = False
            print(f"   {svc_name}: {'✅' if ok else '❌'} ({r.status_code})")
        except Exception:
            services_ok = False
            print(f"   {svc_name}: ❌ (unreachable)")
    oracles.append(("Services Direct", services_ok))
    print(f"   Oracle 3: {'✅ PASS' if services_ok else '❌ FAIL'}")

    # Final decision: ALL oracles must pass
    is_healthy = all(passed for _, passed in oracles)
    passed_count = sum(1 for _, passed in oracles if passed)
    print(f"\n   📊 Result: {passed_count}/{len(oracles)} oracles passed")
    print(f"   {'✅ Hệ thống HEALTHY — TNR COMMIT' if is_healthy else '❌ Hệ thống vẫn lỗi — TNR ROLLBACK'}")

    return {
        "overall_status": "healthy" if is_healthy else "degraded",
    }
def undo_agent(state: SystemState) -> dict:
    """
    Undo Agent — TNR Rollback.
    Kích hoạt khi Validation Oracle phát hiện mitigation thất bại.
    """
    print("\n" + "="*60)
    print("⏪ [Undo Agent] Kích hoạt TNR — Transactional No-Regression!")
    print("="*60)

    current_attempt = state.get("attempt_count", 0) + 1
    max_retries = state.get("max_retries", 3)

    print(f"   📊 Lần thử: {current_attempt}/{max_retries}")

    # Rollback Nginx config
    print("   ⏪ Rollback Nginx config...")
    rollback_msg = rollback_nginx_config.invoke({})
    print(f"   {rollback_msg}")

    actions_log = state.get("actions_taken", [])
    actions_log.append(f"TNR Rollback (attempt {current_attempt}) → {rollback_msg}")

    return {
        "attempt_count": current_attempt,
        "actions_taken": actions_log,
        "mitigation_result": {
            "success": False,
            "action_taken": "rollback",
            "message": rollback_msg,
            "target_service": "api-gateway",
        },
    }
