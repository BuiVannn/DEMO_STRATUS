"""Docker tools - Multi-container operations cho SRE Agent."""
import docker
import time
import base64
from langchain_core.tools import tool

try:
    client = docker.from_env()
except Exception as e:
    print(f"Error initializing Docker client: {e}")
    client = None

# Danh sách container cần quản lý
MANAGED_CONTAINERS = ["order-service", "product-service", "payment-service", "api-gateway"]
NGINX_CONTAINER = "api-gateway"
NGINX_CONFIG_PATH = "/etc/nginx/nginx.conf"
NGINX_BACKUP_PATH = "/etc/nginx/nginx.conf.bak"


def _get_container(name: str):
    """Helper: lấy container theo tên."""
    try:
        return client.containers.get(name)
    except docker.errors.NotFound:
        return None
    except Exception:
        return None


@tool
def check_all_services_health() -> str:
    """
    Kiểm tra sức khỏe tất cả services trong hệ thống.
    Trả về trạng thái chi tiết từng container và HTTP health check.
    """
    import requests
    results = []
    health_endpoints = {
        "order-service": "http://localhost:5001/health",
        "product-service": "http://localhost:5002/health",
        "payment-service": "http://localhost:5003/health",
    }

    for name in MANAGED_CONTAINERS:
        container = _get_container(name)
        if not container:
            results.append(f"{name}: NOT_FOUND")
            continue

        status = container.status
        if status != "running":
            results.append(f"{name}: CONTAINER_{status.upper()}")
            continue

        # HTTP health check cho business services
        if name in health_endpoints:
            try:
                r = requests.get(health_endpoints[name], timeout=5)
                if r.status_code == 200:
                    results.append(f"{name}: HEALTHY (HTTP 200)")
                else:
                    results.append(f"{name}: UNHEALTHY (HTTP {r.status_code})")
            except Exception as e:
                results.append(f"{name}: UNREACHABLE ({str(e)[:50]})")
        else:
            # nginx / infra containers
            results.append(f"{name}: RUNNING")

    # Gateway check
    try:
        import requests
        r = requests.get("http://localhost:80/", timeout=5)
        results.append(f"api-gateway-http: HTTP_{r.status_code}")
    except Exception:
        results.append("api-gateway-http: UNREACHABLE")

    return "\n".join(results)


@tool
def check_service_health(service_name: str) -> str:
    """
    Kiểm tra sức khỏe 1 service cụ thể.
    Args:
        service_name: Tên container (vd: order-service, product-service, payment-service)
    """
    import requests
    container = _get_container(service_name)
    if not container:
        return f"UNHEALTHY: Container '{service_name}' not found"

    if container.status != "running":
        return f"UNHEALTHY: Container '{service_name}' is {container.status}"

    port_map = {"order-service": 5001, "product-service": 5002, "payment-service": 5003}
    port = port_map.get(service_name)

    if port:
        try:
            r = requests.get(f"http://localhost:{port}/health", timeout=5)
            if r.status_code == 200:
                return f"HEALTHY: {service_name} running, HTTP 200"
            else:
                return f"UNHEALTHY: {service_name} returned HTTP {r.status_code}"
        except Exception as e:
            return f"UNHEALTHY: {service_name} unreachable - {str(e)[:80]}"

    return f"RUNNING: {service_name} container is up"


@tool
def read_service_logs(service_name: str, tail: int = 30) -> str:
    """
    Đọc logs của 1 service container.
    Args:
        service_name: Tên container
        tail: Số dòng log cuối cần đọc (mặc định 30)
    """
    container = _get_container(service_name)
    if not container:
        return f"Error: Container '{service_name}' not found"
    try:
        logs = container.logs(tail=tail).decode("utf-8")
        return logs if logs.strip() else "(No logs available)"
    except Exception as e:
        return f"Error reading logs: {str(e)}"


