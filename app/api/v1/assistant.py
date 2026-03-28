"""Dashboard assistant: OpenRouter proxy + persisted chat sessions (JWT)."""

import logging
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_jwt
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.assistant_session import AssistantChatSession
from app.schemas.assistant import AssistantChatRequest
from app.schemas.assistant_sessions import (
    AssistantSessionCreate,
    AssistantSessionDetailOut,
    AssistantSessionOut,
    AssistantSessionPatch,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["Assistant"])

_EMPTY_STATE: dict[str, Any] = {
    "v": 2,
    "messages": [],
    "apiMessages": [],
    "toolLog": [],
    "suggestionChecks": {},
}


def _openrouter_chat_url() -> str:
    base = (settings.OPENROUTER_BASE_URL or "").strip().rstrip("/")
    if not base:
        base = "https://openrouter.ai/api/v1"
    return f"{base}/chat/completions"


def _openrouter_headers() -> dict[str, str]:
    key = (settings.OPENROUTER_API_KEY or "").strip()
    headers: dict[str, str] = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    referer = (settings.OPENROUTER_HTTP_REFERER or settings.PUBLIC_APP_URL or "").strip()
    if referer:
        headers["Referer"] = referer
    headers["X-Title"] = settings.PROJECT_NAME
    return headers


@router.get("/llm-status")
async def llm_status(_auth: AuthContext = Depends(require_jwt)) -> dict[str, Any]:
    key = (settings.OPENROUTER_API_KEY or "").strip()
    enabled = bool(key)
    return {"enabled": enabled}


@router.post("/llm-chat")
async def llm_chat(
    body: AssistantChatRequest,
    _auth: AuthContext = Depends(require_jwt),
) -> dict[str, Any]:
    key = (settings.OPENROUTER_API_KEY or "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Cloud assistant is not configured on the server.",
        )

    model = (body.model or settings.OPENROUTER_MODEL or "").strip()
    if not model:
        raise HTTPException(
            status_code=503,
            detail="Cloud assistant is not fully configured on the server.",
        )

    payload: dict[str, Any] = {
        "model": model,
        "messages": body.messages,
        "temperature": body.temperature,
    }
    if body.tools is not None:
        payload["tools"] = body.tools
    if body.tool_choice is not None:
        payload["tool_choice"] = body.tool_choice

    url = _openrouter_chat_url()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            r = await client.post(
                url,
                headers=_openrouter_headers(),
                json=payload,
            )
    except httpx.RequestError as e:
        _log.warning("OpenRouter request failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Could not reach the cloud assistant service.",
        ) from e

    try:
        data = r.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="The cloud assistant returned an invalid response.",
        )

    if r.is_success:
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "model"}
        return data

    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        msg = err.get("message", r.text)
    else:
        msg = r.text or r.reason_phrase
    _log.warning("OpenRouter error %s: %s", r.status_code, msg)
    raise HTTPException(
        status_code=502,
        detail="The cloud assistant is temporarily unavailable. Please try again.",
    )


@router.get("/sessions", response_model=list[AssistantSessionOut])
async def list_assistant_sessions(
    _auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
    limit: int = 30,
) -> list[AssistantSessionOut]:
    lim = min(max(limit, 1), 50)
    stmt = (
        select(AssistantChatSession)
        .where(
            AssistantChatSession.org_id == _auth.org_id,
            AssistantChatSession.user_id == _auth.actor_id,
        )
        .order_by(AssistantChatSession.updated_at.desc())
        .limit(lim)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [AssistantSessionOut.model_validate(r) for r in rows]


@router.post(
    "/sessions",
    response_model=AssistantSessionDetailOut,
    status_code=201,
)
async def create_assistant_session(
    body: AssistantSessionCreate,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
) -> AssistantSessionDetailOut:
    row = AssistantChatSession(
        org_id=auth.org_id,
        user_id=auth.actor_id,
        preview=(body.preview or "")[:200],
        state=dict(_EMPTY_STATE),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    st = row.state if isinstance(row.state, dict) else dict(_EMPTY_STATE)
    return AssistantSessionDetailOut(
        id=row.id,
        preview=row.preview or "",
        state=st,
        updated_at=row.updated_at,
    )


@router.get("/sessions/{session_id}", response_model=AssistantSessionDetailOut)
async def get_assistant_session(
    session_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
) -> AssistantSessionDetailOut:
    stmt = select(AssistantChatSession).where(
        AssistantChatSession.id == session_id,
        AssistantChatSession.org_id == auth.org_id,
        AssistantChatSession.user_id == auth.actor_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("Session not found")
    st = row.state if isinstance(row.state, dict) else {}
    return AssistantSessionDetailOut(
        id=row.id,
        preview=row.preview or "",
        state=st,
        updated_at=row.updated_at,
    )


@router.patch("/sessions/{session_id}", response_model=AssistantSessionDetailOut)
async def patch_assistant_session(
    session_id: UUID,
    body: AssistantSessionPatch,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
) -> AssistantSessionDetailOut:
    stmt = select(AssistantChatSession).where(
        AssistantChatSession.id == session_id,
        AssistantChatSession.org_id == auth.org_id,
        AssistantChatSession.user_id == auth.actor_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("Session not found")
    if body.preview is not None:
        row.preview = body.preview[:200]
    if body.state is not None:
        row.state = body.state
    await db.commit()
    await db.refresh(row)
    st = row.state if isinstance(row.state, dict) else {}
    return AssistantSessionDetailOut(
        id=row.id,
        preview=row.preview or "",
        state=st,
        updated_at=row.updated_at,
    )


@router.delete("/sessions/{session_id}")
async def delete_assistant_session(
    session_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    stmt = select(AssistantChatSession).where(
        AssistantChatSession.id == session_id,
        AssistantChatSession.org_id == auth.org_id,
        AssistantChatSession.user_id == auth.actor_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("Session not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
