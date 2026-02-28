"""
Multi-Agent SRE Workflow — STRATUS-inspired.
Kết hợp các agent đã có: triage → planner → mitigation → undo (validation).
Stream events cho dashboard qua callback.
"""
import time
from typing import Literal, Callable, Optional
from langgraph.graph import START, END, StateGraph

from models.states import SystemState
from agents.triage_agent import triage_agent
from agents.planner_agent import planner_agent
from agents.mitigation_agent import mitigation_agent
from agents.undo_agent import validation_oracle, undo_agent

# Global callback — dashboard sẽ set function này
_event_callback: Optional[Callable] = None


def set_event_callback(cb: Callable):
    """Dashboard gọi hàm này để register callback nhận events."""
    global _event_callback
    _event_callback = cb


def emit_event(event: dict):
    """Emit event tới dashboard (nếu có callback) + print ra terminal."""
    event.setdefault("timestamp", time.strftime("%H:%M:%S"))

    # Print to terminal
    phase = event.get("phase", "")
    agent = event.get("agent", "")
    action = event.get("action", "")
    print(f"   📡 [{phase}] {agent}: {action}")

    # Send to dashboard
    if _event_callback:
        try:
            _event_callback(event)
        except Exception as e:
            print(f"   ⚠️ Callback error: {e}")

    time.sleep(0.5)  # Visual delay for dashboard


# === Wrapper nodes ===

def triage_node(state: SystemState, llm) -> dict:
    """Node 1: Triage — thu thập telemetry + LLM phân tích symptoms."""
    emit_event({
        "phase": "triage",
        "agent": "TriageAgent",
        "action": "🔍 Bắt đầu thu thập telemetry data (Health Check, Prometheus, Jaeger, Logs)...",
        "type": "action",
    })

    result = triage_agent(state, llm)

    # Emit chi tiết telemetry — health check
    health = result.get("pre_fix_health", "")
    if health:
        for line in str(health).split("\n"):
            if line.strip():
                is_ok = any(k in line.upper() for k in ["HEALTHY", "HTTP_200", "RUNNING"])
                emit_event({
                    "phase": "triage",
                    "agent": "TriageAgent",
                    "action": f"{'✅' if is_ok else '❌'} {line.strip()}",
                    "type": "telemetry",
                })

    # Emit metrics summary
    metrics = result.get("metrics_data", "")
    if metrics:
        for line in str(metrics).split("\n"):
            line = line.strip()
            if line and ("UP" in line or "DOWN" in line or "req/s" in line):
                emit_event({
                    "phase": "triage",
                    "agent": "TriageAgent",
                    "action": f"📊 {line}",
                    "type": "telemetry",
                })

    # Emit LLM diagnosis
    symptoms = result.get("symptoms", [])
    triage_summary = result.get("triage_summary", "")
    status = result.get("overall_status", "unknown")

    if triage_summary:
        emit_event({
            "phase": "triage",
            "agent": "TriageAgent",
            "action": f"🧠 LLM Diagnosis: {triage_summary}",
            "type": "reasoning",
        })

    if symptoms:
        for i, s in enumerate(symptoms, 1):
            svc = s.service_name if hasattr(s, 'service_name') else 'unknown'
            stype = s.symptom_type if hasattr(s, 'symptom_type') else 'unknown'
            severity = s.severity if hasattr(s, 'severity') else 'unknown'
            evidence = s.evidence if hasattr(s, 'evidence') else ''
            emit_event({
                "phase": "triage",
                "agent": "TriageAgent",
                "action": f"🔴 Symptom {i}: [{severity.upper()}] {svc} — {stype}\n   Evidence: {evidence[:150]}",
                "type": "conclusion",
            })
    else:
        emit_event({
            "phase": "triage",
            "agent": "TriageAgent",
            "action": f"🟢 Không phát hiện symptoms nghiêm trọng. Status: {status}",
            "type": "conclusion",
        })

    return result


