"""Verification orchestrator — drives sessions through workflow steps.

For each step, it checks the tier profile's required_checks and
attribute_schema to determine what data is needed and whether the step
can be marked as passed.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.applicant import Applicant
from app.models.tier_profile import TierProfile
from app.models.verification import StepProgress, VerificationSession
from app.models.workflow import Workflow, WorkflowStep
from app.services import audit_service, webhook_dispatcher

logger = logging.getLogger(__name__)

DOCUMENT_CHECKS = {"government_id", "address_proof"}
BIOMETRIC_CHECKS = {"selfie", "face_match", "liveness"}
AUTO_CHECKS = {"email", "phone"}

DOC_TYPE_TO_CHECK = {
    "passport": "government_id",
    "national_id": "government_id",
    "drivers_license": "government_id",
    "voter_card": "government_id",
    "residence_permit": "government_id",
    "address_proof": "address_proof",
    "other": None,
}

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def create_session(
    db: AsyncSession,
    *,
    org_id: UUID,
    applicant_id: UUID,
    workflow_id: UUID,
    actor_id: Optional[UUID] = None,
    actor_type: str = "api_key",
    ip_address: Optional[str] = None,
) -> VerificationSession:
    wf_stmt = (
        select(Workflow)
        .where(
            Workflow.id == workflow_id,
            Workflow.org_id == org_id,
            Workflow.status == "published",
        )
        .options(selectinload(Workflow.steps))
    )
    wf_result = await db.execute(wf_stmt)
    workflow = wf_result.scalar_one_or_none()
    if not workflow:
        raise NotFoundError("Published workflow not found")

    app_stmt = select(Applicant).where(
        Applicant.id == applicant_id, Applicant.org_id == org_id
    )
    app_result = await db.execute(app_stmt)
    applicant = app_result.scalar_one_or_none()
    if not applicant:
        raise NotFoundError("Applicant not found")

    if not workflow.steps:
        raise BadRequestError("Workflow has no steps")

    active_stmt = select(VerificationSession).where(
        VerificationSession.applicant_id == applicant_id,
        VerificationSession.workflow_id == workflow_id,
        VerificationSession.status.notin_(["approved", "rejected"]),
    )
    active_result = await db.execute(active_stmt)
    if active_result.scalar_one_or_none():
        raise BadRequestError(
            "An active verification session already exists for this applicant and workflow"
        )

    session = VerificationSession(
        org_id=org_id,
        applicant_id=applicant_id,
        workflow_id=workflow_id,
        workflow_version=workflow.version,
        current_step_order=1,
        status="created",
        result="pending",
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.flush()

    for step in sorted(workflow.steps, key=lambda s: s.step_order):
        sp = StepProgress(
            session_id=session.id,
            workflow_step_id=step.id,
            tier_profile_id=step.tier_profile_id,
            step_order=step.step_order,
            status="pending",
        )
        db.add(sp)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="verification.created",
        resource_type="verification_session",
        resource_id=session.id,
        ip_address=ip_address,
        changes={
            "workflow_id": str(workflow_id),
            "applicant_id": str(applicant_id),
        },
    )

    await webhook_dispatcher.dispatch_event(
        db,
        org_id=org_id,
        event_type="verification.created",
        payload={
            "session_id": str(session.id),
            "applicant_id": str(applicant_id),
        },
    )

    return session


def _guard_session_active(session: VerificationSession) -> None:
    if session.status in ("approved", "rejected"):
        raise BadRequestError("Session is already finalized")


async def get_current_step(
    db: AsyncSession, session: VerificationSession
) -> Optional[StepProgress]:
    stmt = select(StepProgress).where(
        StepProgress.session_id == session.id,
        StepProgress.step_order == session.current_step_order,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_tier_profile_for_step(
    db: AsyncSession, step: StepProgress
) -> TierProfile:
    stmt = select(TierProfile).where(TierProfile.id == step.tier_profile_id)
    result = await db.execute(stmt)
    tp = result.scalar_one_or_none()
    if not tp:
        raise NotFoundError("Tier profile not found")
    return tp


async def get_required_data(
    db: AsyncSession, session: VerificationSession
) -> dict[str, Any]:
    """Return what the current step needs: pending checks, missing attributes."""
    step = await get_current_step(db, session)
    if not step:
        return {"complete": True, "message": "All steps completed"}

    tier = await get_tier_profile_for_step(db, step)
    required_checks = set(tier.required_checks or [])
    completed_checks = step.checks_completed or {}
    schema = tier.attribute_schema or []

    pending_checks = [
        c for c in required_checks if c not in completed_checks
    ]
    failed_checks = [
        c for c in required_checks if completed_checks.get(c) is False
    ]
    passed_checks = [
        c for c in required_checks if completed_checks.get(c) is True
    ]

    required_attrs = {
        a["key"] for a in schema if a.get("required", True)
    }
    collected_attrs = set((step.attributes_collected or {}).keys())
    missing_attrs = list(required_attrs - collected_attrs)

    return {
        "session_id": str(session.id),
        "current_step_order": step.step_order,
        "tier_profile_name": tier.name,
        "step_status": step.status,
        "checks": {
            "required": list(required_checks),
            "passed": passed_checks,
            "failed": failed_checks,
            "pending": pending_checks,
        },
        "attributes": {
            "schema": schema,
            "missing_required": missing_attrs,
            "collected": list(collected_attrs),
        },
        "accepted_document_types": tier.accepted_document_types or [],
    }


def validate_attributes(
    submitted: dict[str, Any], attribute_schema: list[dict[str, Any]]
) -> list[str]:
    """Validate submitted attributes against the tier's dynamic schema.

    Returns a list of validation errors (empty = valid).
    """
    errors: list[str] = []
    schema_map = {attr["key"]: attr for attr in attribute_schema}

    unknown_keys = set(submitted.keys()) - set(schema_map.keys())
    if unknown_keys:
        errors.append(
            f"Unknown attributes not defined in tier schema: {', '.join(sorted(unknown_keys))}"
        )

    for attr_def in attribute_schema:
        key = attr_def["key"]
        required = attr_def.get("required", True)
        if required and key not in submitted:
            errors.append(f"Missing required attribute: {key}")

    for key, value in submitted.items():
        if key not in schema_map:
            continue
        attr_def = schema_map[key]
        data_type = attr_def.get("data_type", "string")
        validation = attr_def.get("validation") or {}

        if value is None:
            if attr_def.get("required", True):
                errors.append(f"Attribute '{key}' cannot be null")
            continue

        if data_type == "string":
            if not isinstance(value, str):
                errors.append(f"Attribute '{key}' must be a string")
                continue
        elif data_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"Attribute '{key}' must be a number")
                continue
        elif data_type == "boolean":
            if not isinstance(value, bool):
                errors.append(f"Attribute '{key}' must be a boolean")
                continue
        elif data_type == "date":
            if not isinstance(value, str):
                errors.append(f"Attribute '{key}' must be a date string (YYYY-MM-DD)")
                continue
            if not DATE_PATTERN.match(value):
                errors.append(
                    f"Attribute '{key}' must be in YYYY-MM-DD format"
                )
                continue
        elif data_type == "enum":
            options = attr_def.get("options", [])
            if value not in options:
                errors.append(
                    f"Attribute '{key}' must be one of {options}"
                )
                continue
        elif data_type == "file":
            if not isinstance(value, str):
                errors.append(f"Attribute '{key}' must be a file reference string")
                continue

        if isinstance(value, str) and data_type in ("string", "date"):
            min_len = validation.get("min_length")
            max_len = validation.get("max_length")
            pattern = validation.get("pattern")
            if min_len is not None and len(value) < min_len:
                errors.append(
                    f"Attribute '{key}' must be at least {min_len} characters"
                )
            if max_len is not None and len(value) > max_len:
                errors.append(
                    f"Attribute '{key}' must be at most {max_len} characters"
                )
            if pattern and not re.match(pattern, value):
                errors.append(
                    f"Attribute '{key}' does not match required pattern"
                )

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            min_val = validation.get("min")
            max_val = validation.get("max")
            if min_val is not None and value < min_val:
                errors.append(f"Attribute '{key}' must be >= {min_val}")
            if max_val is not None and value > max_val:
                errors.append(f"Attribute '{key}' must be <= {max_val}")

    return errors


def validate_document_type(
    document_type: str, accepted_types: list[str]
) -> Optional[str]:
    """Validate document type against tier's accepted list. Returns error or None."""
    if not accepted_types:
        return None
    if document_type not in accepted_types:
        return (
            f"Document type '{document_type}' not accepted. "
            f"Allowed: {', '.join(accepted_types)}"
        )
    return None


