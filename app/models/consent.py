import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from app.db.types import GUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class ConsentGrant(Base):
    __tablename__ = "consent_grants"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    applicant_id = Column(
        GUID,
        ForeignKey("applicants.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id = Column(
        GUID,
        ForeignKey("verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    granted_attributes = Column(JSON, nullable=False, default=list)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    applicant = relationship("Applicant", backref="consent_grants")
    session = relationship("VerificationSession", backref="consent_grants")


class VerificationToken(Base):
    __tablename__ = "verification_tokens"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    consent_grant_id = Column(
        GUID,
        ForeignKey("consent_grants.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    consent_grant = relationship("ConsentGrant", backref="tokens")
