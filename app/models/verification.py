import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class VerificationSession(Base):
    __tablename__ = "verification_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    applicant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applicants.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workflow_version = Column(Integer, nullable=False)
    current_step_order = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="created")
    result = Column(String(20), nullable=False, default="pending")
    result_details = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    applicant = relationship("Applicant", back_populates="verification_sessions")
    workflow = relationship("Workflow")
    organization = relationship("Organization")
    step_progress = relationship(
        "StepProgress",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="StepProgress.step_order",
    )

    __table_args__ = (
        Index("ix_sessions_org_status", "org_id", "status"),
        Index("ix_sessions_org_created", "org_id", "created_at"),
        Index("ix_sessions_applicant", "applicant_id"),
    )


class StepProgress(Base):
    __tablename__ = "step_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_step_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_steps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tier_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tier_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_order = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    checks_completed = Column(JSON, nullable=False, default=dict)
    attributes_collected = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    session = relationship("VerificationSession", back_populates="step_progress")
    workflow_step = relationship("WorkflowStep")
    tier_profile = relationship("TierProfile")

    __table_args__ = (
        UniqueConstraint(
            "session_id", "workflow_step_id", name="uq_step_progress_session_step"
        ),
    )
