import hashlib
import uuid as uuid_mod
from uuid import UUID

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthContext, get_auth_context, get_client_ip, require_role
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.session import get_db
from app.models.document import DocumentArtifact
from app.models.verification import StepProgress, VerificationSession
from app.schemas.verification import (
    ReviewRequest,
    StepProgressOut,
    SubmitAttributesRequest,
    VerificationCreate,
    VerificationDetailOut,
    VerificationOut,
)
from app.services import (
    audit_service,
    biometric_service,
    document_processor,
    orchestrator,
)
from app.services.workflow_short_code import resolve_published_workflow_id
from app.storage.local import get_storage

router = APIRouter(prefix="/verifications", tags=["Verifications"])

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/jpg",
    "application/octet-stream",
}
MAX_FILE_SIZE = 10 * 1024 * 1024


def _step_out(sp: StepProgress) -> StepProgressOut:
    return StepProgressOut(
        id=sp.id,
        session_id=sp.session_id,
        workflow_step_id=sp.workflow_step_id,
        tier_profile_id=sp.tier_profile_id,
        tier_profile_name=sp.tier_profile.name if sp.tier_profile else None,
        step_order=sp.step_order,
        status=sp.status,
        checks_completed=sp.checks_completed,
        attributes_collected=sp.attributes_collected,
        started_at=sp.started_at,
        completed_at=sp.completed_at,
        created_at=sp.created_at,
    )


