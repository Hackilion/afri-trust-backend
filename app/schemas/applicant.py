from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class ApplicantCreate(BaseModel):
    external_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    metadata: dict[str, Any] = {}


class ApplicantUpdate(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ApplicantOut(BaseModel):
    id: UUID
    org_id: UUID
    external_id: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    full_name: Optional[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplicantListOut(BaseModel):
    id: UUID
    external_id: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    full_name: Optional[str]
    verification_status: Optional[str] = None
    tier_reached: Optional[str] = None
    last_verified_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
