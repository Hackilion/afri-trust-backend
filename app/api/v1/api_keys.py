from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role, get_client_ip
from app.core.exceptions import NotFoundError
from app.core.security import generate_api_key
from app.db.session import get_db
from app.models.organization import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyOut
from app.schemas.common import StatusMessage
from app.services import audit_service
from fastapi import Request

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    raw_key, prefix, key_hash = generate_api_key()

    api_key = ApiKey(
        org_id=auth.org_id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=body.scopes,
    )
    db.add(api_key)
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="api_key.created",
        resource_type="api_key",
        resource_id=api_key.id,
        ip_address=get_client_ip(request),
    )

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        api_key=raw_key,
        key_prefix=prefix,
        scopes=api_key.scopes,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApiKey).where(ApiKey.org_id == auth.org_id).order_by(ApiKey.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/{key_id}", response_model=StatusMessage)
async def revoke_api_key(
    key_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_role("owner", "admin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == auth.org_id)
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise NotFoundError("API key not found")

    api_key.is_active = False
    await db.flush()

    await audit_service.log_event(
        db,
        org_id=auth.org_id,
        actor_type="user",
        actor_id=auth.actor_id,
        action="api_key.revoked",
        resource_type="api_key",
        resource_id=api_key.id,
        ip_address=get_client_ip(request),
    )

    return StatusMessage(detail="API key revoked")