def planner_node(state: SystemState, llm) -> dict:
    """Node 2: Planner — lên kế hoạch mitigation."""
    emit_event({
        "phase": "planner",
        "agent": "PlannerAgent",
        "action": "📋 Phân tích root cause & lên kế hoạch khắc phục...",
        "type": "action",
    })

    result = planner_agent(state, llm)

    plan = result.get("mitigation_plan")
    if plan:
        root_cause = plan.root_cause if hasattr(plan, 'root_cause') else plan.get('root_cause', 'N/A')
        reasoning = plan.reasoning if hasattr(plan, 'reasoning') else plan.get('reasoning', 'N/A')
        action_type = plan.action_type if hasattr(plan, 'action_type') else plan.get('action_type', 'N/A')
        target = plan.target_service if hasattr(plan, 'target_service') else plan.get('target_service', 'N/A')
        impact = plan.estimated_impact if hasattr(plan, 'estimated_impact') else plan.get('estimated_impact', 'N/A')

        emit_event({
            "phase": "planner",
            "agent": "PlannerAgent",
            "action": f"🎯 Root Cause: {root_cause}",
            "type": "reasoning",
        })
        emit_event({
            "phase": "planner",
            "agent": "PlannerAgent",
            "action": f"💭 Reasoning: {reasoning}",
            "type": "reasoning",
        })
        emit_event({
            "phase": "planner",
            "agent": "PlannerAgent",
            "action": f"🔧 Plan: {action_type} → {target}\n⚡ Impact: {impact}",
            "type": "conclusion",
        })
    return result


def mitigation_node(state: SystemState, llm) -> dict:
    """Node 3: Mitigation — thực thi sửa lỗi với A-Lock & TNR backup."""
    attempt = state.get("attempt_count", 0) + 1
    max_retries = state.get("max_retries", 3)

    # A-Lock
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"🔒 A-Lock ACQUIRED. Attempt {attempt}/{max_retries}",
        "type": "lock_acquired",
    })

    # TNR Backup
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": "💾 TNR: Tạo backup config (push vào undo stack)...",
        "type": "tnr_backup",
    })

    result = mitigation_agent(state, llm)

    mit_result = result.get("mitigation_result", {})
    success = mit_result.get("success", False)
    action = mit_result.get("action_taken", "unknown")
    message = mit_result.get("message", "")
    target = mit_result.get("target_service", "")

    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"⚡ Executing: {action} on '{target}'...",
        "type": "tnr_apply",
    })

    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"{'✅' if success else '❌'} Result: {message[:200]}",
        "type": "conclusion" if success else "tnr_rollback",
    })

    # Release A-Lock
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": "🔓 A-Lock RELEASED",
        "type": "lock_released",
    })

    return result


def verification_node(state: SystemState) -> dict:
    """Node 4: Validation Oracle — kiểm chứng đa nguồn."""
    emit_event({
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🧪 Bắt đầu kiểm chứng đa nguồn (3 Oracles)...",
        "type": "action",
    })

    emit_event({
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🔍 Oracle 1: System Health Check (Docker containers)...",
        "type": "oracle",
    })

    result = validation_oracle(state)
    is_healthy = result.get("overall_status") == "healthy"

    emit_event({
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🔍 Oracle 2: Gateway HTTP Test (GET /api/products)...",
        "type": "oracle",
    })

    emit_event({
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🔍 Oracle 3: Service Direct Health Check (port 5001, 5002, 5003)...",
        "type": "oracle",
    })

    if is_healthy:
        emit_event({
            "phase": "verification",
            "agent": "ValidationOracle",
            "action": "✅ All 3 Oracles PASSED — TNR COMMIT! Hệ thống HEALTHY!",
            "type": "tnr_commit",
        })
    else:
        emit_event({
            "phase": "verification",
            "agent": "ValidationOracle",
            "action": "❌ Oracle FAILED — TNR cần ROLLBACK! Hệ thống vẫn lỗi.",
            "type": "tnr_rollback",
        })

    return result


