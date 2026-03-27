from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.api.deps import AuthContext, get_auth_context, get_client_ip, require_jwt, require_role
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.db.session import get_db
from app.models.applicant import Applicant
from app.models.verification import VerificationSession
from app.schemas.applicant import ApplicantCreate, ApplicantOut, ApplicantUpdate
from app.schemas.common import StatusMessage
from app.services import audit_service

router = APIRouter(prefix="/applicants", tags=["Applicants"])


@router.post("", response_model=ApplicantOut, status_code=201)
async def create_applicant(
    body: ApplicantCreate,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    if body.external_id:
        existing = await db.execute(
            select(Applicant).where(
                Applicant.org_id == auth.org_id,
                Applicant.external_id == body.external_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictError("Applicant with this external_id already exists")

    applicant = Applicant(
        org_id=auth.org_id,
        external_id=body.external_id,
        email=body.email,
        phone=body.phone,
        full_name=body.full_name,
        metadata_=body.metadata,
    )
    db.add(applicant)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="applicant.created",
        resource_type="applicant",
        resource_id=applicant.id,
        ip_address=get_client_ip(request),
    )

    return ApplicantOut(
        id=applicant.id,
        org_id=applicant.org_id,
        external_id=applicant.external_id,
        email=applicant.email,
        phone=applicant.phone,
        full_name=applicant.full_name,
        metadata=applicant.metadata_,
        created_at=applicant.created_at,
        updated_at=applicant.updated_at,
    )


@router.get("/{applicant_id}", response_model=ApplicantOut)
async def get_applicant(
    applicant_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Applicant).where(
        Applicant.id == applicant_id, Applicant.org_id == auth.org_id
    )
    result = await db.execute(stmt)
    applicant = result.scalar_one_or_none()
    if not applicant:
        raise NotFoundError("Applicant not found")

    return ApplicantOut(
        id=applicant.id,
        org_id=applicant.org_id,
        external_id=applicant.external_id,
        email=applicant.email,
        phone=applicant.phone,
        full_name=applicant.full_name,
        metadata=applicant.metadata_,
        created_at=applicant.created_at,
        updated_at=applicant.updated_at,
    )


@router.put("/{applicant_id}", response_model=ApplicantOut)
async def update_applicant(
    applicant_id: UUID,
    body: ApplicantUpdate,
    request: Request,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Applicant).where(
        Applicant.id == applicant_id, Applicant.org_id == auth.org_id
    )
    result = await db.execute(stmt)
    applicant = result.scalar_one_or_none()
    if not applicant:
        raise NotFoundError("Applicant not found")

    if body.email is not None:
        applicant.email = body.email
    if body.phone is not None:
        applicant.phone = body.phone
    if body.full_name is not None:
        applicant.full_name = body.full_name
    if body.metadata is not None:
        applicant.metadata_ = body.metadata

    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="applicant.updated",
        resource_type="applicant",
        resource_id=applicant.id,
        ip_address=get_client_ip(request),
    )

    return ApplicantOut(
        id=applicant.id,
        org_id=applicant.org_id,
        external_id=applicant.external_id,
        email=applicant.email,
        phone=applicant.phone,
        full_name=applicant.full_name,
        metadata=applicant.metadata_,
        created_at=applicant.created_at,
        updated_at=applicant.updated_at,
    )


@router.delete("/{applicant_id}", response_model=StatusMessage)
async def delete_applicant(
    applicant_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Applicant).where(
        Applicant.id == applicant_id, Applicant.org_id == auth.org_id
    )
    result = await db.execute(stmt)
    applicant = result.scalar_one_or_none()
    if not applicant:
        raise NotFoundError("Applicant not found")

    active_sessions = await db.execute(
        select(func.count()).where(
            VerificationSession.applicant_id == applicant_id,
            VerificationSession.status.notin_(["approved", "rejected"]),
        )
    )
    if (active_sessions.scalar() or 0) > 0:
        raise BadRequestError(
            "Cannot delete applicant with active verification sessions"
        )

    await db.delete(applicant)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="applicant.deleted",
        resource_type="applicant",
        resource_id=applicant_id,
        ip_address=get_client_ip(request),
    )

    return StatusMessage(detail="Applicant deleted")
