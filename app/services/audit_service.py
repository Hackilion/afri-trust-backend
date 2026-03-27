from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def log_event(
    db: AsyncSession,
    *,
    org_id: Optional[UUID],
    actor_type: str,
    actor_id: Optional[UUID],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
    changes: Optional[dict[str, Any]] = None,
) -> AuditLog:
    entry = AuditLog(
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        changes=changes or {},
    )
    db.add(entry)
    await db.flush()
    return entry