def undo_node(state: SystemState) -> dict:
    """Node 5: Undo Agent — Stack-based rollback."""
    attempt = state.get("attempt_count", 0)
    max_retries = state.get("max_retries", 3)

    emit_event({
        "phase": "undo",
        "agent": "UndoAgent",
        "action": f"⏪ TNR Rollback: Pop config từ undo stack (attempt {attempt}/{max_retries})...",
        "type": "tnr_rollback",
    })

    result = undo_agent(state)

    new_attempt = result.get("attempt_count", attempt)
    if new_attempt < max_retries:
        emit_event({
            "phase": "undo",
            "agent": "UndoAgent",
            "action": f"🔄 Retry {new_attempt}/{max_retries} — Quay lại Mitigation",
            "type": "action",
        })
    else:
        emit_event({
            "phase": "undo",
            "agent": "UndoAgent",
            "action": f"🚫 Circuit Breaker OPEN: Đã thử {new_attempt}/{max_retries}. DỪNG LẠI — Escalate to human!",
            "type": "circuit_breaker",
        })

    return result


# === Routing functions ===

def should_mitigate(state: SystemState) -> Literal["planner", "end"]:
    """Triage → Planner only nếu có symptoms."""
    symptoms = state.get("symptoms", [])
    if symptoms:
        return "planner"
    return "end"


def should_retry_or_end(state: SystemState) -> Literal["undo", "end"]:
    """Verification → Undo nếu vẫn lỗi, End nếu healthy."""
    status = state.get("overall_status", "")
    if status == "healthy":
        return "end"
    return "undo"


def can_retry(state: SystemState) -> Literal["mitigation", "end"]:
    """Undo → retry Mitigation nếu chưa vượt max attempts."""
    attempt = state.get("attempt_count", 0)
    max_retries = state.get("max_retries", 3)
    if attempt < max_retries:
        return "mitigation"
    return "end"


def build_sre_graph(llm):
    """Build LangGraph workflow."""

    builder = StateGraph(SystemState)

    builder.add_node("triage", lambda state: triage_node(state, llm))
    builder.add_node("planner", lambda state: planner_node(state, llm))
    builder.add_node("mitigation", lambda state: mitigation_node(state, llm))
    builder.add_node("verification", verification_node)
    builder.add_node("undo", undo_node)

    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", should_mitigate, {
        "planner": "planner",
        "end": END,
    })
    builder.add_edge("planner", "mitigation")
    builder.add_edge("mitigation", "verification")
    builder.add_conditional_edges("verification", should_retry_or_end, {
        "undo": "undo",
        "end": END,
    })
    builder.add_conditional_edges("undo", can_retry, {
        "mitigation": "mitigation",
        "end": END,
    })

    return builder.compile()