async def submit_attributes(
    db: AsyncSession,
    session: VerificationSession,
    attributes: dict[str, Any],
) -> StepProgress:
    """Submit and validate attributes against the current step's tier schema."""
    _guard_session_active(session)

    if not attributes:
        raise BadRequestError("No attributes submitted")

    step = await get_current_step(db, session)
    if not step:
        raise BadRequestError("No active step found")

    tier = await get_tier_profile_for_step(db, step)
    schema = tier.attribute_schema or []

    errors = validate_attributes(attributes, schema)
    if errors:
        raise BadRequestError("; ".join(errors))

    merged = dict(step.attributes_collected or {})
    merged.update(attributes)
    step.attributes_collected = merged

    attr_checks = {}
    for check in tier.required_checks or []:
        if check in AUTO_CHECKS:
            if check == "email" and "email_address" in merged:
                attr_checks[check] = True
            elif check == "phone" and "phone_number" in merged:
                attr_checks[check] = True

    if attr_checks:
        completed = dict(step.checks_completed or {})
        completed.update(attr_checks)
        step.checks_completed = completed

    if step.status == "pending":
        step.status = "in_progress"
        step.started_at = datetime.now(timezone.utc)
        if session.status == "created":
            session.status = "in_progress"

    await db.flush()
    await _try_advance(db, session, step, tier)
    return step


