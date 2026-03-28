from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AssistantSessionCreate(BaseModel):
    preview: str = ""


class AssistantSessionPatch(BaseModel):
    preview: Optional[str] = None
    state: Optional[dict[str, Any]] = None


class AssistantSessionOut(BaseModel):
    id: UUID
    preview: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssistantSessionDetailOut(BaseModel):
    id: UUID
    preview: str
    state: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime

    model_config = {"from_attributes": True}
