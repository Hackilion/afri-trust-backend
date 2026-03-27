from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class KycSummaryOut(BaseModel):
    applicant_id: UUID
    external_id: Optional[str]
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    metadata: dict[str, Any]
    sessions: list["KycSessionSummary"]
    active_consents: int


class KycSessionSummary(BaseModel):
    session_id: UUID
    workflow_name: Optional[str]
    status: str
    result: str
    current_step_order: int
    total_steps: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    steps: list["KycStepDetail"]


class KycStepDetail(BaseModel):
    step_order: int
    tier_profile_name: Optional[str]
    status: str
    checks_completed: dict[str, Any]
    attributes_collected: dict[str, Any]
    documents: list["KycDocumentDetail"]
    biometrics: list["KycBiometricDetail"]


class KycDocumentDetail(BaseModel):
    id: UUID
    document_type: str
    original_filename: Optional[str]
    confidence_score: Optional[float]
    document_classification: Optional[str]
    fraud_signals: dict[str, Any] = {}
    created_at: datetime


class KycBiometricDetail(BaseModel):
    id: UUID
    check_type: str
    passed: bool
    score: Optional[float]
    created_at: datetime


class DashboardStatsOut(BaseModel):
    total_applicants: int
    verifications_today: int
    approval_rate: Optional[float]
    avg_time_to_verify_seconds: Optional[float]
    by_status: dict[str, int]
    by_tier: dict[str, dict[str, int]]
    by_workflow: dict[str, dict[str, int]]
