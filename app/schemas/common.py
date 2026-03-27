import enum
from typing import Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CheckType(str, enum.Enum):
    EMAIL = "email"
    PHONE = "phone"
    SELFIE = "selfie"
    GOVERNMENT_ID = "government_id"
    FACE_MATCH = "face_match"
    LIVENESS = "liveness"
    ADDRESS_PROOF = "address_proof"
    PEP_SCREENING = "pep_screening"
    AML_SCREENING = "aml_screening"


class DocumentType(str, enum.Enum):
    PASSPORT = "passport"
    NATIONAL_ID = "national_id"
    DRIVERS_LICENSE = "drivers_license"
    VOTER_CARD = "voter_card"
    RESIDENCE_PERMIT = "residence_permit"
    ADDRESS_PROOF = "address_proof"
    OTHER = "other"


class AttributeDataType(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    ENUM = "enum"
    FILE = "file"


class WorkflowStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SessionStatus(str, enum.Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class SessionResult(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    VIEWER = "viewer"


class ActorType(str, enum.Enum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class StatusMessage(BaseModel):
    detail: str


class IDResponse(BaseModel):
    id: UUID
