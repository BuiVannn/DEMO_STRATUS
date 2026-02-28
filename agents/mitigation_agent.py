"""
Mitigation Agent - Thực thi MitigationPlan.
Hỗ trợ: restart_container, update_config, rollback_config.
"""
from models.states import SystemState
from tools.docker_tools import restart_container, apply_nginx_config, rollback_nginx_config
from prompts.mitigation_prompts import MITIGATION_SYSTEM_PROMPT, MITIGATION_HUMAN_PROMPT
from langchain_core.messages import HumanMessage, SystemMessage


def get_clean_text(llm_response):
    """Xử lý response từ LLM (string hoặc list blocks)."""
    content = llm_response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(text_parts)
    return str(content)


def mitigation_agent(state: SystemState, llm) -> dict:
    """Thực thi kế hoạch mitigation."""
    print("\n" + "="*60)
    print("🔧 [Mitigation Agent] Thực thi kế hoạch sửa lỗi...")
    print("="*60)

    plan = state.get("mitigation_plan")
    if not plan:
        print("   ⚠️ Không có mitigation plan")
        return {
            "mitigation_result": {"success": False, "action_taken": "none", "message": "No plan provided", "target_service": ""},
            "actions_taken": state.get("actions_taken", []) + ["No mitigation plan to execute"]
        }

    action = plan.action_type
    target = plan.target_service
    actions_log = state.get("actions_taken", [])

    print(f"   🎯 Target: {target}")
    print(f"   🔧 Action: {action}")

    result_msg = ""
    success = False

    if action == "restart_container":
        print(f"   ▶️ Restarting container '{target}'...")
        result_msg = restart_container.invoke({"service_name": target})
        success = "successfully" in result_msg.lower() or "restarted" in result_msg.lower()
        actions_log.append(f"Restart container: {target} → {'OK' if success else 'FAILED'}")

    elif action == "update_config":
        if plan.config_content:
            config = plan.config_content
        else:
            # Gọi LLM sinh config Nginx
            print("   🤖 Gọi LLM sinh config Nginx...")
            ai_msg = llm.invoke([
                SystemMessage(content=MITIGATION_SYSTEM_PROMPT),
                HumanMessage(content=MITIGATION_HUMAN_PROMPT.format(error_description=plan.root_cause)),
            ])
            config = get_clean_text(ai_msg).strip()
            config = config.replace("```nginx", "").replace("```", "").strip()

        print(f"   📄 Applying config ({len(config)} chars)...")
        result_msg = apply_nginx_config.invoke({"config_content": config})
        success = "successfully" in result_msg.lower()
        actions_log.append(f"Update Nginx config → {'OK' if success else 'FAILED'}")

    elif action == "rollback_config":
        print(f"   ⏪ Rolling back config...")
        result_msg = rollback_nginx_config.invoke({})
        success = "completed" in result_msg.lower() or "rollback" in result_msg.lower()
        actions_log.append(f"Rollback Nginx config → {'OK' if success else 'FAILED'}")

    else:
        result_msg = f"Unknown action type: {action}"
        actions_log.append(f"Unknown action: {action}")

    status = "✅ SUCCESS" if success else "❌ FAILED"
    print(f"\n   {status}: {result_msg}")

    return {
        "mitigation_result": {
            "success": success,
            "action_taken": action,
            "message": result_msg,
            "target_service": target,
        },
        "actions_taken": actions_log,
    }
