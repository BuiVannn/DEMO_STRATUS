"""TypedDict state definitions for LangGraph agents."""
from typing import TypedDict, List, Optional
from models.schemas import Symptom, MitigationPlan, MitigationResult, ServiceHealth


class SystemState(TypedDict):
    """Parent state cho toàn bộ SRE workflow"""
    # --- Triage Agent ---
    services_health: List[ServiceHealth]
    container_logs: str
    metrics_data: str
    tracing_data: str
    symptoms: List[Symptom]
    triage_summary: str

    # --- Planner Agent ---
    mitigation_plan: Optional[MitigationPlan]

    # --- Mitigation Agent ---
    mitigation_result: Optional[MitigationResult]

    # --- Undo / TNR ---
    attempt_count: int
    max_retries: int
    pre_fix_health: str  # snapshot before fix

    # --- Final ---
    overall_status: str  # healthy | degraded | critical
    resolution: str
    actions_taken: List[str]