async def submit_document(
    db: AsyncSession,
    session: VerificationSession,
    document_type: str,
) -> tuple[StepProgress, TierProfile]:
    """Validate document type and mark the corresponding check."""
    _guard_session_active(session)

    step = await get_current_step(db, session)
    if not step:
        raise BadRequestError("No active step found")

    tier = await get_tier_profile_for_step(db, step)

    doc_error = validate_document_type(
        document_type, tier.accepted_document_types or []
    )
    if doc_error:
        raise BadRequestError(doc_error)

    check_type = DOC_TYPE_TO_CHECK.get(document_type)
    if check_type and check_type in (tier.required_checks or []):
        completed = dict(step.checks_completed or {})
        completed[check_type] = True
        step.checks_completed = completed

    if step.status == "pending":
        step.status = "in_progress"
        step.started_at = datetime.now(timezone.utc)
        if session.status == "created":
            session.status = "in_progress"

    await db.flush()
    await _try_advance(db, session, step, tier)
    return step, tier


async def mark_check_completed(
    db: AsyncSession,
    session: VerificationSession,
    check_type: str,
    passed: bool,
) -> StepProgress:
    _guard_session_active(session)

    step = await get_current_step(db, session)
    if not step:
        raise BadRequestError("No active step found")

    tier = await get_tier_profile_for_step(db, step)

    if check_type not in (tier.required_checks or []):
        logger.info(
            "Check '%s' not required by tier '%s', skipping",
            check_type,
            tier.name,
        )
        return step

    completed = dict(step.checks_completed or {})
    completed[check_type] = passed
    step.checks_completed = completed

    if step.status == "pending":
        step.status = "in_progress"
        step.started_at = datetime.now(timezone.utc)
        if session.status == "created":
            session.status = "in_progress"

    await db.flush()
    await _try_advance(db, session, step, tier)
    return step


