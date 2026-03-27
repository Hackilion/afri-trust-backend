from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_client_ip, require_jwt, require_role
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.session import get_db
from app.models.tier_profile import TierProfile
from app.models.workflow import Workflow, WorkflowStep
from app.schemas.common import CheckType, DocumentType, AttributeDataType, StatusMessage
from app.schemas.tier_profile import (
    CheckCatalogueOut,
    TierProfileCreate,
    TierProfileOut,
    TierProfileUpdate,
)
from app.services import audit_service

router = APIRouter(prefix="/tier-profiles", tags=["Tier Profiles"])


@router.get("/check-catalogue", response_model=CheckCatalogueOut)
async def check_catalogue(auth: AuthContext = Depends(require_jwt)):
    return CheckCatalogueOut(
        check_types=[{"value": c.value, "label": c.name.replace("_", " ").title()} for c in CheckType],
        document_types=[{"value": d.value, "label": d.name.replace("_", " ").title()} for d in DocumentType],
        attribute_data_types=[{"value": a.value, "label": a.name.replace("_", " ").title()} for a in AttributeDataType],
    )


@router.post("", response_model=TierProfileOut, status_code=201)
async def create_tier_profile(
    body: TierProfileCreate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    tp = TierProfile(
        org_id=auth.org_id,
        name=body.name,
        description=body.description,
        required_checks=[c.value for c in body.required_checks],
        attribute_schema=[a.model_dump(mode="json") for a in body.attribute_schema],
        accepted_document_types=[d.value for d in body.accepted_document_types],
        settings=body.settings,
    )
    db.add(tp)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="tier_profile.created",
        resource_type="tier_profile",
        resource_id=tp.id,
        ip_address=get_client_ip(request),
    )

    return tp


@router.get("", response_model=list[TierProfileOut])
async def list_tier_profiles(
    is_active: bool = True,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TierProfile).where(
        TierProfile.org_id == auth.org_id,
        TierProfile.is_active == is_active,
    ).order_by(TierProfile.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{tier_id}", response_model=TierProfileOut)
async def get_tier_profile(
    tier_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TierProfile).where(
        TierProfile.id == tier_id, TierProfile.org_id == auth.org_id
    )
    result = await db.execute(stmt)
    tp = result.scalar_one_or_none()
    if not tp:
        raise NotFoundError("Tier profile not found")
    return tp


@router.put("/{tier_id}", response_model=TierProfileOut)
async def update_tier_profile(
    tier_id: UUID,
    body: TierProfileUpdate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TierProfile).where(
        TierProfile.id == tier_id, TierProfile.org_id == auth.org_id
    )
    result = await db.execute(stmt)
    tp = result.scalar_one_or_none()
    if not tp:
        raise NotFoundError("Tier profile not found")

    published_ref = await db.execute(
        select(WorkflowStep).join(Workflow).where(
            WorkflowStep.tier_profile_id == tier_id,
            Workflow.status == "published",
        ).limit(1)
    )
    if published_ref.scalar_one_or_none():
        raise BadRequestError(
            "Cannot modify tier profile referenced by a published workflow. Archive the workflow first."
        )

    if body.name is not None:
        tp.name = body.name
    if body.description is not None:
        tp.description = body.description
    if body.required_checks is not None:
        tp.required_checks = [c.value for c in body.required_checks]
    if body.attribute_schema is not None:
        tp.attribute_schema = [a.model_dump(mode="json") for a in body.attribute_schema]
    if body.accepted_document_types is not None:
        tp.accepted_document_types = [d.value for d in body.accepted_document_types]
    if body.settings is not None:
        tp.settings = body.settings

    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="tier_profile.updated",
        resource_type="tier_profile",
        resource_id=tp.id,
        ip_address=get_client_ip(request),
    )

    return tp


@router.delete("/{tier_id}", response_model=StatusMessage)
async def delete_tier_profile(
    tier_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TierProfile).where(
        TierProfile.id == tier_id, TierProfile.org_id == auth.org_id
    )
    result = await db.execute(stmt)
    tp = result.scalar_one_or_none()
    if not tp:
        raise NotFoundError("Tier profile not found")

    published_ref = await db.execute(
        select(WorkflowStep).join(Workflow).where(
            WorkflowStep.tier_profile_id == tier_id,
            Workflow.status == "published",
        ).limit(1)
    )
    if published_ref.scalar_one_or_none():
        raise BadRequestError(
            "Cannot delete tier profile referenced by a published workflow"
        )

    tp.is_active = False
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="tier_profile.deleted",
        resource_type="tier_profile",
        resource_id=tp.id,
        ip_address=get_client_ip(request),
    )

    return StatusMessage(detail="Tier profile deactivated")
