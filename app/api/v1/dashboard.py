"""Dashboard statistics and reporting APIs.

Provides aggregated metrics, time-series data, verification funnel analysis,
tier/workflow breakdowns, and daily/weekly/monthly summaries.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, cast, Float, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_jwt
from app.db.session import get_db
from app.models.applicant import Applicant
from app.models.biometric import BiometricResult
from app.models.document import DocumentArtifact
from app.models.tier_profile import TierProfile
from app.models.verification import StepProgress, VerificationSession
from app.models.workflow import Workflow

router = APIRouter(prefix="/dashboard", tags=["Dashboard & Reports"])


@router.get("/stats")
async def get_dashboard_stats(
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    org_id = auth.org_id
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)

    total_applicants = (
        await db.execute(
            select(func.count()).where(Applicant.org_id == org_id)
        )
    ).scalar() or 0

    verifications_today = (
        await db.execute(
            select(func.count()).where(
                VerificationSession.org_id == org_id,
                VerificationSession.created_at >= today_start,
            )
        )
    ).scalar() or 0

    total_sessions = (
        await db.execute(
            select(func.count()).where(VerificationSession.org_id == org_id)
        )
    ).scalar() or 0

    approved_30d = (
        await db.execute(
            select(func.count()).where(
                VerificationSession.org_id == org_id,
                VerificationSession.result == "approved",
                VerificationSession.completed_at >= thirty_days_ago,
            )
        )
    ).scalar() or 0
    completed_30d = (
        await db.execute(
            select(func.count()).where(
                VerificationSession.org_id == org_id,
                VerificationSession.result.in_(["approved", "rejected"]),
                VerificationSession.completed_at >= thirty_days_ago,
            )
        )
    ).scalar() or 0
    approval_rate = (
        round(approved_30d / completed_30d * 100, 1) if completed_30d else None
    )

    completed_sessions = (
        await db.execute(
            select(
                VerificationSession.started_at,
                VerificationSession.completed_at,
            ).where(
                VerificationSession.org_id == org_id,
                VerificationSession.completed_at.isnot(None),
                VerificationSession.started_at.isnot(None),
            )
        )
    ).all()
    if completed_sessions:
        deltas = [
            (row[1] - row[0]).total_seconds() for row in completed_sessions
        ]
        avg_time = sum(deltas) / len(deltas)
    else:
        avg_time = None

    status_rows = (
        await db.execute(
            select(VerificationSession.result, func.count())
            .where(VerificationSession.org_id == org_id)
            .group_by(VerificationSession.result)
        )
    ).all()
    by_status = {r[0]: r[1] for r in status_rows}

    tier_rows = (
        await db.execute(
            select(TierProfile.name, VerificationSession.result, func.count())
            .join(
                StepProgress,
                StepProgress.session_id == VerificationSession.id,
            )
            .join(TierProfile, TierProfile.id == StepProgress.tier_profile_id)
            .where(VerificationSession.org_id == org_id)
            .group_by(TierProfile.name, VerificationSession.result)
        )
    ).all()
    by_tier: dict = {}
    for t_name, result_val, count in tier_rows:
        by_tier.setdefault(t_name, {})[result_val] = count

    wf_rows = (
        await db.execute(
            select(Workflow.name, VerificationSession.result, func.count())
            .join(Workflow, Workflow.id == VerificationSession.workflow_id)
            .where(VerificationSession.org_id == org_id)
            .group_by(Workflow.name, VerificationSession.result)
        )
    ).all()
    by_workflow: dict = {}
    for w_name, result_val, count in wf_rows:
        by_workflow.setdefault(w_name, {})[result_val] = count

    return {
        "total_applicants": total_applicants,
        "total_verifications": total_sessions,
        "verifications_today": verifications_today,
        "approval_rate_30d": approval_rate,
        "avg_time_to_verify_seconds": round(avg_time, 1) if avg_time else None,
        "by_status": by_status,
        "by_tier": by_tier,
        "by_workflow": by_workflow,
    }


@router.get("/stats/timeseries")
async def get_timeseries(
    days: int = Query(30, ge=1, le=365),
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Daily verification counts and outcomes for the last N days."""
    org_id = auth.org_id
    start = datetime.now(timezone.utc) - timedelta(days=days)

    day_col = func.date(VerificationSession.created_at).label("day")
    rows = (
        await db.execute(
            select(
                day_col,
                VerificationSession.result,
                func.count().label("count"),
            )
            .where(
                VerificationSession.org_id == org_id,
                VerificationSession.created_at >= start,
            )
            .group_by(day_col, VerificationSession.result)
            .order_by(day_col)
        )
    ).all()

    series: dict = {}
    for day, result_val, count in rows:
        day_str = str(day)
        series.setdefault(day_str, {"date": day_str, "total": 0})
        series[day_str][result_val] = count
        series[day_str]["total"] += count

    return {"days": days, "data": list(series.values())}


