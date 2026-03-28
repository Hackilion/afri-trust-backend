"""Unique 6-digit workflow codes per organisation for integrator-friendly references."""

import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.workflow import Workflow


async def assign_unique_short_code(db: AsyncSession, org_id: UUID, wf: Workflow) -> None:
    """Set `wf.short_code` to a random 6-digit string unique within the org."""
    for _ in range(100):
        code = f"{secrets.randbelow(1_000_000):06d}"
        stmt = select(Workflow.id).where(
            Workflow.org_id == org_id,
            Workflow.short_code == code,
        )
        res = await db.execute(stmt)
        if res.scalar_one_or_none() is None:
            wf.short_code = code
            return
    raise BadRequestError("Could not allocate a unique workflow code — please retry")


async def resolve_published_workflow_id(
    db: AsyncSession,
    org_id: UUID,
    *,
    workflow_id: UUID | None,
    workflow_code: str | None,
) -> UUID:
    """Return internal workflow UUID from either UUID or 6-digit org-scoped code."""
    if workflow_id is not None:
        stmt = (
            select(Workflow)
            .where(
                Workflow.id == workflow_id,
                Workflow.org_id == org_id,
                Workflow.status == "published",
            )
        )
        res = await db.execute(stmt)
        wf = res.scalar_one_or_none()
        if not wf:
            raise NotFoundError("Published workflow not found")
        return wf.id

    raw = (workflow_code or "").strip()
    if len(raw) != 6 or not raw.isdigit():
        raise BadRequestError("workflow_code must be exactly 6 digits")

    stmt = select(Workflow).where(
        Workflow.org_id == org_id,
        Workflow.short_code == raw,
        Workflow.status == "published",
    )
    res = await db.execute(stmt)
    wf = res.scalar_one_or_none()
    if not wf:
        raise NotFoundError("Published workflow not found for this code")
    return wf.id
