import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from app.db.types import GUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class BiometricResult(Base):
    __tablename__ = "biometric_results"

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
    check_type = Column(String(30), nullable=False)
    passed = Column(Boolean, nullable=False)
    score = Column(Float, nullable=True)
    model_version = Column(String(50), nullable=True)
    raw_response = Column(JSON, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session = relationship("VerificationSession", backref="biometric_results")
    step_progress = relationship("StepProgress", backref="biometric_results")