async def _load_session(
    db: AsyncSession, session_id: UUID, org_id: UUID
) -> VerificationSession:
    stmt = select(VerificationSession).where(
        VerificationSession.id == session_id,
        VerificationSession.org_id == org_id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Verification session not found")
    return session


@router.post("", response_model=VerificationOut, status_code=201)
async def create_verification(
    body: VerificationCreate,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    workflow_uuid = await resolve_published_workflow_id(
        db,
        auth.org_id,
        workflow_id=body.workflow_id,
        workflow_code=body.workflow_code,
    )
    session = await orchestrator.create_session(
        db,
        org_id=auth.org_id,
        applicant_id=body.applicant_id,
        workflow_id=workflow_uuid,
        actor_id=auth.actor_id,
        actor_type=auth.actor_type,
        ip_address=get_client_ip(request),
    )
    return session


@router.get("/{session_id}", response_model=VerificationDetailOut)
async def get_verification(
    session_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(VerificationSession)
        .where(
            VerificationSession.id == session_id,
            VerificationSession.org_id == auth.org_id,
        )
        .options(
            selectinload(VerificationSession.step_progress).selectinload(
                StepProgress.tier_profile
            ),
            selectinload(VerificationSession.workflow),
            selectinload(VerificationSession.applicant),
        )
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Verification session not found")

    steps = [
        _step_out(sp)
        for sp in sorted(session.step_progress, key=lambda s: s.step_order)
    ]

    return VerificationDetailOut(
        id=session.id,
        org_id=session.org_id,
        applicant_id=session.applicant_id,
        workflow_id=session.workflow_id,
        workflow_version=session.workflow_version,
        current_step_order=session.current_step_order,
        status=session.status,
        result=session.result,
        result_details=session.result_details,
        started_at=session.started_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
        steps=steps,
        workflow_name=session.workflow.name if session.workflow else None,
        applicant_name=(
            session.applicant.full_name if session.applicant else None
        ),
    )


@router.get("/{session_id}/steps", response_model=list[StepProgressOut])
async def get_steps(
    session_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    await _load_session(db, session_id, auth.org_id)

    sp_stmt = (
        select(StepProgress)
        .where(StepProgress.session_id == session_id)
        .options(selectinload(StepProgress.tier_profile))
        .order_by(StepProgress.step_order)
    )
    sp_result = await db.execute(sp_stmt)
    return [_step_out(sp) for sp in sp_result.scalars().all()]


@router.get("/{session_id}/required-data")
async def get_required_data(
    session_id: UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """Show what the current step requires: pending checks, missing attributes,
    accepted document types. Essential for client SDK integration."""
    session = await _load_session(db, session_id, auth.org_id)
    return await orchestrator.get_required_data(db, session)


@router.post("/{session_id}/attributes", response_model=StepProgressOut)
async def submit_attributes(
    session_id: UUID,
    body: SubmitAttributesRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _load_session(db, session_id, auth.org_id)
    step = await orchestrator.submit_attributes(db, session, body.attributes)

    tier_stmt = (
        select(StepProgress)
        .where(StepProgress.id == step.id)
        .options(selectinload(StepProgress.tier_profile))
    )
    tier_result = await db.execute(tier_stmt)
    step = tier_result.scalar_one()
    return _step_out(step)


@router.post("/{session_id}/documents")
async def upload_document(
    session_id: UUID,
    request: Request,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _load_session(db, session_id, auth.org_id)
    orchestrator._guard_session_active(session)

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise BadRequestError("File too large (max 10 MB)")
    if not data:
        raise BadRequestError("Empty file")

    step, tier = await orchestrator.submit_document(
        db, session, document_type
    )

    file_hash = hashlib.sha256(data).hexdigest()
    file_key = (
        f"{auth.org_id}/{session_id}/{uuid_mod.uuid4()}/{file.filename}"
    )

    storage = get_storage()
    file_path = await storage.save(file_key, data)

    artifact = DocumentArtifact(
        session_id=session_id,
        step_progress_id=step.id,
        document_type=document_type,
        file_key=file_key,
        file_hash=file_hash,
        mime_type=file.content_type,
        original_filename=file.filename,
    )
    db.add(artifact)
    await db.flush()

    extracted = await document_processor.process_document(
        db, artifact, file_path
    )

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="document.uploaded",
        resource_type="document_artifact",
        resource_id=artifact.id,
        ip_address=get_client_ip(request),
    )

    return {
        "document_id": str(artifact.id),
        "document_type": document_type,
        "extracted_data": extracted.extracted_data,
        "confidence_score": extracted.confidence_score,
        "fraud_signals": extracted.fraud_signals,
    }


@router.post("/{session_id}/selfie")
async def upload_selfie(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _load_session(db, session_id, auth.org_id)
    orchestrator._guard_session_active(session)

    step = await orchestrator.get_current_step(db, session)
    if not step:
        raise BadRequestError("No active step")

    tier = await orchestrator.get_tier_profile_for_step(db, step)
    tier_checks = set(tier.required_checks or [])
    needs_selfie = "selfie" in tier_checks
    needs_face = "face_match" in tier_checks
    needs_liveness = "liveness" in tier_checks
    if not (needs_selfie or needs_face or needs_liveness):
        raise BadRequestError(
            "Current tier does not require selfie, face_match, or liveness checks"
        )

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise BadRequestError("File too large (max 10 MB)")
    if not data:
        raise BadRequestError("Empty file")

    file_key = (
        f"{auth.org_id}/{session_id}/selfie/{uuid_mod.uuid4()}/{file.filename}"
    )
    storage = get_storage()
    file_path = await storage.save(file_key, data)

    results: dict = {}

    if needs_selfie or needs_liveness:
        bio = await biometric_service.run_liveness_check(
            db,
            session_id=session_id,
            step_progress_id=step.id,
            image_path=file_path,
        )
        results["liveness_passed"] = bio.passed
        results["liveness_score"] = bio.score
        if needs_selfie:
            await orchestrator.mark_check_completed(
                db, session, "selfie", bio.passed
            )
        if needs_liveness:
            await orchestrator.mark_check_completed(
                db, session, "liveness", bio.passed
            )

    if needs_face:
        face = await biometric_service.run_face_match(
            db,
            session_id=session_id,
            step_progress_id=step.id,
            selfie_path=file_path,
            document_face_path=file_path,
        )
        results["face_match_passed"] = face.passed
        results["face_match_score"] = face.score
        await orchestrator.mark_check_completed(
            db, session, "face_match", face.passed
        )

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        action="selfie.uploaded",
        resource_type="verification_session",
        resource_id=session.id,
        ip_address=get_client_ip(request),
    )

    return results


@router.post("/{session_id}/liveness")
async def submit_liveness(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    session = await _load_session(db, session_id, auth.org_id)
    orchestrator._guard_session_active(session)

    step = await orchestrator.get_current_step(db, session)
    if not step:
        raise BadRequestError("No active step")

    tier = await orchestrator.get_tier_profile_for_step(db, step)
    if "liveness" not in (tier.required_checks or []):
        raise BadRequestError("Current tier does not require liveness check")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise BadRequestError("File too large (max 10 MB)")
    if not data:
        raise BadRequestError("Empty file")

    file_key = f"{auth.org_id}/{session_id}/liveness/{uuid_mod.uuid4()}"
    storage = get_storage()
    file_path = await storage.save(file_key, data)

    bio = await biometric_service.run_liveness_check(
        db,
        session_id=session_id,
        step_progress_id=step.id,
        image_path=file_path,
    )
    await orchestrator.mark_check_completed(
        db, session, "liveness", bio.passed
    )
    return {"passed": bio.passed, "score": bio.score}


@router.post("/{session_id}/review", response_model=VerificationOut)
async def review_verification(
    session_id: UUID,
    body: ReviewRequest,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await _load_session(db, session_id, auth.org_id)
    updated = await orchestrator.review_session(
        db,
        session,
        decision=body.decision,
        reason=body.reason,
        actor_id=auth.actor_id,
        ip_address=get_client_ip(request),
    )
    return updated