@router.get("/stats/funnel")
async def get_verification_funnel(
    workflow_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Verification funnel: how many sessions reach each step and outcome."""
    org_id = auth.org_id
    start = datetime.now(timezone.utc) - timedelta(days=days)

    base = select(VerificationSession).where(
        VerificationSession.org_id == org_id,
        VerificationSession.created_at >= start,
    )
    if workflow_id:
        base = base.where(VerificationSession.workflow_id == workflow_id)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    started = (
        await db.execute(
            select(func.count()).select_from(
                base.where(
                    VerificationSession.status != "created"
                ).subquery()
            )
        )
    ).scalar() or 0

    completed = (
        await db.execute(
            select(func.count()).select_from(
                base.where(
                    VerificationSession.result.in_(["approved", "rejected"])
                ).subquery()
            )
        )
    ).scalar() or 0

    approved = (
        await db.execute(
            select(func.count()).select_from(
                base.where(
                    VerificationSession.result == "approved"
                ).subquery()
            )
        )
    ).scalar() or 0

    rejected = (
        await db.execute(
            select(func.count()).select_from(
                base.where(
                    VerificationSession.result == "rejected"
                ).subquery()
            )
        )
    ).scalar() or 0

    step_rows = (
        await db.execute(
            select(
                StepProgress.step_order,
                TierProfile.name,
                StepProgress.status,
                func.count(),
            )
            .join(
                VerificationSession,
                VerificationSession.id == StepProgress.session_id,
            )
            .join(TierProfile, TierProfile.id == StepProgress.tier_profile_id)
            .where(
                VerificationSession.org_id == org_id,
                VerificationSession.created_at >= start,
            )
            .group_by(
                StepProgress.step_order,
                TierProfile.name,
                StepProgress.status,
            )
            .order_by(StepProgress.step_order)
        )
    ).all()

    steps: dict = {}
    for order, tier_name, status, count in step_rows:
        key = f"step_{order}"
        steps.setdefault(key, {"step_order": order, "tier_name": tier_name})
        steps[key][status] = count

    return {
        "period_days": days,
        "funnel": {
            "created": total,
            "started": started,
            "completed": completed,
            "approved": approved,
            "rejected": rejected,
            "drop_off_rate": (
                round((total - completed) / total * 100, 1) if total else 0
            ),
        },
        "by_step": list(steps.values()),
    }


@router.get("/stats/documents")
async def get_document_stats(
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Document processing statistics: types, quality, classification accuracy."""
    org_id = auth.org_id

    doc_rows = (
        await db.execute(
            select(
                DocumentArtifact.document_type,
                func.count().label("count"),
            )
            .join(
                VerificationSession,
                VerificationSession.id == DocumentArtifact.session_id,
            )
            .where(VerificationSession.org_id == org_id)
            .group_by(DocumentArtifact.document_type)
        )
    ).all()
    by_type = {row[0]: row[1] for row in doc_rows}

    total_docs = sum(by_type.values())

    bio_rows = (
        await db.execute(
            select(
                BiometricResult.check_type,
                BiometricResult.passed,
                func.count(),
                func.avg(BiometricResult.score),
            )
            .join(
                VerificationSession,
                VerificationSession.id == BiometricResult.session_id,
            )
            .where(VerificationSession.org_id == org_id)
            .group_by(BiometricResult.check_type, BiometricResult.passed)
        )
    ).all()

    biometrics: dict = {}
    for check_type, passed, count, avg_score in bio_rows:
        biometrics.setdefault(check_type, {"total": 0, "passed": 0, "failed": 0})
        biometrics[check_type]["total"] += count
        if passed:
            biometrics[check_type]["passed"] += count
        else:
            biometrics[check_type]["failed"] += count
        biometrics[check_type]["avg_score"] = (
            round(float(avg_score), 3) if avg_score else None
        )

    return {
        "total_documents": total_docs,
        "by_document_type": by_type,
        "biometrics": biometrics,
    }