async def _try_advance(
    db: AsyncSession,
    session: VerificationSession,
    step: StepProgress,
    tier: TierProfile,
) -> None:
    """Check if current step is complete and advance the session."""
    required_checks = set(tier.required_checks or [])
    completed_checks = step.checks_completed or {}

    all_checks_resolved = all(
        c in completed_checks for c in required_checks
    )

    required_attrs = {
        a["key"]
        for a in (tier.attribute_schema or [])
        if a.get("required", True)
    }
    collected_attrs = set((step.attributes_collected or {}).keys())
    all_attrs_done = required_attrs.issubset(collected_attrs)

    if not all_checks_resolved or not all_attrs_done:
        return

    any_check_failed = any(
        completed_checks.get(c) is False for c in required_checks
    )
    if any_check_failed:
        step.status = "failed"
        step.completed_at = datetime.now(timezone.utc)
        session.status = "rejected"
        session.result = "rejected"
        session.completed_at = datetime.now(timezone.utc)

        failed_list = [
            c for c in required_checks if completed_checks.get(c) is False
        ]
        details = dict(session.result_details or {})
        details["failed_checks"] = failed_list
        session.result_details = details

        await db.flush()
        await webhook_dispatcher.dispatch_event(
            db,
            org_id=session.org_id,
            event_type="verification.rejected",
            payload={
                "session_id": str(session.id),
                "failed_checks": failed_list,
            },
        )
        return

    step.status = "passed"
    step.completed_at = datetime.now(timezone.utc)

    await webhook_dispatcher.dispatch_event(
        db,
        org_id=session.org_id,
        event_type="verification.step_completed",
        payload={
            "session_id": str(session.id),
            "step_order": step.step_order,
        },
    )

    next_step_stmt = select(StepProgress).where(
        StepProgress.session_id == session.id,
        StepProgress.step_order == step.step_order + 1,
    )
    next_result = await db.execute(next_step_stmt)
    next_step = next_result.scalar_one_or_none()

    if next_step:
        session.current_step_order = next_step.step_order
        session.status = "in_progress"
    else:
        session.status = "approved"
        session.result = "approved"
        session.completed_at = datetime.now(timezone.utc)

        await webhook_dispatcher.dispatch_event(
            db,
            org_id=session.org_id,
            event_type="verification.approved",
            payload={"session_id": str(session.id)},
        )

    await db.flush()


async def review_session(
    db: AsyncSession,
    session: VerificationSession,
    decision: str,
    reason: Optional[str] = None,
    actor_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> VerificationSession:
    if session.status not in ("awaiting_review", "in_progress", "processing"):
        raise BadRequestError(
            f"Cannot review session in '{session.status}' status"
        )

    if decision not in ("approve", "reject"):
        raise BadRequestError("Decision must be 'approve' or 'reject'")

    if decision == "approve":
        session.status = "approved"
        session.result = "approved"
    else:
        session.status = "rejected"
        session.result = "rejected"

    session.completed_at = datetime.now(timezone.utc)
    result_details = dict(session.result_details or {})
    result_details["review_reason"] = reason
    result_details["reviewed_by"] = str(actor_id) if actor_id else None
    session.result_details = result_details

    await audit_service.log_event(
        db,
        org_id=session.org_id,
        actor_type="user",
        actor_id=actor_id,
        action=f"verification.{decision}d",
        resource_type="verification_session",
        resource_id=session.id,
        ip_address=ip_address,
        changes={"decision": decision, "reason": reason},
    )

    event = "verification.approved" if decision == "approve" else "verification.rejected"
    await webhook_dispatcher.dispatch_event(
        db,
        org_id=session.org_id,
        event_type=event,
        payload={"session_id": str(session.id), "decision": decision},
    )

    await db.flush()
    return session
