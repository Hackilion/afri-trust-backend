"""Dashboard assistant: proxy to OpenRouter (OpenAI-compatible API)."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import AuthContext, require_jwt
from app.core.config import settings
from app.schemas.assistant import AssistantChatRequest

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["Assistant"])


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
