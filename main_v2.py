"""
Main entry point — Chạy SRE Agent workflow & stream events tới Dashboard.
"""
import os
import json
import time
import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from graph import build_sre_graph

load_dotenv()

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8888")


def emit_to_dashboard(event: dict):
    """Gửi event tới dashboard qua REST API."""
    try:
        requests.post(
            f"{DASHBOARD_URL}/api/agent-log",
            json=event,
            timeout=2,
        )
    except Exception:
        pass  # Dashboard có thể chưa chạy


def run_sre_workflow():
    """Chạy toàn bộ SRE workflow."""
    print("=" * 60)
    print("🤖 SRE Multi-Agent System — STRATUS Demo")
    print("=" * 60)

    # Init LLM
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
    )

    # Build graph
    graph = build_sre_graph(llm)

    # Initial state
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

    emit_to_dashboard({
        "agent": "System",
        "message": "🚀 SRE Agent Workflow bắt đầu...",
        "level": "info",
    })

    # Stream graph execution
    prev_events_count = 0
    for step in graph.stream(initial_state, stream_mode="updates"):
        for node_name, node_output in step.items():
            # Emit workflow events mới tới dashboard
            events = node_output.get("workflow_events", [])
            new_events = events[prev_events_count:] if isinstance(events, list) else []
            for ev in new_events:
                emit_to_dashboard({
                    "agent": ev.get("agent", node_name),
                    "message": ev.get("action", ""),
                    "level": "info",
                    "phase": ev.get("phase", ""),
                    "type": ev.get("type", "action"),
                })
                time.sleep(0.5)  # Delay cho visual effect
            prev_events_count = len(events) if isinstance(events, list) else 0

            print(f"\n📍 Node '{node_name}' completed.")

    emit_to_dashboard({
        "agent": "System",
        "message": "✅ SRE Agent Workflow hoàn tất!",
        "level": "info",
    })

    print("\n" + "=" * 60)
    print("✅ Workflow hoàn tất!")
    print("=" * 60)


if __name__ == "__main__":
    run_sre_workflow()


# """
# SRE Agent Demo — Entry point.
# Hệ thống Multi-Agent tự động phát hiện và sửa lỗi microservices.
# Lấy cảm hứng từ paper: STRATUS - A Multi-agent System for Autonomous Reliability Engineering.
# """
# import os
# import sys
# import argparse
# from dotenv import load_dotenv

# load_dotenv()

# # Thêm project root vào path
# sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# from langchain_openai import ChatOpenAI
# from graph import build_sre_graph


# def print_banner():
#     print("""
# ╔══════════════════════════════════════════════════════════════╗
# ║          🤖 SRE Multi-Agent System (STRATUS-inspired)        ║
# ║          Autonomous Reliability Engineering Demo             ║
# ╠══════════════════════════════════════════════════════════════╣
# ║  Agents:                                                     ║
# ║    🔍 Triage Agent    — Hybrid detection (Metrics + LLM)     ║
# ║    📋 Planner Agent   — Root cause analysis & planning       ║
# ║    🔧 Mitigation Agent — Execute fix                         ║
# ║    ⏪ Undo Agent      — TNR (Transactional No-Regression)    ║
# ║                                                              ║
# ║  Services:                                                   ║
# ║    📦 Order Service   — Quản lý đơn hàng (orchestrator)      ║
# ║    🏷️  Product Service — Quản lý sản phẩm & tồn kho          ║
# ║    💳 Payment Service — Xử lý thanh toán                     ║
# ║    🚪 API Gateway     — Nginx reverse proxy                  ║
# ║                                                              ║
# ║  Observability:                                              ║
# ║    📊 Prometheus (9090) | 🔍 Jaeger (16686) | 📈 cAdvisor    ║
# ╚══════════════════════════════════════════════════════════════╝
#     """)


# def main():
#     parser = argparse.ArgumentParser(description="SRE Multi-Agent Demo")
#     parser.add_argument(
#         "--model", default="gpt-4o-mini", help="OpenAI model name (default: gpt-4o-mini)"
#     )
#     parser.add_argument(
#         "--max-retries", type=int, default=3, help="Max retry attempts for TNR (default: 3)"
#     )
#     args = parser.parse_args()

#     print_banner()

#     # Init LLM
#     api_key = os.getenv("OPENAI_API_KEY")
#     if not api_key:
#         print("❌ OPENAI_API_KEY not found in .env!")
#         sys.exit(1)

#     llm = ChatOpenAI(model_name=args.model, temperature=0)
#     print(f"🤖 LLM: {args.model}")
#     print(f"🔄 Max retries (TNR): {args.max_retries}\n")

#     # Build graph
#     app = build_sre_graph(llm)

#     # Initial state
#     initial_state = {
#         "services_health": [],
#         "container_logs": "",
#         "metrics_data": "",
#         "tracing_data": "",
#         "symptoms": [],
#         "triage_summary": "",
#         "mitigation_plan": None,
#         "mitigation_result": None,
#         "attempt_count": 0,
#         "max_retries": args.max_retries,
#         "pre_fix_health": "",
#         "overall_status": "unknown",
#         "resolution": "",
#         "actions_taken": [],
#     }

#     print("=" * 60)
#     print("🚀 Bắt đầu SRE Workflow...")
#     print("=" * 60)

#     try:
#         final_state = None
#         for output in app.stream(initial_state):
#             for key, value in output.items():
#                 if isinstance(value, dict):
#                     final_state = {**initial_state, **(final_state or {}), **value}

#         print("\n" + "=" * 60)
#         print("📊 KẾT QUẢ WORKFLOW")
#         print("=" * 60)

#         if final_state:
#             status = final_state.get("overall_status", "unknown")
#             emoji = "✅" if status == "healthy" else "⚠️" if status == "degraded" else "❌"
#             print(f"   {emoji} Overall Status: {status.upper()}")
#             print(f"   📝 Triage Summary: {final_state.get('triage_summary', 'N/A')}")
#             print(f"   🔄 Attempts: {final_state.get('attempt_count', 0)}")

#             actions = final_state.get("actions_taken", [])
#             if actions:
#                 print(f"   📋 Actions taken:")
#                 for a in actions:
#                     print(f"      • {a}")

#             plan = final_state.get("mitigation_plan")
#             if plan:
#                 print(f"   🎯 Root Cause: {plan.root_cause if hasattr(plan, 'root_cause') else plan.get('root_cause', 'N/A')}")

#     except KeyboardInterrupt:
#         print("\n\n⚠️ Workflow interrupted by user.")
#     except Exception as e:
#         print(f"\n❌ Error during workflow: {str(e)}")
#         import traceback
#         traceback.print_exc()

#     print("\n" + "=" * 60)
#     print("🏁 Workflow execution completed.")
#     print("=" * 60)


# if __name__ == "__main__":
#     main()
