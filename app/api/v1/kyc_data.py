"""KYC data registry — rich query endpoints for the org dashboard."""

import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthContext, require_jwt
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.applicant import Applicant
from app.models.biometric import BiometricResult
from app.models.consent import ConsentGrant
from app.models.document import DocumentArtifact, ExtractedIdentity
from app.models.verification import StepProgress, VerificationSession
from app.schemas.applicant import ApplicantListOut
from app.schemas.common import PaginatedResponse
from app.schemas.kyc_data import (
    KycBiometricDetail,
    KycDocumentDetail,
    KycSessionSummary,
    KycStepDetail,
    KycSummaryOut,
)
from app.schemas.verification import VerificationListOut

router = APIRouter(tags=["KYC Data"])


@router.get("/applicants", response_model=PaginatedResponse[ApplicantListOut])
async def list_applicants(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    workflow_id: Optional[UUID] = Query(None),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    base = select(Applicant).where(Applicant.org_id == auth.org_id)

    if search:
        pattern = f"%{search}%"
        base = base.where(
            Applicant.full_name.ilike(pattern)
            | Applicant.email.ilike(pattern)
            | Applicant.phone.ilike(pattern)
            | Applicant.external_id.ilike(pattern)
        )
    if created_after:
        base = base.where(Applicant.created_at >= created_after)
    if created_before:
        base = base.where(Applicant.created_at <= created_before)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0

    order_col = getattr(Applicant, sort_by, Applicant.created_at)
    if sort_order == "asc":
        base = base.order_by(order_col.asc())
    else:
        base = base.order_by(order_col.desc())

    base = base.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(base)
    applicants = result.scalars().all()

    items = []
    for app in applicants:
        latest_session = await db.execute(
            select(VerificationSession)
            .where(VerificationSession.applicant_id == app.id)
            .order_by(VerificationSession.created_at.desc())
            .limit(1)
        )
        ls = latest_session.scalar_one_or_none()

        items.append(
            ApplicantListOut(
                id=app.id,
                external_id=app.external_id,
                email=app.email,
                phone=app.phone,
                full_name=app.full_name,
                verification_status=ls.result if ls else "not_started",
                tier_reached=None,
                last_verified_at=ls.completed_at if ls else None,
                created_at=app.created_at,
            )
        )

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/verifications", response_model=PaginatedResponse[VerificationListOut])
async def list_verifications(
    applicant_id: Optional[UUID] = Query(None),
    workflow_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    started_after: Optional[datetime] = Query(None),
    started_before: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    base = select(VerificationSession).where(
        VerificationSession.org_id == auth.org_id
    )
    if applicant_id:
        base = base.where(VerificationSession.applicant_id == applicant_id)
    if workflow_id:
        base = base.where(VerificationSession.workflow_id == workflow_id)
    if status:
        base = base.where(VerificationSession.status == status)
    if result:
        base = base.where(VerificationSession.result == result)
    if started_after:
        base = base.where(VerificationSession.started_at >= started_after)
    if started_before:
        base = base.where(VerificationSession.started_at <= started_before)

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0

    order_col = getattr(VerificationSession, sort_by, VerificationSession.created_at)
    if sort_order == "asc":
        base = base.order_by(order_col.asc())
    else:
        base = base.order_by(order_col.desc())

    base = base.offset((page - 1) * page_size).limit(page_size)
    res = await db.execute(base)
    sessions = res.scalars().all()

    return PaginatedResponse(
        items=[
            VerificationListOut(
                id=s.id,
                applicant_id=s.applicant_id,
                workflow_id=s.workflow_id,
                status=s.status,
                result=s.result,
                current_step_order=s.current_step_order,
                started_at=s.started_at,
                completed_at=s.completed_at,
                created_at=s.created_at,
            )
            for s in sessions
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/applicants/{applicant_id}/kyc-summary", response_model=KycSummaryOut)
async def get_kyc_summary(
    applicant_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    app_stmt = select(Applicant).where(
        Applicant.id == applicant_id, Applicant.org_id == auth.org_id
    )
    app_result = await db.execute(app_stmt)
    applicant = app_result.scalar_one_or_none()
    if not applicant:
        raise NotFoundError("Applicant not found")

    sessions_stmt = (
        select(VerificationSession)
        .where(VerificationSession.applicant_id == applicant_id)
        .options(
            selectinload(VerificationSession.step_progress).selectinload(StepProgress.tier_profile),
            selectinload(VerificationSession.workflow),
        )
        .order_by(VerificationSession.created_at.desc())
    )
    sessions_result = await db.execute(sessions_stmt)
    sessions = sessions_result.scalars().all()

    session_summaries = []
    for session in sessions:
        step_details = []
        for sp in sorted(session.step_progress, key=lambda s: s.step_order):
            docs_stmt = (
                select(DocumentArtifact)
                .where(DocumentArtifact.step_progress_id == sp.id)
                .options(selectinload(DocumentArtifact.extracted_identity))
            )
            docs_result = await db.execute(docs_stmt)
            docs = docs_result.scalars().all()

            bio_stmt = select(BiometricResult).where(
                BiometricResult.step_progress_id == sp.id
            )
            bio_result = await db.execute(bio_stmt)
            bios = bio_result.scalars().all()

            step_details.append(
                KycStepDetail(
                    step_order=sp.step_order,
                    tier_profile_name=sp.tier_profile.name if sp.tier_profile else None,
                    status=sp.status,
                    checks_completed=sp.checks_completed,
                    attributes_collected=sp.attributes_collected,
                    documents=[
                        KycDocumentDetail(
                            id=d.id,
                            document_type=d.document_type,
                            original_filename=d.original_filename,
                            confidence_score=d.extracted_identity.confidence_score if d.extracted_identity else None,
                            document_classification=d.extracted_identity.document_classification if d.extracted_identity else None,
                            fraud_signals=d.extracted_identity.fraud_signals if d.extracted_identity else {},
                            created_at=d.created_at,
                        )
                        for d in docs
                    ],
                    biometrics=[
                        KycBiometricDetail(
                            id=b.id,
                            check_type=b.check_type,
                            passed=b.passed,
                            score=b.score,
                            created_at=b.created_at,
                        )
                        for b in bios
                    ],
                )
            )

        session_summaries.append(
            KycSessionSummary(
                session_id=session.id,
                workflow_id=session.workflow_id,
                workflow_name=session.workflow.name if session.workflow else None,
                status=session.status,
                result=session.result,
                current_step_order=session.current_step_order,
                total_steps=len(session.step_progress),
                started_at=session.started_at,
                completed_at=session.completed_at,
                steps=step_details,
            )
        )

    consent_count_stmt = select(func.count()).where(
        ConsentGrant.applicant_id == applicant_id,
        ConsentGrant.revoked_at.is_(None),
    )
    consent_count_result = await db.execute(consent_count_stmt)
    active_consents = consent_count_result.scalar() or 0

    return KycSummaryOut(
        applicant_id=applicant.id,
        external_id=applicant.external_id,
        full_name=applicant.full_name,
        email=applicant.email,
        phone=applicant.phone,
        metadata=applicant.metadata_,
        sessions=session_summaries,
        active_consents=active_consents,
    )
