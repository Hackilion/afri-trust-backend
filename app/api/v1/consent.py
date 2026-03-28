from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_client_ip, require_jwt
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.applicant import Applicant
from app.models.consent import ConsentGrant
from app.models.verification import StepProgress, VerificationSession
from app.schemas.common import StatusMessage
from app.schemas.consent import (
    ConsentGrantListOut,
    ConsentGrantOut,
    ConsentGrantRequest,
    IdentityDataOut,
)
from app.services import audit_service, consent_service

router = APIRouter(tags=["Consent & Identity"])


@router.get("/consents", response_model=list[ConsentGrantListOut])
async def list_org_consents(
    active_only: bool = Query(False),
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    """All consent grants for the authenticated user's organisation."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(ConsentGrant, Applicant.full_name)
        .join(Applicant, Applicant.id == ConsentGrant.applicant_id)
        .where(
            ConsentGrant.org_id == auth.org_id,
            Applicant.org_id == auth.org_id,
        )
        .order_by(ConsentGrant.created_at.desc())
    )
    if active_only:
        stmt = stmt.where(
            ConsentGrant.revoked_at.is_(None),
            ConsentGrant.expires_at > now,
        )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        ConsentGrantListOut(
            id=g.id,
            applicant_id=g.applicant_id,
            applicant_full_name=name,
            session_id=g.session_id,
            granted_attributes=g.granted_attributes or [],
            expires_at=g.expires_at,
            revoked_at=g.revoked_at,
            created_at=g.created_at,
        )
        for g, name in rows
    ]


@router.post(
    "/verifications/{session_id}/consent",
    response_model=ConsentGrantOut,
    status_code=201,
)
async def grant_consent(
    session_id: UUID,
    body: ConsentGrantRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(VerificationSession).where(
        VerificationSession.id == session_id,
        VerificationSession.org_id == auth.org_id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Session not found")

    grant, raw_token = await consent_service.create_consent(
        db,
        applicant_id=session.applicant_id,
        org_id=session.org_id,
        session_id=session.id,
        granted_attributes=body.granted_attributes,
        expires_in_days=body.expires_in_days,
    )

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="consent.granted",
        resource_type="consent_grant",
        resource_id=grant.id,
        ip_address=get_client_ip(request),
    )

    return ConsentGrantOut(
        id=grant.id,
        applicant_id=grant.applicant_id,
        session_id=grant.session_id,
        granted_attributes=grant.granted_attributes,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        verification_token=raw_token,
        created_at=grant.created_at,
    )


@router.get("/identities/{applicant_id}", response_model=IdentityDataOut)
async def get_identity_data(
    applicant_id: UUID,
    request: Request,
    attributes: str = Query(..., description="Comma-separated attribute keys"),
    verification_token: str = Query(...),
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    grant = await consent_service.validate_token(db, verification_token)
    if not grant:
        raise NotFoundError("Invalid or expired verification token")
    if grant.applicant_id != applicant_id:
        raise NotFoundError("Token does not match applicant")

    requested = {a.strip() for a in attributes.split(",")}
    allowed = set(grant.granted_attributes)
    filtered = requested & allowed

    sessions_stmt = (
        select(VerificationSession)
        .where(
            VerificationSession.applicant_id == applicant_id,
            VerificationSession.org_id == auth.org_id,
            VerificationSession.result == "approved",
        )
        .order_by(VerificationSession.completed_at.desc())
    )
    sessions_result = await db.execute(sessions_stmt)
    sessions = sessions_result.scalars().all()

    collected: dict = {}
    for session in sessions:
        steps_stmt = (
            select(StepProgress)
            .where(StepProgress.session_id == session.id)
            .order_by(StepProgress.step_order)
        )
        steps_result = await db.execute(steps_stmt)
        for sp in steps_result.scalars().all():
            attrs = sp.attributes_collected or {}
            for k, v in attrs.items():
                if k in filtered and k not in collected:
                    collected[k] = v

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="identity.accessed",
        resource_type="applicant",
        resource_id=applicant_id,
        ip_address=get_client_ip(request),
        changes={
            "requested_attributes": list(requested),
            "returned_attributes": list(collected.keys()),
        },
    )

    return IdentityDataOut(applicant_id=applicant_id, attributes=collected)


@router.get(
    "/applicants/{applicant_id}/consents", response_model=list[ConsentGrantOut]
)
async def list_consents(
    applicant_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    app_stmt = select(Applicant).where(
        Applicant.id == applicant_id, Applicant.org_id == auth.org_id
    )
    if not (await db.execute(app_stmt)).scalar_one_or_none():
        raise NotFoundError("Applicant not found")

    stmt = (
        select(ConsentGrant)
        .where(ConsentGrant.applicant_id == applicant_id)
        .order_by(ConsentGrant.created_at.desc())
    )
    result = await db.execute(stmt)
    return [
        ConsentGrantOut(
            id=g.id,
            applicant_id=g.applicant_id,
            session_id=g.session_id,
            granted_attributes=g.granted_attributes,
            expires_at=g.expires_at,
            revoked_at=g.revoked_at,
            created_at=g.created_at,
        )
        for g in result.scalars().all()
    ]


@router.post(
    "/applicants/{applicant_id}/consents/{consent_id}/revoke",
    response_model=StatusMessage,
)
async def revoke_consent(
    applicant_id: UUID,
    consent_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ConsentGrant).where(
        ConsentGrant.id == consent_id,
        ConsentGrant.applicant_id == applicant_id,
        ConsentGrant.org_id == auth.org_id,
    )
    result = await db.execute(stmt)
    grant = result.scalar_one_or_none()
    if not grant:
        raise NotFoundError("Consent grant not found")

    grant.revoked_at = datetime.now(timezone.utc)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="consent.revoked",
        resource_type="consent_grant",
        resource_id=grant.id,
        ip_address=get_client_ip(request),
    )

    return StatusMessage(detail="Consent revoked")
