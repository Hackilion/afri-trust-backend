from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] = []


class ApiKeyCreateResponse(BaseModel):
    id: UUID
    name: str
    api_key: str
    key_prefix: str
    scopes: list[str]
    created_at: datetime


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
