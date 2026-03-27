import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_verification_token
from app.models.consent import ConsentGrant, VerificationToken


def _utcnow() -> datetime:
    return datetime.utcnow()


async def create_consent(
    db: AsyncSession,
    *,
    applicant_id: UUID,
    org_id: UUID,
    session_id: UUID,
    granted_attributes: list[str],
    expires_in_days: int = 30,
) -> tuple[ConsentGrant, str]:
    """Create a consent grant and return (grant, raw_token)."""
    expires_at = _utcnow() + timedelta(days=expires_in_days)

    grant = ConsentGrant(
        applicant_id=applicant_id,
        org_id=org_id,
        session_id=session_id,
        granted_attributes=granted_attributes,
        expires_at=expires_at,
    )
    db.add(grant)
    await db.flush()

    raw_token = generate_verification_token()
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    vt = VerificationToken(
        consent_grant_id=grant.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(vt)
    await db.flush()

    return grant, raw_token


async def validate_token(
    db: AsyncSession, raw_token: str
) -> Optional[ConsentGrant]:
    """Validate a verification token and return associated consent grant."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    stmt = select(VerificationToken).where(
        VerificationToken.token_hash == token_hash
    )
    result = await db.execute(stmt)
    vt = result.scalar_one_or_none()

    if not vt:
        return None

    now = _utcnow()
    expires = vt.expires_at.replace(tzinfo=None) if vt.expires_at and vt.expires_at.tzinfo else vt.expires_at
    if expires and expires < now:
        return None

    stmt2 = select(ConsentGrant).where(ConsentGrant.id == vt.consent_grant_id)
    result2 = await db.execute(stmt2)
    grant = result2.scalar_one_or_none()

    if not grant:
        return None
    grant_expires = grant.expires_at.replace(tzinfo=None) if grant.expires_at and grant.expires_at.tzinfo else grant.expires_at
    if grant.revoked_at or (grant_expires and grant_expires < now):
        return None

    vt.used_at = now
    await db.flush()
    return grant
