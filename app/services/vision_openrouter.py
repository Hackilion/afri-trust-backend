"""OpenRouter vision API — shared JSON extraction for documents and liveness (server-side key)."""

import base64
import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings

_log = logging.getLogger(__name__)

MAX_VISION_BYTES = 4 * 1024 * 1024


def openrouter_headers() -> dict[str, str]:
    key = (settings.OPENROUTER_API_KEY or "").strip()
    if not key:
        return {}
    headers: dict[str, str] = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    referer = (settings.OPENROUTER_HTTP_REFERER or settings.PUBLIC_APP_URL or "").strip()
    if referer:
        headers["Referer"] = referer
    headers["X-Title"] = settings.PROJECT_NAME
    return headers


def vision_model_name() -> str:
    v = (settings.OPENROUTER_VISION_MODEL or "").strip()
    if v:
        return v
    return (settings.OPENROUTER_MODEL or "openai/gpt-4o-mini").strip()


def parse_json_from_model_text(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {"raw_text": cleaned[:2000]}


def _prepare_image_bytes(image_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    """Downscale/compress if over OpenRouter-friendly size."""
    ct = (content_type or "image/jpeg").split(";")[0].strip().lower()
    if ct not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"):
        ct = "image/jpeg"
    if len(image_bytes) <= MAX_VISION_BYTES:
        return image_bytes, ct
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        img.thumbnail((2048, 2048))
        out = BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        _log.warning("Could not downscale image for vision; truncating not supported")
        return image_bytes[:MAX_VISION_BYTES], ct


async def vision_chat_json(
    *,
    system: str,
    user_text: str,
    image_bytes: bytes,
    content_type: str,
    max_tokens: int = 800,
    timeout: float = 90.0,
) -> dict[str, Any]:
    key = (settings.OPENROUTER_API_KEY or "").strip()
    if not key:
        return {}

    img_bytes, ct = _prepare_image_bytes(image_bytes, content_type)
    b64 = base64.standard_b64encode(img_bytes).decode("ascii")
    data_url = f"data:{ct};base64,{b64}"

    model = vision_model_name()
    base = (settings.OPENROUTER_BASE_URL or "").strip().rstrip("/") or "https://openrouter.ai/api/v1"
    url = f"{base}/chat/completions"

    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            r = await client.post(url, headers=openrouter_headers(), json=payload)
    except httpx.RequestError as e:
        _log.warning("OpenRouter vision request failed: %s", e)
        return {}

    try:
        data = r.json()
    except Exception:
        return {}

    if not r.is_success:
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message", r.text) if isinstance(err, dict) else r.text
        _log.warning("OpenRouter vision error %s: %s", r.status_code, msg)
        return {}

    text = ""
    try:
        choices = data.get("choices") or []
        if choices:
            msg0 = choices[0].get("message") or {}
            text = (msg0.get("content") or "").strip()
    except Exception:
        pass

    return parse_json_from_model_text(text)


async def extract_identity_from_document_image(
    image_bytes: bytes,
    content_type: str,
    declared_document_type: str,
) -> dict[str, Any]:
    """Vision OCR + structured fields; `declared_document_type` from upload (passport, national_id, …)."""
    doc_hint = (declared_document_type or "identity_document").strip()
    system = (
        f"The image is an identity document the user submitted as type: {doc_hint}. "
        "Prioritize fields relevant to that category (e.g. passport: MRZ/names/passport number; "
        "national_id: national ID number; drivers_license: license number and class; "
        "address_proof: address lines). "
        "Reply with a single JSON object only, no markdown. Keys (omit unknown): full_name, given_name, "
        "family_name, document_number, date_of_birth, expiry_date, nationality, document_type_guess, "
        "issuing_country, address_line. Use ISO dates YYYY-MM-DD when possible. "
        "document_type_guess one of: passport, national_id, drivers_license, voter_card, residence_permit, address_proof, other. "
        "Include extraction_confidence (number 0.0-1.0) for how confident you are in the read."
    )
    user = "Extract all readable identity-related fields from this document image as JSON."
    return await vision_chat_json(
        system=system,
        user_text=user,
        image_bytes=image_bytes,
        content_type=content_type,
        max_tokens=900,
    )


async def assess_selfie_liveness_vision(
    image_bytes: bytes,
    content_type: str,
) -> dict[str, Any]:
    """LLM vision assessment for presentation-attack resistance (complements OpenCV heuristics)."""
    system = (
        "You evaluate a single selfie for identity verification liveness. "
        "Reject obvious non-live cases: photo of a printed photo, phone/laptop screen showing a face, "
        "mask covering identity, extreme darkness, or no human face. "
        "Accept normal selfies with one visible face. "
        "Reply with one JSON object only, no markdown: "
        '{"live_likely": true or false, "confidence": number from 0 to 1, "reasons": ["brief reason"]}'
    )
    user = "Does this image show a live person suitable for liveness verification?"
    return await vision_chat_json(
        system=system,
        user_text=user,
        image_bytes=image_bytes,
        content_type=content_type,
        max_tokens=400,
    )
