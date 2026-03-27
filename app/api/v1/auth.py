import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_email_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.organization import OrgUser, Organization
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    UserProfile,
    VerifyEmailRequest,
)
from app.schemas.common import StatusMessage
from app.api.deps import require_jwt, AuthContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


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
    user = OrgUser(
        org_id=org.id,
        email=body.email,
        password_hash=hash_password(body.password),
        role="owner",
        email_verify_token=token,
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
        email_verify_token=token,
        message="Registration successful. Use the email_verify_token to verify your email.",
    )


@router.post("/verify-email", response_model=StatusMessage)
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(OrgUser).where(OrgUser.email_verify_token == body.token)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise BadRequestError("Invalid verification token")

    user.email_verified = True
    user.email_verify_token = None
    await db.flush()
    return StatusMessage(detail="Email verified successfully")


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

    return UserProfile(
        id=user.id,
        org_id=user.org_id,
        email=user.email,
        role=user.role,
        email_verified=user.email_verified,
        org_name=org.name,
        org_plan=org.plan,
    )
