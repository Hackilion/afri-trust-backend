from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class ConsentGrantRequest(BaseModel):
    granted_attributes: list[str]
    expires_in_days: int = 30


class ConsentGrantOut(BaseModel):
    id: UUID
    applicant_id: UUID
    session_id: UUID
    granted_attributes: list[str]
    expires_at: datetime
    revoked_at: Optional[datetime]
    verification_token: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IdentityDataOut(BaseModel):
    applicant_id: UUID
    attributes: dict[str, Any]