'''
"""
Multi-Agent SRE Workflow — STRATUS-inspired.
Kết hợp các agent đã có: triage → planner → mitigation → undo (validation).
Stream events cho dashboard qua callback.
"""
import time
from typing import Literal, Callable, Optional
from langgraph.graph import START, END, StateGraph

from models.states import SystemState
from agents.triage_agent import triage_agent
from agents.planner_agent import planner_agent
from agents.mitigation_agent import mitigation_agent
from agents.undo_agent import validation_oracle, undo_agent

# Global callback — dashboard sẽ set function này
_event_callback: Optional[Callable] = None

def set_event_callback(cb: Callable):
    """Dashboard gọi hàm này để register callback nhận events."""
    global _event_callback
    _event_callback = cb

def emit_event(event: dict):
    """Emit event tới dashboard (nếu có callback) + print ra terminal."""
    event.setdefault("timestamp", time.strftime("%H:%M:%S"))
    
    # Print to terminal
    phase = event.get("phase", "")
    agent = event.get("agent", "")
    action = event.get("action", "")
    print(f"   [{phase}] {agent}: {action}")
    
    # Send to dashboard
    if _event_callback:
        try:
            _event_callback(event)
        except Exception:
            pass
    
    time.sleep(0.6)  # Visual delay for dashboard


# === Wrapper nodes ===

def triage_node(state: SystemState, llm) -> dict:
    """Node 1: Triage — thu thập telemetry + LLM phân tích symptoms."""
    emit_event({
        "phase": "triage",
        "agent": "TriageAgent",
        "action": "🔍 Bắt đầu thu thập telemetry data (Health Check, Prometheus, Jaeger, Logs)...",
        "type": "action",
    })
    
    result = triage_agent(state, llm)
    
    # Emit chi tiết telemetry
    health = result.get("pre_fix_health", "")
    if health:
        # Parse health lines
        for line in str(health).split("\n"):
            if line.strip():
                is_ok = any(k in line.upper() for k in ["HEALTHY", "HTTP_200", "RUNNING"])
                emit_event({
                    "phase": "triage",
                    "agent": "TriageAgent",
                    "action": f"{'✅' if is_ok else '❌'} {line.strip()}",
                    "type": "telemetry",
                })
    
    # Emit metrics summary
    metrics = result.get("metrics_data", "")
    if metrics:
        # Extract key lines
        for line in str(metrics).split("\n"):
            if "UP" in line or "DOWN" in line or "req/s" in line:
                emit_event({
                    "phase": "triage",
                    "agent": "TriageAgent",
                    "action": f"📊 {line.strip()}",
                    "type": "telemetry",
                })
    
    # Emit LLM diagnosis
    symptoms = result.get("symptoms", [])
    triage_summary = result.get("triage_summary", "")
    status = result.get("overall_status", "unknown")
    
    if triage_summary:
        emit_event({
            "phase": "triage",
            "agent": "TriageAgent",
            "action": f"🧠 LLM Diagnosis: {triage_summary}",
            "type": "reasoning",
        })
    
    if symptoms:
        for i, s in enumerate(symptoms, 1):
            svc = s.service_name if hasattr(s, 'service_name') else 'unknown'
            stype = s.symptom_type if hasattr(s, 'symptom_type') else 'unknown'
            severity = s.severity if hasattr(s, 'severity') else 'unknown'
            evidence = s.evidence if hasattr(s, 'evidence') else ''
            emit_event({
                "phase": "triage",
                "agent": "TriageAgent",
                "action": f"🔴 Symptom {i}: [{severity.upper()}] {svc} — {stype}\n   Evidence: {evidence[:120]}...",
                "type": "conclusion",
            })
    else:
        emit_event({
            "phase": "triage",
            "agent": "TriageAgent",
            "action": f"🟢 Không phát hiện symptoms. Status: {status}",
            "type": "conclusion",
        })
    
    return result


def planner_node(state: SystemState, llm) -> dict:
    """Node 2: Planner — lên kế hoạch mitigation."""
    emit_event({
        "phase": "planner",
        "agent": "PlannerAgent",
        "action": "📋 Phân tích root cause & lên kế hoạch khắc phục...",
        "type": "action",
    })
    
    result = planner_agent(state, llm)
    
    plan = result.get("mitigation_plan")
    if plan:
        emit_event({
            "phase": "planner",
            "agent": "PlannerAgent",
            "action": f"🎯 Root Cause: {plan.root_cause}",
            "type": "reasoning",
        })
        emit_event({
            "phase": "planner",
            "agent": "PlannerAgent",
            "action": f"💭 Reasoning: {plan.reasoning}",
            "type": "reasoning",
        })
        emit_event({
            "phase": "planner",
            "agent": "PlannerAgent",
            "action": f"🔧 Plan: {plan.action_type} → {plan.target_service} | Impact: {plan.estimated_impact}",
            "type": "conclusion",
        })
    return result


def mitigation_node(state: SystemState, llm) -> dict:
    """Node 3: Mitigation — thực thi sửa lỗi với A-Lock & TNR backup."""
    attempt = state.get("attempt_count", 0) + 1
    max_retries = state.get("max_retries", 3)
    
    # A-Lock
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"🔒 A-Lock ACQUIRED. Attempt {attempt}/{max_retries}",
        "type": "lock_acquired",
    })
    
    # TNR Backup
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": "💾 TNR: Tạo backup config (push vào undo stack)...",
        "type": "tnr_backup",
    })
    
    result = mitigation_agent(state, llm)
    
    mit_result = result.get("mitigation_result", {})
    success = mit_result.get("success", False)
    action = mit_result.get("action_taken", "unknown")
    message = mit_result.get("message", "")
    target = mit_result.get("target_service", "")
    
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"⚡ Executing: {action} on '{target}'...",
        "type": "tnr_apply",
    })
    
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"{'✅' if success else '❌'} Result: {message[:150]}",
        "type": "conclusion" if success else "tnr_rollback",
    })
    
    # Release A-Lock
    emit_event({
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": "🔓 A-Lock RELEASED",
        "type": "lock_released",
    })
    
    return result


def verification_node(state: SystemState) -> dict:
    """Node 4: Validation Oracle — kiểm chứng đa nguồn."""
    emit_event({
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🔍 Oracle 1: System Health Check...",
        "type": "oracle",
    })
    
    result = validation_oracle(state)
    is_healthy = result.get("overall_status") == "healthy"
    
    emit_event({
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🔍 Oracle 2: Gateway HTTP Test (GET /api/products)...",
        "type": "oracle",
    })
    
    emit_event({
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🔍 Oracle 3: Service Direct Health Check...",
        "type": "oracle",
    })
    
    if is_healthy:
        emit_event({
            "phase": "verification",
            "agent": "ValidationOracle",
            "action": "✅ All oracles PASSED — TNR COMMIT! Hệ thống HEALTHY!",
            "type": "tnr_commit",
        })
    else:
        emit_event({
            "phase": "verification",
            "agent": "ValidationOracle",
            "action": "❌ Oracle FAILED — TNR cần ROLLBACK! Hệ thống vẫn lỗi.",
            "type": "tnr_rollback",
        })
    
    return result


def undo_node(state: SystemState) -> dict:
    """Node 5: Undo Agent — Stack-based rollback."""
    attempt = state.get("attempt_count", 0)
    max_retries = state.get("max_retries", 3)
    
    emit_event({
        "phase": "undo",
        "agent": "UndoAgent",
        "action": f"⏪ TNR Rollback: Pop config từ undo stack (attempt {attempt}/{max_retries})...",
        "type": "tnr_rollback",
    })
    
    result = undo_agent(state)
    
    new_attempt = result.get("attempt_count", attempt)
    if new_attempt < max_retries:
        emit_event({
            "phase": "undo",
            "agent": "UndoAgent",
            "action": f"🔄 Retry {new_attempt}/{max_retries} — Quay lại Mitigation",
            "type": "action",
        })
    else:
        emit_event({
            "phase": "undo",
            "agent": "UndoAgent",
            "action": f"🚫 Circuit Breaker OPEN: Đã thử {new_attempt}/{max_retries}. DỪNG LẠI!",
            "type": "circuit_breaker",
        })
    
    return result


# === Routing functions ===

def should_mitigate(state: SystemState) -> Literal["planner", "end"]:
    """Triage → Planner only nếu có symptoms."""
    symptoms = state.get("symptoms", [])
    if symptoms:
        return "planner"
    return "end"


def should_retry_or_end(state: SystemState) -> Literal["undo", "end"]:
    """Verification → Undo nếu vẫn lỗi, End nếu healthy."""
    status = state.get("overall_status", "")
    if status == "healthy":
        return "end"
    return "undo"


def can_retry(state: SystemState) -> Literal["mitigation", "end"]:
    """Undo → retry Mitigation nếu chưa vượt max attempts."""
    attempt = state.get("attempt_count", 0)
    max_retries = state.get("max_retries", 3)
    if attempt < max_retries:
        return "mitigation"
    return "end"


def build_sre_graph(llm):
    """Build LangGraph workflow."""
    
    builder = StateGraph(SystemState)

    builder.add_node("triage", lambda state: triage_node(state, llm))
    builder.add_node("planner", lambda state: planner_node(state, llm))
    builder.add_node("mitigation", lambda state: mitigation_node(state, llm))
    builder.add_node("verification", verification_node)
    builder.add_node("undo", undo_node)

    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", should_mitigate, {
        "planner": "planner",
        "end": END,
    })
    builder.add_edge("planner", "mitigation")
    builder.add_edge("mitigation", "verification")
    builder.add_conditional_edges("verification", should_retry_or_end, {
        "undo": "undo",
        "end": END,
    })
    builder.add_conditional_edges("undo", can_retry, {
        "mitigation": "mitigation",
        "end": END,
    })

    return builder.compile()

'''


