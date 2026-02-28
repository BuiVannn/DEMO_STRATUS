"""
Planner Agent - Phân tích symptoms và lên kế hoạch mitigation.
Dùng LLM structured output để tạo MitigationPlan.
"""
from models.states import SystemState
from models.schemas import MitigationPlan
from tools.docker_tools import read_service_logs
from prompts.planner_prompts import PLANNER_SYSTEM_PROMPT, PLANNER_HUMAN_PROMPT
from langchain_core.prompts import ChatPromptTemplate


def planner_agent(state: SystemState, llm) -> dict:
    """Phân tích symptoms → tạo MitigationPlan."""
    print("\n" + "="*60)
    print("📋 [Planner Agent] Lên kế hoạch khắc phục...")
    print("="*60)

    symptoms = state.get("symptoms", [])
    if not symptoms:
        print("   ✅ Không có symptoms → không cần mitigation")
        return {"mitigation_plan": None}

    # Format symptoms cho prompt
    symptoms_info = ""
    for i, s in enumerate(symptoms, 1):
        symptoms_info += f"""
## Symptom {i}
- **Service**: {s.service_name}
- **Type**: {s.symptom_type}
- **Severity**: {s.severity}
- **Evidence**: {s.evidence}
- **Affected Endpoints**: {', '.join(s.affected_endpoints) if s.affected_endpoints else 'N/A'}
"""

    # Đọc logs của service bị ảnh hưởng
    affected_services = set(s.service_name for s in symptoms)
    relevant_logs = ""
    for svc in affected_services:
        logs = read_service_logs.invoke({"service_name": svc, "tail": 20})
        relevant_logs += f"\n--- {svc} ---\n{logs}\n"

    # Gọi LLM với structured output
    prompt = ChatPromptTemplate.from_messages([
        ("system", PLANNER_SYSTEM_PROMPT),
        ("human", PLANNER_HUMAN_PROMPT),
    ])

    llm_structured = llm.with_structured_output(MitigationPlan)
    chain = prompt | llm_structured

    plan = chain.invoke({
        "symptoms_info": symptoms_info,
        "relevant_logs": relevant_logs,
    })

    print(f"\n   🎯 Root Cause: {plan.root_cause}")
    print(f"   🎯 Target: {plan.target_service}")
    print(f"   🔧 Action: {plan.action_type}")
    print(f"   💭 Reasoning: {plan.reasoning}")
    print(f"   ⚡ Impact: {plan.estimated_impact}")
    if plan.config_content:
        print(f"   📄 Config ({len(plan.config_content)} chars): {plan.config_content[:80]}...")

    return {"mitigation_plan": plan}
