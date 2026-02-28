"""Pydantic model schemas for SRE Agent - Structured Output."""
from pydantic import BaseModel, Field
from typing import List, Literal, Optional


class ServiceHealth(BaseModel):
    """Trạng thái sức khỏe của 1 service"""
    service_name: str = Field(..., description="Tên service (vd: order-service)")
    container_status: Literal["running", "stopped", "restarting", "unknown"] = Field(...)
    http_status: Optional[int] = Field(None, description="HTTP status code từ health endpoint")
    is_healthy: bool = Field(...)
    error_message: Optional[str] = Field(None)


class Symptom(BaseModel):
    """Triệu chứng phát hiện — output từ Triage Agent"""
    service_name: str = Field(..., description="Service bị ảnh hưởng")
    symptom_type: Literal[
        "high_error_rate",
        "high_latency",
        "service_down",
        "resource_exhaustion",
        "connectivity_error",
        "config_error"
    ] = Field(..., description="Loại triệu chứng")
    severity: Literal["low", "medium", "high", "critical"] = Field(...)
    evidence: str = Field(..., description="Dữ liệu chứng minh (metrics, logs, traces)")
    affected_endpoints: List[str] = Field(default_factory=list, description="Các endpoint bị ảnh hưởng")


class SymptomList(BaseModel):
    """Danh sách triệu chứng — structured output từ Triage Agent"""
    symptoms: List[Symptom] = Field(default_factory=list)
    overall_status: Literal["healthy", "degraded", "critical"] = Field(...)
    summary: str = Field(..., description="Tóm tắt tình trạng hệ thống")


class MitigationPlan(BaseModel):
    """Kế hoạch sửa lỗi — output từ Planner Agent"""
    root_cause: str = Field(..., description="Nguyên nhân gốc rễ")
    target_service: str = Field(..., description="Service cần sửa")
    action_type: Literal[
        "restart_container",
        "update_config",
        "rollback_config",
        "scale_service"
    ] = Field(..., description="Loại hành động")
    config_content: Optional[str] = Field(None, description="Nội dung config mới (nếu update_config)")
    reasoning: str = Field(..., description="Giải thích tại sao chọn action này")
    estimated_impact: str = Field(..., description="Dự đoán tác động")


class MitigationResult(BaseModel):
    """Kết quả thực thi mitigation"""
    success: bool = Field(...)
    action_taken: str = Field(...)
    message: str = Field(...)
    target_service: str = Field(...)


class ValidationResult(BaseModel):
    """Kết quả validation sau mitigation"""
    is_healthy: bool = Field(...)
    services_checked: List[ServiceHealth] = Field(default_factory=list)
    metrics_improved: bool = Field(...)
    details: str = Field(...)


class HealthReport(BaseModel):
    """Báo cáo sức khoẻ tổng hợp cuối cùng"""
    overall_status: Literal["healthy", "degraded", "critical"] = Field(...)
    services: List[ServiceHealth] = Field(default_factory=list)
    symptoms_found: List[Symptom] = Field(default_factory=list)
    actions_taken: List[str] = Field(default_factory=list)
    resolution: str = Field(...)
