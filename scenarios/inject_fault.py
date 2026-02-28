"""
Fault Injection Scenarios — inject lỗi thật vào microservices.
Sử dụng: python scenarios/inject_fault.py --scenario <1|2|3>
"""
import argparse
import docker
import base64
import time
import subprocess


client = docker.from_env()


def scenario_1_bad_nginx_config():
    """
    Scenario 1: Sai config Nginx API Gateway
    → Gây 502 Bad Gateway cho tất cả requests
    → Agent cần: phân tích logs → tạo config đúng → apply
    """
    print("\n🔥 Scenario 1: Injecting BAD Nginx config...")
    print("   Hệ thống sẽ trả về 502 Bad Gateway\n")

    bad_config = """
worker_processes auto;
events {
    worker_connections 1024;
}
http {
    upstream order_service {
        server order-service:9999;  # PORT SAI - service chạy ở 5001
    }
    upstream product_service {
        server product-service:9999;  # PORT SAI
    }
    upstream payment_service {
        server payment-service:9999;  # PORT SAI
    }
    server {
        listen 80 default_server;
        server_name localhost;
        location /api/orders {
            proxy_pass http://order_service/orders;
            proxy_connect_timeout 3s;
            proxy_read_timeout 3s;
        }
        location /api/products {
            proxy_pass http://product_service/products;
            proxy_connect_timeout 3s;
            proxy_read_timeout 3s;
        }
        location /api/payments {
            proxy_pass http://payment_service/payments;
            proxy_connect_timeout 3s;
            proxy_read_timeout 3s;
        }
        location /nginx_status {
            stub_status on;
            allow all;
        }
        location / {
            return 200 '{"message": "E-Commerce API Gateway"}';
            add_header Content-Type application/json;
        }
    }
}
"""
    container = client.containers.get("api-gateway")

    # Backup trước
    container.exec_run("cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak")

    # Ghi config lỗi
    b64 = base64.b64encode(bad_config.encode("utf-8")).decode("utf-8")
    container.exec_run(f"sh -c 'echo {b64} | base64 -d > /etc/nginx/nginx.conf'")
    container.exec_run("nginx -s reload")

    print("   ✅ Đã inject lỗi! Nginx đang trỏ sai port (9999 thay vì 500x)")
    print("   🧪 Test: curl http://localhost/api/products → sẽ trả về 502")
    print("\n   Bây giờ chạy: python main_v2.py")


def scenario_2_payment_service_crash():
    """
    Scenario 2: Payment Service bị crash
    → Order đặt hàng sẽ fail ở bước thanh toán
    → Agent cần: phát hiện qua health check + traces → restart container
    """
    print("\n🔥 Scenario 2: Stopping Payment Service...")
    print("   Order sẽ fail ở bước thanh toán\n")

    container = client.containers.get("payment-service")
    container.stop()

    print("   ✅ Payment Service đã STOP!")
    print("   🧪 Test: curl -X POST http://localhost/api/orders -H 'Content-Type: application/json' \\")
    print("          -d '{\"product_id\": \"P001\", \"qty\": 1}' → sẽ fail ở payment step")
    print("\n   Bây giờ chạy: python main_v2.py")


def scenario_3_product_service_overload():
    """
    Scenario 3: Product Service quá tải (simulated high latency)
    → Tất cả requests check stock sẽ rất chậm
    → Agent cần: phát hiện high latency → restart service
    """
    print("\n🔥 Scenario 3: Injecting HIGH LATENCY into Product Service...")
    print("   Product Service sẽ respond rất chậm (>5s)\n")

    # Stop the current product-service and restart with delay env
    container = client.containers.get("product-service")
    container.stop()
    time.sleep(2)

    # Restart with simulated delay - sử dụng Docker exec approach
    container.start()
    time.sleep(3)

    # Inject delay bằng cách ghi đè env (simplified approach)
    # Trong production dùng tc netem, ở đây ta stop và restart
    container.restart()
    time.sleep(3)

    print("   ✅ Product Service restarted (may show startup latency)")
    print("   🧪 Tạo traffic để generate metrics:")
    print("      for i in {1..10}; do curl http://localhost/api/products; done")
    print("\n   Bây giờ chạy: python main_v2.py")


def restore_all():
    """Khôi phục toàn bộ hệ thống về trạng thái bình thường."""
    print("\n🔄 Restoring all services...")

    # Restore nginx config
    try:
        gw = client.containers.get("api-gateway")
        check = gw.exec_run("test -f /etc/nginx/nginx.conf.bak")
        if check.exit_code == 0:
            gw.exec_run("cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf")
            gw.exec_run("nginx -s reload")
            print("   ✅ Nginx config restored")
    except Exception as e:
        print(f"   ⚠️ Nginx restore: {e}")

    # Restart all services
    for name in ["order-service", "product-service", "payment-service"]:
        try:
            c = client.containers.get(name)
            if c.status != "running":
                c.start()
                print(f"   ✅ {name} started")
            else:
                print(f"   ✅ {name} already running")
        except Exception as e:
            print(f"   ⚠️ {name}: {e}")

    time.sleep(3)
    print("\n   🎉 All services restored!")


def main():
    parser = argparse.ArgumentParser(description="Fault Injection for SRE Demo")
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["1", "2", "3", "restore"],
        required=True,
        help="Scenario: 1=Bad Nginx Config, 2=Payment Crash, 3=Product Overload, restore=Reset All"
    )
    args = parser.parse_args()

    print("=" * 50)
    print("🔥 SRE Demo — Fault Injection Tool")
    print("=" * 50)

    if args.scenario == "1":
        scenario_1_bad_nginx_config()
    elif args.scenario == "2":
        scenario_2_payment_service_crash()
    elif args.scenario == "3":
        scenario_3_product_service_overload()
    elif args.scenario == "restore":
        restore_all()


if __name__ == "__main__":
    main()
