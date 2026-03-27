from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class VerificationCreate(BaseModel):
    applicant_id: UUID
    workflow_id: UUID


class VerificationOut(BaseModel):
    id: UUID
    org_id: UUID
    applicant_id: UUID
    workflow_id: UUID
    workflow_version: int
    current_step_order: int
    status: str
    result: str
    result_details: dict[str, Any]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VerificationDetailOut(VerificationOut):
    steps: list["StepProgressOut"] = []
    workflow_name: Optional[str] = None
    applicant_name: Optional[str] = None


class StepProgressOut(BaseModel):
    id: UUID
    session_id: UUID
    workflow_step_id: UUID
    tier_profile_id: UUID
    tier_profile_name: Optional[str] = None
    step_order: int
    status: str
    checks_completed: dict[str, Any]
    attributes_collected: dict[str, Any]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmitAttributesRequest(BaseModel):
    attributes: dict[str, Any]


class ReviewRequest(BaseModel):
    decision: str
    reason: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, v: str) -> str:
        if v not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")
        return v


class VerificationListOut(BaseModel):
    id: UUID
    applicant_id: UUID
    workflow_id: UUID
    status: str
    result: str
    current_step_order: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
