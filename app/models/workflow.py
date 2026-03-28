import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from app.db.types import GUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    org_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization = relationship("Organization", backref="workflows")
    steps = relationship(
        "WorkflowStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.step_order",
    )

    short_code = Column(String(6), nullable=False)

    __table_args__ = (
        Index("ix_workflows_org_status", "org_id", "status"),
        UniqueConstraint("org_id", "short_code", name="uq_workflows_org_short_code"),
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    workflow_id = Column(
        GUID,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    tier_profile_id = Column(
        GUID,
        ForeignKey("tier_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_order = Column(Integer, nullable=False)
    is_optional = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workflow = relationship("Workflow", back_populates="steps")
    tier_profile = relationship("TierProfile")

    __table_args__ = (
        UniqueConstraint("workflow_id", "step_order", name="uq_workflow_step_order"),
    )
