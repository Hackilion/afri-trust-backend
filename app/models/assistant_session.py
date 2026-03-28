import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.types import GUID, JSON


class AssistantChatSession(Base):
    """Per-user assistant conversation persisted for the dashboard (JWT users only)."""

    __tablename__ = "assistant_chat_sessions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    org_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        GUID,
        ForeignKey("org_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    preview = Column(String(200), nullable=False, default="")
    state = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization = relationship("Organization", backref="assistant_sessions")
    user = relationship("OrgUser", backref="assistant_sessions")

    __table_args__ = (
        Index("ix_assistant_sessions_org_user_updated", "org_id", "user_id", "updated_at"),
    )