@tool
def restart_container(service_name: str) -> str:
    """
    Restart 1 container service.
    Args:
        service_name: Tên container cần restart
    """
    container = _get_container(service_name)
    if not container:
        return f"Error: Container '{service_name}' not found"
    try:
        container.restart(timeout=10)
        time.sleep(5)
        container.reload()
        return f"Container '{service_name}' restarted successfully. Status: {container.status}"
    except Exception as e:
        return f"Error restarting '{service_name}': {str(e)}"


@tool
def apply_nginx_config(config_content: str) -> str:
    """
    Cập nhật file config Nginx và reload.
    Thực hiện 3 bước: backup → ghi config mới → reload.
    Args:
        config_content: Nội dung đầy đủ file nginx.conf mới
    """
    container = _get_container(NGINX_CONTAINER)
    if not container:
        return "Error: api-gateway container not found"

    try:
        if container.status != "running":
            container.start()
            time.sleep(3)
            container.reload()

        # 1. Backup config cũ
        container.exec_run(f"cp {NGINX_CONFIG_PATH} {NGINX_BACKUP_PATH}")

        # 2. Ghi config mới (dùng base64 để tránh lỗi escape)
        b64 = base64.b64encode(config_content.encode("utf-8")).decode("utf-8")
        cmd = f"sh -c 'echo {b64} | base64 -d > {NGINX_CONFIG_PATH}'"
        result = container.exec_run(cmd)
        if result.exit_code != 0:
            return f"Failed to write config: {result.output.decode()}"

        # 3. Test config trước khi reload
        test_result = container.exec_run("nginx -t")
        if test_result.exit_code != 0:
            # Config lỗi → rollback ngay
            container.exec_run(f"cp {NGINX_BACKUP_PATH} {NGINX_CONFIG_PATH}")
            return f"Config test FAILED (auto-rolled back): {test_result.output.decode()}"

        # 4. Reload
        reload_result = container.exec_run("nginx -s reload")
        if reload_result.exit_code != 0:
            return f"Reload FAILED: {reload_result.output.decode()}"

        return "Nginx config applied and reloaded successfully."
    except Exception as e:
        return f"Error applying config: {str(e)}"


@tool
def rollback_nginx_config() -> str:
    """
    Rollback Nginx config về bản backup trước đó (TNR - Undo).
    Khôi phục file backup và restart container.
    """
    container = _get_container(NGINX_CONTAINER)
    if not container:
        return "Error: api-gateway container not found"

    try:
        if container.status != "running":
            container.start()
            time.sleep(3)
            container.reload()

        # Kiểm tra backup tồn tại
        check = container.exec_run(f"test -f {NGINX_BACKUP_PATH}")
        if check.exit_code != 0:
            return "No backup found to rollback"

        container.exec_run(f"cp {NGINX_BACKUP_PATH} {NGINX_CONFIG_PATH}")
        container.restart(timeout=10)
        time.sleep(3)

        return "Rollback completed. Nginx restarted with previous config."
    except Exception as e:
        return f"Error during rollback: {str(e)}"


@tool
def get_container_stats() -> str:
    """
    Lấy thông tin resource usage (CPU, Memory) của tất cả managed containers.
    """
    results = []
    for name in MANAGED_CONTAINERS:
        container = _get_container(name)
        if not container or container.status != "running":
            results.append(f"{name}: not running")
            continue
        try:
            stats = container.stats(stream=False)
            # CPU
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
            cpu_pct = (cpu_delta / system_delta) * 100.0 if system_delta > 0 else 0.0

            # Memory
            mem_usage = stats["memory_stats"].get("usage", 0) / (1024 * 1024)
            mem_limit = stats["memory_stats"].get("limit", 1) / (1024 * 1024)

            results.append(f"{name}: CPU={cpu_pct:.2f}%, Memory={mem_usage:.1f}MB/{mem_limit:.0f}MB")
        except Exception as e:
            results.append(f"{name}: stats error ({str(e)[:50]})")

    return "\n".join(results)
