import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from app.db.types import GUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Applicant(Base):
    __tablename__ = "applicants"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    org_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    full_name = Column(String(500), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization = relationship("Organization", backref="applicants")
    verification_sessions = relationship(
        "VerificationSession", back_populates="applicant", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "external_id", name="uq_applicant_org_external"),
        Index("ix_applicants_org_created", "org_id", "created_at"),
        Index("ix_applicants_email", "email"),
    )
