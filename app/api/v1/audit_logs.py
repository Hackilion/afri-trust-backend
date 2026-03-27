import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role
from app.db.session import get_db
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogOut
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("", response_model=PaginatedResponse[AuditLogOut])
async def list_audit_logs(
    actor_id: Optional[UUID] = Query(None),
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[UUID] = Query(None),
    action: Optional[str] = Query(None),
    after: Optional[datetime] = Query(None),
    before: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    base = select(AuditLog).where(AuditLog.org_id == auth.org_id)

    if actor_id:
        base = base.where(AuditLog.actor_id == actor_id)
    if resource_type:
        base = base.where(AuditLog.resource_type == resource_type)
    if resource_id:
        base = base.where(AuditLog.resource_id == resource_id)
    if action:
        base = base.where(AuditLog.action == action)
    if after:
        base = base.where(AuditLog.created_at >= after)
    if before:
        base = base.where(AuditLog.created_at <= before)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0

    base = base.order_by(AuditLog.created_at.desc())
    base = base.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(base)
    logs = result.scalars().all()

    return PaginatedResponse(
        items=logs,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )
