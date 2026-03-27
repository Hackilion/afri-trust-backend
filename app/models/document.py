import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from app.db.types import GUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class DocumentArtifact(Base):
    __tablename__ = "document_artifacts"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    session_id = Column(
        GUID,
        ForeignKey("verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_progress_id = Column(
        GUID,
        ForeignKey("step_progress.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type = Column(String(50), nullable=False)
    file_key = Column(String(1024), nullable=False)
    file_hash = Column(String(64), nullable=True)
    mime_type = Column(String(100), nullable=True)
    original_filename = Column(String(500), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session = relationship("VerificationSession", backref="documents")
    step_progress = relationship("StepProgress", backref="documents")
    extracted_identity = relationship(
        "ExtractedIdentity",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ExtractedIdentity(Base):
    __tablename__ = "extracted_identities"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    document_artifact_id = Column(
        GUID,
        ForeignKey("document_artifacts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    extracted_data = Column(JSON, nullable=False, default=dict)
    confidence_score = Column(Float, nullable=True)
    document_classification = Column(String(50), nullable=True)
    fraud_signals = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document = relationship("DocumentArtifact", back_populates="extracted_identity")
