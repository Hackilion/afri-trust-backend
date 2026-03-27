import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_client_ip, require_jwt, require_role
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.webhook import WebhookDelivery, WebhookSubscription
from app.schemas.common import StatusMessage
from app.schemas.webhook import (
    WebhookCreate,
    WebhookCreateResponse,
    WebhookDeliveryOut,
    WebhookOut,
    WebhookUpdate,
)
from app.services import audit_service

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("", response_model=WebhookCreateResponse, status_code=201)
async def create_webhook(
    body: WebhookCreate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    signing_secret = secrets.token_urlsafe(32)

    sub = WebhookSubscription(
        org_id=auth.org_id,
        url=body.url,
        secret_hash=signing_secret,
        event_types=body.event_types,
    )
    db.add(sub)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="webhook.created",
        resource_type="webhook_subscription",
        resource_id=sub.id,
        ip_address=get_client_ip(request),
    )

    return WebhookCreateResponse(
        id=sub.id,
        url=sub.url,
        event_types=sub.event_types,
        signing_secret=signing_secret,
        created_at=sub.created_at,
    )


@router.get("", response_model=list[WebhookOut])
async def list_webhooks(
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.org_id == auth.org_id
    ).order_by(WebhookSubscription.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.put("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: UUID,
    body: WebhookUpdate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.id == webhook_id,
        WebhookSubscription.org_id == auth.org_id,
    )
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none()
    if not sub:
        raise NotFoundError("Webhook not found")

    if body.url is not None:
        sub.url = body.url
    if body.event_types is not None:
        sub.event_types = body.event_types
    if body.is_active is not None:
        sub.is_active = body.is_active

    await db.flush()
    return sub


@router.delete("/{webhook_id}", response_model=StatusMessage)
async def delete_webhook(
    webhook_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.id == webhook_id,
        WebhookSubscription.org_id == auth.org_id,
    )
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none()
    if not sub:
        raise NotFoundError("Webhook not found")

    await db.delete(sub)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="webhook.deleted",
        resource_type="webhook_subscription",
        resource_id=webhook_id,
        ip_address=get_client_ip(request),
    )

    return StatusMessage(detail="Webhook deleted")


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryOut])
async def list_deliveries(
    webhook_id: UUID,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    sub_stmt = select(WebhookSubscription).where(
        WebhookSubscription.id == webhook_id,
        WebhookSubscription.org_id == auth.org_id,
    )
    if not (await db.execute(sub_stmt)).scalar_one_or_none():
        raise NotFoundError("Webhook not found")

    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{webhook_id}/test", response_model=StatusMessage)
async def test_webhook(
    webhook_id: UUID,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    sub_stmt = select(WebhookSubscription).where(
        WebhookSubscription.id == webhook_id,
        WebhookSubscription.org_id == auth.org_id,
    )
    sub_result = await db.execute(sub_stmt)
    sub = sub_result.scalar_one_or_none()
    if not sub:
        raise NotFoundError("Webhook not found")

    delivery = WebhookDelivery(
        subscription_id=sub.id,
        event_type="test.ping",
        payload={"message": "This is a test event from AfriTrust"},
        status="pending",
    )
    db.add(delivery)
    await db.flush()

    return StatusMessage(detail="Test event queued for delivery")
