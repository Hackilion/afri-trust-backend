from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthContext, get_client_ip, require_jwt, require_role
from app.core.exceptions import BadRequestError, NotFoundError, WorkflowLifecycleError
from app.db.session import get_db
from app.models.tier_profile import TierProfile
from app.models.workflow import Workflow, WorkflowStep
from app.schemas.common import StatusMessage
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowListOut,
    WorkflowOut,
    WorkflowStepCreate,
    WorkflowStepOut,
    WorkflowStepUpdate,
    WorkflowUpdate,
)
from app.services import audit_service

router = APIRouter(prefix="/workflows", tags=["Workflows"])


def _step_to_out(step: WorkflowStep) -> WorkflowStepOut:
    tp_name = step.tier_profile.name if step.tier_profile else None
    return WorkflowStepOut(
        id=step.id,
        workflow_id=step.workflow_id,
        tier_profile_id=step.tier_profile_id,
        tier_profile_name=tp_name,
        step_order=step.step_order,
        is_optional=step.is_optional,
        created_at=step.created_at,
    )


async def _load_workflow(db: AsyncSession, wf_id: UUID, org_id: UUID) -> Workflow:
    stmt = (
        select(Workflow)
        .where(Workflow.id == wf_id, Workflow.org_id == org_id)
        .options(selectinload(Workflow.steps).selectinload(WorkflowStep.tier_profile))
    )
    result = await db.execute(stmt)
    wf = result.scalar_one_or_none()
    if not wf:
        raise NotFoundError("Workflow not found")
    return wf


@router.post("", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = Workflow(
        org_id=auth.org_id,
        name=body.name,
        description=body.description,
        status="draft",
    )
    db.add(wf)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="workflow.created",
        resource_type="workflow",
        resource_id=wf.id,
        ip_address=get_client_ip(request),
    )

    return WorkflowOut(
        id=wf.id,
        org_id=wf.org_id,
        name=wf.name,
        description=wf.description,
        status=wf.status,
        version=wf.version,
        published_at=wf.published_at,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        steps=[],
    )


@router.get("", response_model=list[WorkflowListOut])
async def list_workflows(
    status: str = None,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Workflow).where(Workflow.org_id == auth.org_id)
    if status:
        stmt = stmt.where(Workflow.status == status)
    stmt = stmt.order_by(Workflow.created_at.desc())

    result = await db.execute(
        stmt.options(selectinload(Workflow.steps))
    )
    workflows = result.scalars().all()

    return [
        WorkflowListOut(
            id=wf.id,
            org_id=wf.org_id,
            name=wf.name,
            description=wf.description,
            status=wf.status,
            version=wf.version,
            step_count=len(wf.steps),
            published_at=wf.published_at,
            created_at=wf.created_at,
        )
        for wf in workflows
    ]


