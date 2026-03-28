"""Organisation workspace: team members and appearance settings."""

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_client_ip, require_jwt, require_role
from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import generate_email_token, hash_password
from app.db.session import get_db
from app.models.organization import OrgUser, Organization
from app.schemas.common import StatusMessage
from app.schemas.org import (
    OrgSettingsOut,
    OrgSettingsPatch,
    OrgUserInvite,
    OrgUserInviteResponse,
    OrgUserOut,
    OrgUserRolePatch,
    OrgUserSelfPatch,
)
from app.services import audit_service
from app.services.org_settings import apply_branding_patch, get_branding

router = APIRouter(prefix="/org", tags=["Organisation"])


def _join_link(token: str) -> str:
    base = settings.PUBLIC_APP_URL.rstrip("/")
    return f"{base}/accept-invite?token={quote(token, safe='')}"


def _user_out(u: OrgUser) -> OrgUserOut:
    invite_pending = bool(
        not u.email_verified and u.invite_token and u.invite_expires_at
    )
    now = datetime.now(timezone.utc)
    if invite_pending and u.invite_expires_at:
        exp = u.invite_expires_at
        exp_aware = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
        if now > exp_aware:
            invite_pending = False
    return OrgUserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        email_verified=u.email_verified,
        invite_pending=invite_pending,
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


@router.get("/settings", response_model=OrgSettingsOut)
async def get_org_settings(
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Organization, auth.org_id)
    if not org:
        raise NotFoundError("Organisation not found")
    return OrgSettingsOut(
        org_id=org.id,
        org_name=org.name,
        branding=get_branding(org),
    )


@router.patch("/settings", response_model=OrgSettingsOut)
async def patch_org_settings(
    body: OrgSettingsPatch,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Organization, auth.org_id)
    if not org:
        raise NotFoundError("Organisation not found")
    if body.branding is not None:
        apply_branding_patch(org, body.branding)
    await db.flush()
    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="org.settings.updated",
        resource_type="organization",
        resource_id=org.id,
        ip_address=get_client_ip(request),
        changes={"branding": body.branding.model_dump(exclude_none=True) if body.branding else {}},
    )
    return OrgSettingsOut(
        org_id=org.id,
        org_name=org.name,
        branding=get_branding(org),
    )


@router.get("/users", response_model=list[OrgUserOut])
async def list_org_users(
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(OrgUser)
        .where(OrgUser.org_id == auth.org_id)
        .order_by(OrgUser.created_at.asc())
    )
    result = await db.execute(stmt)
    return [_user_out(u) for u in result.scalars().all()]


@router.patch("/users/me", response_model=OrgUserOut)
async def patch_me_profile(
    body: OrgUserSelfPatch,
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(OrgUser, auth.actor_id)
    if not u or u.org_id != auth.org_id:
        raise NotFoundError("User not found")
    if body.display_name is not None:
        u.display_name = body.display_name
    await db.flush()
    return _user_out(u)


@router.post("/users/invite", response_model=OrgUserInviteResponse, status_code=201)
async def invite_org_user(
    body: OrgUserInvite,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    email_norm = body.email.strip().lower()
    existing = await db.execute(select(OrgUser).where(OrgUser.email == email_norm))
    if existing.scalar_one_or_none():
        raise ConflictError("This email is already registered or invited")

    raw_pw = secrets.token_urlsafe(48)
    token = generate_email_token()
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    user = OrgUser(
        org_id=auth.org_id,
        email=email_norm,
        password_hash=hash_password(raw_pw),
        role=body.role,
        email_verified=False,
        invite_token=token,
        invite_expires_at=expires,
    )
    db.add(user)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="org.user.invited",
        resource_type="org_user",
        resource_id=user.id,
        ip_address=get_client_ip(request),
        changes={"email": email_norm, "role": body.role},
    )

    return OrgUserInviteResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        invite_token=token,
        invite_expires_at=expires,
        join_link=_join_link(token),
    )


@router.patch("/users/{user_id}", response_model=OrgUserOut)
async def patch_org_user_role(
    user_id: UUID,
    body: OrgUserRolePatch,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(OrgUser, user_id)
    if not u or u.org_id != auth.org_id:
        raise NotFoundError("User not found")

    if u.role == "owner" and body.role != "owner":
        cnt = (
            await db.execute(
                select(func.count())
                .select_from(OrgUser)
                .where(
                    OrgUser.org_id == auth.org_id,
                    OrgUser.role == "owner",
                )
            )
        ).scalar() or 0
        if cnt <= 1:
            raise BadRequestError("Cannot change role of the only organisation owner")

    if body.role == "owner" and u.role != "owner":
        raise ForbiddenError("Promoting to owner is not supported via API")

    old = u.role
    u.role = body.role
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="org.user.role_changed",
        resource_type="org_user",
        resource_id=u.id,
        ip_address=get_client_ip(request),
        changes={"before": old, "after": body.role},
    )
    return _user_out(u)


@router.delete("/users/{user_id}", response_model=StatusMessage)
async def remove_org_user(
    user_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    if user_id == auth.actor_id:
        raise BadRequestError("You cannot remove yourself")

    u = await db.get(OrgUser, user_id)
    if not u or u.org_id != auth.org_id:
        raise NotFoundError("User not found")

    if u.role == "owner":
        cnt = (
            await db.execute(
                select(func.count())
                .select_from(OrgUser)
                .where(
                    OrgUser.org_id == auth.org_id,
                    OrgUser.role == "owner",
                )
            )
        ).scalar() or 0
        if cnt <= 1:
            raise BadRequestError("Cannot remove the only organisation owner")

    uid = u.id
    await db.delete(u)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="org.user.removed",
        resource_type="org_user",
        resource_id=uid,
        ip_address=get_client_ip(request),
    )
    return StatusMessage(detail="User removed from organisation")
