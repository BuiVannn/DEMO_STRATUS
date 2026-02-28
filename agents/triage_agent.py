"""
Triage Agent - Hybrid: Deterministic metrics check + LLM diagnosis.
Lấy cảm hứng từ STRATUS paper: kết hợp heuristic và LLM để giảm hallucination.
"""
import json
from models.states import SystemState
from models.schemas import SymptomList
from tools.docker_tools import check_all_services_health, read_service_logs
from tools.metrics_tools import get_all_services_metrics, get_service_error_rate, get_service_latency
from tools.tracing_tools import get_recent_traces, get_error_traces
from prompts.triage_prompts import TRIAGE_SYSTEM_PROMPT, TRIAGE_HUMAN_PROMPT
from langchain_core.prompts import ChatPromptTemplate


def gather_telemetry(state: SystemState, llm) -> dict:
    """
    Bước 1 (Deterministic): Thu thập dữ liệu monitoring từ tất cả sources.
    Không dùng LLM — chỉ gọi tools trực tiếp.
    """
    print("\n" + "="*60)
    print("🔍 [Triage Agent] Bước 1: Thu thập telemetry data...")
    print("="*60)

    # 1. Health check tất cả services
    print("   📋 Kiểm tra health check...")
    health_status = check_all_services_health.invoke({})
    print(f"   {health_status}")

    # 2. Prometheus metrics
    print("   📊 Thu thập Prometheus metrics...")
    metrics_data = get_all_services_metrics.invoke({})

    # Error rate per service
    for svc in ["order", "product", "payment"]:
        err = get_service_error_rate.invoke({"service_name": svc})
        metrics_data += f"\n{err}"

    print(f"   {metrics_data[:200]}...")

    # 3. Distributed traces từ Jaeger
    print("   🔍 Truy vấn Jaeger traces...")
    tracing_data = ""
    for svc in ["order-service", "product-service", "payment-service"]:
        traces = get_recent_traces.invoke({"service_name": svc, "limit": 3})
        error_traces = get_error_traces.invoke({"service_name": svc, "limit": 3})
        tracing_data += f"\n--- {svc} ---\n{traces}\n{error_traces}\n"

    # 4. Container logs
    print("   📝 Đọc container logs...")
    container_logs = ""
    for svc in ["order-service", "product-service", "payment-service", "api-gateway"]:
        logs = read_service_logs.invoke({"service_name": svc, "tail": 15})
        container_logs += f"\n--- {svc} logs ---\n{logs}\n"

    return {
        "services_health": [],  # Will be populated by LLM analysis
        "container_logs": container_logs,
        "metrics_data": metrics_data,
        "tracing_data": tracing_data,
        "pre_fix_health": health_status,  # Snapshot cho TNR comparison
    }


def diagnose_with_llm(state: SystemState, llm) -> dict:
    """
    Bước 2 (LLM): Phân tích telemetry data và xác định symptoms.
    Dùng structured output (Pydantic) để đảm bảo format chuẩn.
    """
    print("\n" + "="*60)
    print("🧠 [Triage Agent] Bước 2: LLM phân tích symptoms...")
    print("="*60)

    prompt = ChatPromptTemplate.from_messages([
        ("system", TRIAGE_SYSTEM_PROMPT),
        ("human", TRIAGE_HUMAN_PROMPT),
    ])

    # Structured output: LLM phải trả về đúng format SymptomList
    llm_structured = llm.with_structured_output(SymptomList)
    chain = prompt | llm_structured

    result = chain.invoke({
        "health_status": state.get("pre_fix_health", ""),
        "container_logs": state.get("container_logs", ""),
        "metrics_data": state.get("metrics_data", ""),
        "tracing_data": state.get("tracing_data", ""),
    })

    # Log kết quả
    print(f"\n   📊 Overall Status: {result.overall_status}")
    print(f"   📝 Summary: {result.summary}")
    if result.symptoms:
        for i, s in enumerate(result.symptoms, 1):
            print(f"   🔴 Symptom {i}: [{s.severity.upper()}] {s.service_name} — {s.symptom_type}")
            print(f"      Evidence: {s.evidence[:100]}...")
    else:
        print("   ✅ Không phát hiện triệu chứng bất thường!")

    return {
        "symptoms": result.symptoms,
        "triage_summary": result.summary,
        "overall_status": result.overall_status,
    }


def triage_agent(state: SystemState, llm) -> dict:
    """Entry point cho Triage Agent — kết hợp cả 2 bước."""
    # Bước 1: Gather telemetry (deterministic)
    telemetry = gather_telemetry(state, llm)
    state.update(telemetry)

    # Bước 2: Diagnose (LLM)
    diagnosis = diagnose_with_llm(state, llm)
    state.update(diagnosis)

    return {**telemetry, **diagnosis}