@router.get("/{wf_id}", response_model=WorkflowOut)
async def get_workflow(
    wf_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    return WorkflowOut(
        id=wf.id,
        org_id=wf.org_id,
        name=wf.name,
        description=wf.description,
        status=wf.status,
        version=wf.version,
        published_at=wf.published_at,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        steps=[_step_to_out(s) for s in sorted(wf.steps, key=lambda s: s.step_order)],
    )


@router.put("/{wf_id}", response_model=WorkflowOut)
async def update_workflow(
    wf_id: UUID,
    body: WorkflowUpdate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    if wf.status != "draft":
        raise WorkflowLifecycleError("Only draft workflows can be edited")

    if body.name is not None:
        wf.name = body.name
    if body.description is not None:
        wf.description = body.description

    await db.flush()
    return await get_workflow(wf_id, auth, db)


@router.delete("/{wf_id}", response_model=StatusMessage)
async def delete_workflow(
    wf_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    if wf.status != "draft":
        raise WorkflowLifecycleError("Only draft workflows can be deleted")

    await db.delete(wf)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="workflow.deleted",
        resource_type="workflow",
        resource_id=wf_id,
        ip_address=get_client_ip(request),
    )

    return StatusMessage(detail="Workflow deleted")


# ---- Step management ----


@router.get("/{wf_id}/steps", response_model=list[WorkflowStepOut])
async def list_steps(
    wf_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    return [_step_to_out(s) for s in sorted(wf.steps, key=lambda s: s.step_order)]


@router.post("/{wf_id}/steps", response_model=WorkflowStepOut, status_code=201)
async def add_step(
    wf_id: UUID,
    body: WorkflowStepCreate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    if wf.status != "draft":
        raise WorkflowLifecycleError("Can only add steps to draft workflows")

    tp_stmt = select(TierProfile).where(
        TierProfile.id == body.tier_profile_id,
        TierProfile.org_id == auth.org_id,
        TierProfile.is_active.is_(True),
    )
    tp_result = await db.execute(tp_stmt)
    tp = tp_result.scalar_one_or_none()
    if not tp:
        raise NotFoundError("Active tier profile not found")

    existing_order = await db.execute(
        select(WorkflowStep).where(
            WorkflowStep.workflow_id == wf.id,
            WorkflowStep.step_order == body.step_order,
        )
    )
    if existing_order.scalar_one_or_none():
        raise BadRequestError(
            f"Step order {body.step_order} already exists in this workflow"
        )

    step = WorkflowStep(
        workflow_id=wf.id,
        tier_profile_id=body.tier_profile_id,
        step_order=body.step_order,
        is_optional=body.is_optional,
    )
    db.add(step)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise BadRequestError(
            f"Step order {body.step_order} already exists in this workflow"
        )

    step.tier_profile = tp
    return _step_to_out(step)


@router.put("/{wf_id}/steps/{step_id}", response_model=WorkflowStepOut)
async def update_step(
    wf_id: UUID,
    step_id: UUID,
    body: WorkflowStepUpdate,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    if wf.status != "draft":
        raise WorkflowLifecycleError("Can only edit steps of draft workflows")

    step_stmt = select(WorkflowStep).where(
        WorkflowStep.id == step_id, WorkflowStep.workflow_id == wf_id
    ).options(selectinload(WorkflowStep.tier_profile))
    step_result = await db.execute(step_stmt)
    step = step_result.scalar_one_or_none()
    if not step:
        raise NotFoundError("Step not found")

    if body.step_order is not None and body.step_order != step.step_order:
        conflict = await db.execute(
            select(WorkflowStep).where(
                WorkflowStep.workflow_id == wf_id,
                WorkflowStep.step_order == body.step_order,
                WorkflowStep.id != step_id,
            )
        )
        if conflict.scalar_one_or_none():
            raise BadRequestError(
                f"Step order {body.step_order} already used by another step"
            )
        step.step_order = body.step_order

    if body.is_optional is not None:
        step.is_optional = body.is_optional

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise BadRequestError("Step order conflict")

    return _step_to_out(step)


@router.delete("/{wf_id}/steps/{step_id}", response_model=StatusMessage)
async def remove_step(
    wf_id: UUID,
    step_id: UUID,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    if wf.status != "draft":
        raise WorkflowLifecycleError("Can only remove steps from draft workflows")

    step_stmt = select(WorkflowStep).where(
        WorkflowStep.id == step_id, WorkflowStep.workflow_id == wf_id
    )
    step_result = await db.execute(step_stmt)
    step = step_result.scalar_one_or_none()
    if not step:
        raise NotFoundError("Step not found")

    await db.delete(step)
    await db.flush()

    # Two-phase renumber so (workflow_id, step_order) stays unique under SQLite while updating.
    remaining_result = await db.execute(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == wf_id)
        .order_by(WorkflowStep.step_order)
    )
    remaining = list(remaining_result.scalars().all())
    tmp_base = 1_000_000
    for i, s in enumerate(remaining):
        s.step_order = tmp_base + i
    await db.flush()
    for i, s in enumerate(remaining, start=1):
        s.step_order = i
    await db.flush()

    return StatusMessage(detail="Step removed")


# ---- Lifecycle actions ----


@router.post("/{wf_id}/publish", response_model=WorkflowOut)
async def publish_workflow(
    wf_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    if wf.status != "draft":
        raise WorkflowLifecycleError("Only draft workflows can be published")

    if not wf.steps:
        raise BadRequestError("Workflow must have at least one step to publish")

    for step in wf.steps:
        if not step.tier_profile or not step.tier_profile.is_active:
            raise BadRequestError(
                f"Step {step.step_order}: tier profile is inactive or missing"
            )

    wf.status = "published"
    wf.published_at = datetime.now(timezone.utc)
    wf.version += 1
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="workflow.published",
        resource_type="workflow",
        resource_id=wf.id,
        ip_address=get_client_ip(request),
        changes={"version": wf.version},
    )

    return await get_workflow(wf_id, auth, db)


@router.post("/{wf_id}/archive", response_model=WorkflowOut)
async def archive_workflow(
    wf_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)
    if wf.status != "published":
        raise WorkflowLifecycleError("Only published workflows can be archived")

    wf.status = "archived"
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="workflow.archived",
        resource_type="workflow",
        resource_id=wf.id,
        ip_address=get_client_ip(request),
    )

    return await get_workflow(wf_id, auth, db)


@router.post("/{wf_id}/clone", response_model=WorkflowOut, status_code=201)
async def clone_workflow(
    wf_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    wf = await _load_workflow(db, wf_id, auth.org_id)

    new_wf = Workflow(
        org_id=auth.org_id,
        name=f"{wf.name} (copy)",
        description=wf.description,
        status="draft",
    )
    db.add(new_wf)
    await db.flush()

    for step in sorted(wf.steps, key=lambda s: s.step_order):
        new_step = WorkflowStep(
            workflow_id=new_wf.id,
            tier_profile_id=step.tier_profile_id,
            step_order=step.step_order,
            is_optional=step.is_optional,
        )
        db.add(new_step)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="workflow.cloned",
        resource_type="workflow",
        resource_id=new_wf.id,
        ip_address=get_client_ip(request),
        changes={"cloned_from": str(wf_id)},
    )

    return await get_workflow(new_wf.id, auth, db)
