"""WebSocket stream for verification session status (integrator demos and live UIs)."""

import asyncio
import contextlib
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import authenticate_websocket
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.db.session import get_db
from app.models.verification import StepProgress, VerificationSession

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/verifications", tags=["Verifications"])

POLL_INTERVAL_SEC = 1.75


def _terminal(session: VerificationSession) -> bool:
    return session.status in ("approved", "rejected")


def _snapshot(session: VerificationSession) -> dict[str, Any]:
    steps = sorted(session.step_progress, key=lambda s: s.step_order)
    return {
        "type": "verification_snapshot",
        "session_id": str(session.id),
        "status": session.status,
        "result": session.result,
        "current_step_order": session.current_step_order,
        "workflow_id": str(session.workflow_id),
        "workflow_name": session.workflow.name if session.workflow else None,
        "workflow_version": session.workflow_version,
        "steps": [
            {
                "step_order": sp.step_order,
                "status": sp.status,
                "tier_profile_name": sp.tier_profile.name if sp.tier_profile else None,
            }
            for sp in steps
        ],
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


async def _load_session_for_stream(
    db: AsyncSession, session_id: UUID, org_id: UUID
) -> VerificationSession | None:
    stmt = (
        select(VerificationSession)
        .where(
            VerificationSession.id == session_id,
            VerificationSession.org_id == org_id,
        )
        .options(
            selectinload(VerificationSession.step_progress).selectinload(
                StepProgress.tier_profile
            ),
            selectinload(VerificationSession.workflow),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.websocket("/{session_id}/live")
async def verification_session_live(
    websocket: WebSocket,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        auth = await authenticate_websocket(websocket, db)
    except (UnauthorizedError, ForbiddenError) as exc:
        await websocket.close(code=1008, reason=str(exc.detail)[:123])
        return

    session = await _load_session_for_stream(db, session_id, auth.org_id)
    if session is None:
        await websocket.close(code=1008, reason="Verification session not found")
        return

    await websocket.accept()

    last_encoded: str | None = None
    try:
        while True:
            session = await _load_session_for_stream(db, session_id, auth.org_id)
            if session is None:
                await websocket.send_json(
                    {"type": "error", "detail": "Verification session not found"}
                )
                break

            payload = _snapshot(session)
            encoded = json.dumps(payload, sort_keys=True, default=str)
            if encoded != last_encoded:
                await websocket.send_json(payload)
                last_encoded = encoded

            if _terminal(session):
                await websocket.send_json({"type": "stream_end", "reason": "terminal"})
                break

            await asyncio.sleep(POLL_INTERVAL_SEC)
    except Exception:
        _log.exception("verification live WebSocket handler error")
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
