import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class TierProfile(Base):
    """Org-defined verification tier with dynamic attribute schema.

    `attribute_schema` stores a list of attribute definitions, each being:
    {
        "key": "full_name",
        "label": "Full Name",
        "data_type": "string",   # string | number | date | boolean | enum | file
        "required": true,
        "description": "Applicant's full legal name",
        "options": null,         # populated for enum type: ["male","female","other"]
        "validation": {          # optional per-type rules
            "min_length": 2,
            "max_length": 200,
            "pattern": "^[A-Za-z ]+$"
        }
    }
    """

    __tablename__ = "tier_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    required_checks = Column(JSON, nullable=False, default=list)
    attribute_schema = Column(JSON, nullable=False, default=list)
    accepted_document_types = Column(JSON, nullable=False, default=list)
    settings = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization = relationship("Organization", backref="tier_profiles")

    __table_args__ = (
        Index("ix_tier_profiles_org_active", "org_id", "is_active"),
    )
