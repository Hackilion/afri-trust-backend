import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from app.db.types import GUID, JSON
from sqlalchemy.sql import func

from app.db.base import Base


class AuditLog(Base):
    """Append-only audit trail. No UPDATE or DELETE operations allowed."""

    __tablename__ = "audit_logs"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    org_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type = Column(String(20), nullable=False)
    actor_id = Column(GUID, nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(GUID, nullable=True)
    ip_address = Column(String(45), nullable=True)
    changes = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )
