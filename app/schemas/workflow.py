from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class WorkflowStepCreate(BaseModel):
    tier_profile_id: UUID
    step_order: int
    is_optional: bool = False

    @field_validator("step_order")
    @classmethod
    def step_order_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("step_order must be >= 1")
        return v


class WorkflowStepUpdate(BaseModel):
    step_order: Optional[int] = None
    is_optional: Optional[bool] = None


class WorkflowStepOut(BaseModel):
    id: UUID
    workflow_id: UUID
    tier_profile_id: UUID
    tier_profile_name: Optional[str] = None
    step_order: int
    is_optional: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowOut(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    description: Optional[str]
    status: str
    version: int
    published_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepOut] = []

    model_config = {"from_attributes": True}


class WorkflowListOut(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    description: Optional[str]
    status: str
    version: int
    step_count: int = 0
    published_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
