from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: UUID
    org_id: Optional[UUID]
    actor_type: str
    actor_id: Optional[UUID]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[UUID]
    ip_address: Optional[str]
    changes: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
