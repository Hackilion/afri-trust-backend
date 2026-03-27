import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import WebhookDelivery, WebhookSubscription

logger = logging.getLogger(__name__)


def _sign_payload(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


async def dispatch_event(
    db: AsyncSession,
    *,
    org_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> list[UUID]:
    """Queue webhook deliveries for all matching subscriptions."""
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.org_id == org_id,
        WebhookSubscription.is_active.is_(True),
    )
    result = await db.execute(stmt)
    subscriptions = result.scalars().all()

    delivery_ids: list[UUID] = []
    now = datetime.now(timezone.utc)

    for sub in subscriptions:
        if event_type not in (sub.event_types or []):
            continue
        delivery = WebhookDelivery(
            subscription_id=sub.id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempts=0,
            next_attempt_at=now,
        )
        db.add(delivery)
        await db.flush()
        delivery_ids.append(delivery.id)

    return delivery_ids


async def process_pending_deliveries(db: AsyncSession, batch_size: int = 50) -> int:
    """Attempt delivery for pending webhooks. Returns count processed."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == "pending",
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(batch_size)
    )
    result = await db.execute(stmt)
    deliveries = result.scalars().all()

    processed = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for delivery in deliveries:
            sub_stmt = select(WebhookSubscription).where(
                WebhookSubscription.id == delivery.subscription_id
            )
            sub_result = await db.execute(sub_stmt)
            sub = sub_result.scalar_one_or_none()
            if not sub:
                delivery.status = "failed"
                processed += 1
                continue

            body = json.dumps(delivery.payload, default=str)
            signature = _sign_payload(body, sub.secret_hash)
            headers = {
                "Content-Type": "application/json",
                "X-AfriTrust-Signature": signature,
                "X-AfriTrust-Event": delivery.event_type,
            }

            try:
                resp = await client.post(sub.url, content=body, headers=headers)
                delivery.last_response_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    delivery.status = "delivered"
                else:
                    delivery.attempts += 1
                    if delivery.attempts >= 5:
                        delivery.status = "failed"
                    else:
                        delay = 2 ** delivery.attempts * 60
                        delivery.next_attempt_at = now + timedelta(seconds=delay)
            except Exception:
                logger.exception("Webhook delivery failed for %s", delivery.id)
                delivery.attempts += 1
                if delivery.attempts >= 5:
                    delivery.status = "failed"
                else:
                    delay = 2 ** delivery.attempts * 60
                    delivery.next_attempt_at = now + timedelta(seconds=delay)

            processed += 1

    await db.flush()
    return processed
