import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_email_otp,
    generate_email_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.organization import OrgUser, Organization
from app.schemas.auth import (
    AcceptInviteRequest,
    AcceptInviteResponse,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    UserProfile,
    VerifyEmailRequest,
)
from app.schemas.common import StatusMessage
from app.api.deps import require_jwt, AuthContext
from app.services.org_settings import get_branding

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


def _email_verify_link(email: str, token: str) -> str:
    base = settings.PUBLIC_APP_URL.rstrip("/")
    return f"{base}/verify-email?email={quote(email, safe='')}&token={quote(token, safe='')}"


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(OrgUser).where(OrgUser.email == body.email)
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    org = Organization(
        name=body.org_name,
        legal_name=body.legal_name,
        country=body.country,
        industry=body.industry,
    )
    db.add(org)
    await db.flush()

    token = generate_email_token()
    otp = generate_email_otp()
    otp_expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.EMAIL_VERIFY_OTP_TTL_MINUTES
    )
    user = OrgUser(
        org_id=org.id,
        email=body.email,
        password_hash=hash_password(body.password),
        role="owner",
        email_verify_token=token,
        email_verify_otp=otp,
        email_verify_otp_expires_at=otp_expires,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("Email already registered")

    return RegisterResponse(
        org_id=org.id,
        user_id=user.id,
        verification_email_sent=False,
        email_verify_token=token,
        email_verify_otp=otp,
        email_verify_link=_email_verify_link(user.email, token),
        message="Registration successful. Use the verification link or token below (or email + 6-digit code) to verify.",
    )


@router.post("/accept-invite", response_model=AcceptInviteResponse)
async def accept_invite(body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    """Complete an organisation invite: set password and activate the account."""
    stmt = select(OrgUser).where(OrgUser.invite_token == body.token)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise BadRequestError("Invalid or expired invite")

    now = datetime.now(timezone.utc)
    exp = user.invite_expires_at
    if exp is None:
        raise BadRequestError("Invalid or expired invite")
    exp_aware = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
    if now > exp_aware:
        raise BadRequestError("Invite has expired — ask an admin to send a new invitation")

    user.password_hash = hash_password(body.password)
    user.email_verified = True
    user.invite_token = None
    user.invite_expires_at = None
    user.email_verify_token = None
    user.email_verify_otp = None
    user.email_verify_otp_expires_at = None
    if body.display_name:
        user.display_name = body.display_name
    await db.flush()

    return AcceptInviteResponse(
        user_id=user.id,
        org_id=user.org_id,
        message="Account activated. You can sign in with your email and password.",
    )


@router.post("/verify-email", response_model=StatusMessage)
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    if body.token:
        stmt = select(OrgUser).where(OrgUser.email_verify_token == body.token)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise BadRequestError("Invalid verification token")
    else:
        stmt = select(OrgUser).where(OrgUser.email == body.email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise BadRequestError("Invalid email or verification code")
        if user.email_verified:
            raise BadRequestError("This email is already verified")
        if (user.email_verify_otp or "") != body.otp:
            raise BadRequestError("Invalid email or verification code")
        exp = user.email_verify_otp_expires_at
        if exp is None:
            raise BadRequestError("Verification code expired or invalid")
        now = datetime.now(timezone.utc)
        exp_aware = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
        if now > exp_aware:
            raise BadRequestError(
                "Verification code expired. Request new credentials via POST /resend-verification."
            )

    user.email_verified = True
    user.email_verify_token = None
    user.email_verify_otp = None
    user.email_verify_otp_expires_at = None
    await db.flush()
    return StatusMessage(detail="Email verified successfully")


@router.post("/resend-verification", response_model=ResendVerificationResponse)
async def resend_verification(
    body: ResendVerificationRequest, db: AsyncSession = Depends(get_db)
):
    """Issue new verification token and OTP (no outbound email)."""
    generic_detail = (
        "If an account exists for this email and is not yet verified, new verification "
        "credentials are included in this response."
    )
    stmt = select(OrgUser).where(OrgUser.email == body.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or user.email_verified:
        return ResendVerificationResponse(detail=generic_detail)

    token = generate_email_token()
    otp = generate_email_otp()
    user.email_verify_token = token
    user.email_verify_otp = otp
    user.email_verify_otp_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.EMAIL_VERIFY_OTP_TTL_MINUTES
    )
    await db.flush()

    return ResendVerificationResponse(
        detail="Use the verification link, token, or 6-digit code below.",
        email_verify_token=token,
        email_verify_otp=otp,
        email_verify_link=_email_verify_link(user.email, token),
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(OrgUser).where(OrgUser.email == body.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")
    if not user.email_verified:
        raise UnauthorizedError("Email not verified")

    data = {"sub": str(user.id), "org_id": str(user.org_id), "role": user.role}
    return LoginResponse(
        access_token=create_access_token(data),
        refresh_token=create_refresh_token(data),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except ValueError:
        raise UnauthorizedError("Invalid refresh token")

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid token type")

    stmt = select(OrgUser).where(OrgUser.id == payload["sub"])
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")

    data = {"sub": str(user.id), "org_id": str(user.org_id), "role": user.role}
    return RefreshResponse(access_token=create_access_token(data))


@router.get("/me", response_model=UserProfile)
async def me(
    auth: AuthContext = Depends(require_jwt),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OrgUser).where(OrgUser.id == auth.actor_id)
    result = await db.execute(stmt)
    user = result.scalar_one()

    org_stmt = select(Organization).where(Organization.id == auth.org_id)
    org_result = await db.execute(org_stmt)
    org = org_result.scalar_one()

    b = get_branding(org)
    return UserProfile(
        id=user.id,
        org_id=user.org_id,
        email=user.email,
        role=user.role,
        email_verified=user.email_verified,
        org_name=org.name,
        org_plan=org.plan,
        display_name=user.display_name,
        branding=b,
    )