'''
"""
Multi-Agent SRE Workflow — STRATUS-inspired.
Kết hợp các agent đã có: triage → planner → mitigation → undo (validation).
Thêm streaming events cho dashboard.
"""
import time
from typing import Literal
from langgraph.graph import START, END, StateGraph

from models.states import SystemState
from agents.triage_agent import triage_agent
from agents.planner_agent import planner_agent
from agents.mitigation_agent import mitigation_agent
from agents.undo_agent import validation_oracle, undo_agent


# === Wrapper nodes — thêm event tracking cho dashboard ===

def triage_node(state: SystemState, llm) -> dict:
    """Node 1: Triage — thu thập telemetry + LLM phân tích symptoms."""
    state["current_phase"] = "triage"
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "triage",
        "agent": "TriageAgent",
        "action": "🔍 Bắt đầu thu thập telemetry & phân tích symptoms...",
        "type": "action",
    })
    result = triage_agent(state, llm)
    
    # Log kết quả
    symptoms = result.get("symptoms", [])
    status = result.get("overall_status", "unknown")
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "triage",
        "agent": "TriageAgent",
        "action": f"{'🔴' if symptoms else '🟢'} Phát hiện {len(symptoms)} symptoms. Status: {status}",
        "type": "conclusion",
    })
    return result


def planner_node(state: SystemState, llm) -> dict:
    """Node 2: Planner — lên kế hoạch mitigation."""
    state["current_phase"] = "planner"
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "planner",
        "agent": "PlannerAgent",
        "action": "📋 Phân tích root cause & lên kế hoạch khắc phục...",
        "type": "action",
    })
    result = planner_agent(state, llm)
    
    plan = result.get("mitigation_plan")
    if plan:
        state.setdefault("workflow_events", []).append({
            "timestamp": time.strftime("%H:%M:%S"),
            "phase": "planner",
            "agent": "PlannerAgent",
            "action": f"🎯 Root cause: {plan.root_cause} | Action: {plan.action_type} | Target: {plan.target_service}",
            "type": "conclusion",
        })
    return result


def mitigation_node(state: SystemState, llm) -> dict:
    """Node 3: Mitigation — thực thi sửa lỗi với A-Lock & TNR backup."""
    state["current_phase"] = "mitigation"
    attempt = state.get("attempt_count", 0) + 1
    max_retries = state.get("max_retries", 3)
    
    # A-Lock
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"🔒 A-Lock ACQUIRED. Attempt {attempt}/{max_retries}",
        "type": "lock_acquired",
    })
    
    # TNR Backup
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": "💾 TNR: Tạo backup config (push vào undo stack)...",
        "type": "tnr_backup",
    })
    
    result = mitigation_agent(state, llm)
    
    success = result.get("mitigation_result", {}).get("success", False)
    action = result.get("mitigation_result", {}).get("action_taken", "unknown")
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": f"{'✅' if success else '❌'} {action}: {'Thành công' if success else 'Thất bại'}",
        "type": "tnr_apply",
    })
    
    # Release A-Lock
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "mitigation",
        "agent": "MitigationAgent",
        "action": "🔓 A-Lock RELEASED",
        "type": "lock_released",
    })
    
    return result


def verification_node(state: SystemState) -> dict:
    """Node 4: Validation Oracle — kiểm chứng đa nguồn."""
    state["current_phase"] = "verification"
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": "🔍 Oracle 1: Kiểm tra System Health...",
        "type": "oracle",
    })
    
    result = validation_oracle(state)
    is_healthy = result.get("overall_status") == "healthy"
    
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "verification",
        "agent": "ValidationOracle",
        "action": f"{'✅ TNR COMMIT — Hệ thống HEALTHY!' if is_healthy else '❌ TNR cần ROLLBACK — Hệ thống vẫn lỗi'}",
        "type": "tnr_commit" if is_healthy else "tnr_rollback",
    })
    
    return result


def undo_node(state: SystemState) -> dict:
    """Node 5: Undo Agent — Stack-based rollback."""
    state["current_phase"] = "undo"
    state.setdefault("workflow_events", []).append({
        "timestamp": time.strftime("%H:%M:%S"),
        "phase": "undo",
        "agent": "UndoAgent",
        "action": "⏪ Stack-based Undo: Rollback config từ backup...",
        "type": "tnr_rollback",
    })
    
    result = undo_agent(state)
    return result


# === Routing functions ===

def should_mitigate(state: SystemState) -> Literal["planner", "end"]:
    """Triage → Planner only nếu có symptoms."""
    symptoms = state.get("symptoms", [])
    if symptoms:
        return "planner"
    return "end"


def should_retry_or_end(state: SystemState) -> Literal["undo", "end"]:
    """Verification → Undo nếu vẫn lỗi, End nếu healthy."""
    status = state.get("overall_status", "")
    if status == "healthy":
        return "end"
    return "undo"


def can_retry(state: SystemState) -> Literal["mitigation", "end"]:
    """Undo → retry Mitigation nếu chưa vượt max attempts (Bounded Risk Window)."""
    attempt = state.get("attempt_count", 0)
    max_retries = state.get("max_retries", 3)
    
    if attempt < max_retries:
        state.setdefault("workflow_events", []).append({
            "timestamp": time.strftime("%H:%M:%S"),
            "phase": "undo",
            "agent": "UndoAgent",
            "action": f"🔄 Retry {attempt}/{max_retries} — Quay lại Mitigation",
            "type": "action",
        })
        return "mitigation"
    else:
        state.setdefault("workflow_events", []).append({
            "timestamp": time.strftime("%H:%M:%S"),
            "phase": "undo",
            "agent": "UndoAgent",
            "action": f"🚫 Circuit Breaker OPEN: Đã thử {attempt}/{max_retries}. Dừng lại.",
            "type": "circuit_breaker",
        })
        return "end"


def build_sre_graph(llm):
    """Build LangGraph workflow."""
    
    builder = StateGraph(SystemState)

    # Add nodes — dùng lambda để inject llm
    builder.add_node("triage", lambda state: triage_node(state, llm))
    builder.add_node("planner", lambda state: planner_node(state, llm))
    builder.add_node("mitigation", lambda state: mitigation_node(state, llm))
    builder.add_node("verification", verification_node)
    builder.add_node("undo", undo_node)

    # Edges
    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", should_mitigate, {
        "planner": "planner",
        "end": END,
    })
    builder.add_edge("planner", "mitigation")
    builder.add_edge("mitigation", "verification")
    builder.add_conditional_edges("verification", should_retry_or_end, {
        "undo": "undo",
        "end": END,
    })
    builder.add_conditional_edges("undo", can_retry, {
        "mitigation": "mitigation",
        "end": END,
    })

    return builder.compile()

'''

