"""FastAPI dependency injection for authentication and authorization."""

from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, Request, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token, hash_api_key
from app.db.session import get_db
from app.models.organization import ApiKey, OrgUser


class AuthContext:
    """Unified auth context injected into route handlers."""

    def __init__(
        self,
        org_id: UUID,
        actor_id: UUID,
        actor_type: str,
        role: Optional[str] = None,
        scopes: Optional[list[str]] = None,
    ):
        self.org_id = org_id
        self.actor_id = actor_id
        self.actor_type = actor_type
        self.role = role
        self.scopes = scopes or []


async def _resolve_jwt(token: str, db: AsyncSession) -> AuthContext:
    try:
        payload = decode_token(token)
    except ValueError:
        raise UnauthorizedError("Invalid or expired token")

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")

    stmt = select(OrgUser).where(OrgUser.id == UUID(user_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found")
    if not user.email_verified:
        raise ForbiddenError("Email not verified")

    return AuthContext(
        org_id=user.org_id,
        actor_id=user.id,
        actor_type="user",
        role=user.role,
    )


async def _resolve_api_key(raw_key: str, db: AsyncSession) -> AuthContext:
    key_hash = hash_api_key(raw_key)
    stmt = select(ApiKey).where(
        ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True)
    )
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise UnauthorizedError("Invalid API key")

    from datetime import datetime, timezone
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.flush()

    return AuthContext(
        org_id=api_key.org_id,
        actor_id=api_key.id,
        actor_type="api_key",
        scopes=api_key.scopes or [],
    )


async def authenticate_websocket(websocket: WebSocket, db: AsyncSession) -> AuthContext:
    """Resolve JWT or API key from WebSocket query params (browser-friendly)."""
    api_key = websocket.query_params.get("api_key")
    token = websocket.query_params.get("token")
    if api_key:
        return await _resolve_api_key(api_key, db)
    if token:
        return await _resolve_jwt(token, db)
    raise UnauthorizedError("Missing api_key or token query parameter")


async def get_auth_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> AuthContext:
    """Resolve auth from either JWT Bearer token or X-API-Key header."""
    if x_api_key:
        return await _resolve_api_key(x_api_key, db)

    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        return await _resolve_jwt(token, db)

    raise UnauthorizedError("Missing authentication credentials")


async def require_jwt(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> AuthContext:
    """Require JWT authentication (dashboard routes)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("JWT Bearer token required")
    return await _resolve_jwt(authorization[7:], db)


def require_role(*roles: str):
    """Return a dependency that checks the user's role."""

    async def _check(auth: AuthContext = Depends(require_jwt)) -> AuthContext:
        if auth.role not in roles:
            raise ForbiddenError(
                f"Role '{auth.role}' not allowed; need one of {roles}"
            )
        return auth

    return _check


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
