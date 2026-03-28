"""SDK demo helpers: published workflow list (API key) and AI document preview (OpenRouter vision)."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.session import get_db
from app.models.workflow import Workflow
from app.services import vision_openrouter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/sdk-demo", tags=["SDK Demo"])

MAX_IMAGE_BYTES = 4 * 1024 * 1024


@router.get("/published-workflows")
async def list_published_workflows_for_demo(
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Minimal published workflow list for the hosted SDK demo (JWT or API key)."""
    stmt = (
        select(Workflow)
        .where(Workflow.org_id == auth.org_id, Workflow.status == "published")
        .options(selectinload(Workflow.steps))
        .order_by(Workflow.updated_at.desc())
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [
        {
            "id": str(wf.id),
            "name": wf.name,
            "short_code": wf.short_code,
            "step_count": len(wf.steps) if wf.steps else 0,
        }
        for wf in rows
    ]


@router.post("/vision-extract")
async def vision_extract_document(
    auth: AuthContext = Depends(get_auth_context),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """
    Extract likely identity fields from an ID document image using OpenRouter (vision).
    Uses server OPENROUTER_API_KEY; caller still must authenticate with org API key or JWT.
    """
    key = (settings.OPENROUTER_API_KEY or "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Document AI is not configured (set OPENROUTER_API_KEY on the server).",
        )

    raw = await file.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 4 MB).")

    content_type = (file.content_type or "image/jpeg").split(";")[0].strip().lower()
    if content_type not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported type; use JPEG, PNG, or WebP.",
        )

    extracted = await vision_openrouter.extract_identity_from_document_image(
        raw, content_type, "unknown"
    )
    if not extracted:
        raise HTTPException(
            status_code=502,
            detail="Document AI returned no data. Check OPENROUTER_API_KEY and model vision support.",
        )

    return {"ok": True, "extracted": extracted}
