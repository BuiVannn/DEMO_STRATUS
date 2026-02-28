import docker
import time
from langchain_core.tools import tool

import base64
# khởi tạo docker client

try:
    client = docker.from_env()
    CONTAINER_NAME = "demo-nginx"
    CONFIG_PATH = "/etc/nginx/nginx.conf"
    BACKUP_PATH = "/etc/nginx/nginx.conf.bak"

except Exception as e:
    print(f"Error initializing Docker client: {e}")

def ensure_container_running(container):
    if container.status != 'running':
        print(f"Container {container.name} is not running. Starting it now...")
        container.start()
        time.sleep(3)
        container.reload()
        print(f"[Docker tool] container đã bật (Status: {container.status})")

# Các tool cho agent

@tool
def check_system_health():
    """
    Sử dụng tool này để kiểm tra sức khoẻ hệ thống (Detection agent)
    Trả về 'HEALTHY' nếu Nginx đang chạy và phản hồi 200
    Trả về 'UNHEALTHY' kèm lý do nếu Nginx không chạy hoặc phản hồi lỗi
    """
    try:
        container = client.containers.get(CONTAINER_NAME)

        # Kiểm tra trạng thái container
        if container.status != 'running':
            return "UNHEALTHY: Container is stopped/exited."
        
        # Kiem tra phản hồi HTTP
        exit_code, output = container.exec_run("curl -s -o /dev/null -w '%{http_code}' http://localhost")
        status_code = output.decode().strip()

        if status_code == '200':
            return "HEALTHY"
        else:
            return f"UNHEALTHY: Nginx returned status code {status_code}."
    
    except docker.errors.NotFound:
        return "UNHEALTHY: Container not found."
    except Exception as e:
        return f"UNHEALTHY: Error occurred - {str(e)}"


@tool
def read_logs():
    """
    Sử dụng tool này để đọc logs của Nginx (Diagnosis agent)
    Giúp tìm nguyên nhân gốc rễ của lỗi (ví dụ: sai cú pháp config)
    """
    try:
        container = client.containers.get(CONTAINER_NAME)
        # lấy 20 dòng log cuối
        logs = container.logs(tail=20).decode("utf-8")
        return logs
    except Exception as e:
        return f"Error reading logs: {str(e)}"
    

@tool
def apply_fix_and_reload(config_content : str):
    """
    Sử dụng tool này để sửa lỗi (Mitigation Agent)
    Hàm này thực hiện 3 bước:
    1. Backup file config cũ (tạo checkpoint cho TNR)
    2. Ghi nội dung config mới vào file
    3. Reload Nginx để áp dụng config mới

    Args:
        config_content: Nội dung đầy đủ của file nginx.conf mới.
    """

    try:
        container = client.containers.get(CONTAINER_NAME)

        ensure_container_running(container)

        # 1. backup
        container.exec_run(f"cp {CONFIG_PATH} {BACKUP_PATH}")

        b64_bytes = base64.b64encode(config_content.encode('utf-8'))
        b64_string = b64_bytes.decode('utf-8')
        cmd = f"bash -c 'echo {b64_string} | base64 -d > {CONFIG_PATH}'"
        exec_result = container.exec_run(cmd)
        
        # 2. Ghi file mới
        # cmd = f"bash -c 'cat <<EOF > {CONFIG_PATH}\n{config_content}\nEOF'"
        # exec_result = container.exec_run(cmd)

        if exec_result.exit_code != 0:
            return f"Failed to write config: {exec_result.output.decode()}"
        
        # 3. Reload
        reload_result = container.exec_run("nginx -s reload")

        if reload_result.exit_code != 0:
            return f"Config applied but Reload failed: {reload_result.output.decode()}"
        
        return "Fix applied and Nginx reloaded successfully."
    
    except Exception as e:
        return f"Error applying fix: {str(e)}"
    

@tool
def rollback_changes():
    """
    Sử dụng tool này để hoàn tác (Undo agent)
    Kích hoạt khi cơ chế TNR phát hiện sửa lỗi không thành công.
    Khôi phục file backup và restart container Nginx.
    """
    try: 
        container = client.containers.get(CONTAINER_NAME)

        ensure_container_running(container)

        # khôi phục file backup
        container.exec_run(f"cp {BACKUP_PATH} {CONFIG_PATH}")

        # restart Nginx
        container.restart()

        # chờ một chút để Nginx khởi động lại
        time.sleep(3)

        return "Rollback completed and Nginx restarted."
    except Exception as e:
        return f"Error during rollback: {str(e)}"
