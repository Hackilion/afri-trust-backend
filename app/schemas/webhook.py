from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class WebhookCreate(BaseModel):
    url: str
    event_types: list[str]


class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    event_types: Optional[list[str]] = None
    is_active: Optional[bool] = None


class WebhookOut(BaseModel):
    id: UUID
    org_id: UUID
    url: str
    event_types: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookCreateResponse(BaseModel):
    id: UUID
    url: str
    event_types: list[str]
    signing_secret: str
    created_at: datetime


class WebhookDeliveryOut(BaseModel):
    id: UUID
    event_type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    last_response_code: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}
