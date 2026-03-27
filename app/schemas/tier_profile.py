from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.schemas.common import AttributeDataType, CheckType, DocumentType


class AttributeValidationRules(BaseModel):
    """Optional validation constraints per attribute data_type."""
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None


class AttributeDefinition(BaseModel):
    """Dynamic attribute definition — orgs define these per tier."""
    key: str
    label: str
    data_type: AttributeDataType
    required: bool = True
    description: Optional[str] = None
    options: Optional[list[str]] = None
    validation: Optional[AttributeValidationRules] = None

    @field_validator("options")
    @classmethod
    def options_required_for_enum(cls, v: Optional[list[str]], info) -> Optional[list[str]]:
        if info.data.get("data_type") == AttributeDataType.ENUM and not v:
            raise ValueError("options must be provided when data_type is 'enum'")
        return v

    @field_validator("key")
    @classmethod
    def key_must_be_identifier(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError("key must be a valid identifier (letters, digits, underscores)")
        return v


class TierProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    required_checks: list[CheckType]
    attribute_schema: list[AttributeDefinition]
    accepted_document_types: list[DocumentType] = []
    settings: dict[str, Any] = {}

    @field_validator("attribute_schema")
    @classmethod
    def unique_attribute_keys(cls, v: list[AttributeDefinition]) -> list[AttributeDefinition]:
        keys = [attr.key for attr in v]
        if len(keys) != len(set(keys)):
            raise ValueError("attribute_schema keys must be unique")
        return v


class TierProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    required_checks: Optional[list[CheckType]] = None
    attribute_schema: Optional[list[AttributeDefinition]] = None
    accepted_document_types: Optional[list[DocumentType]] = None
    settings: Optional[dict[str, Any]] = None


class TierProfileOut(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    description: Optional[str]
    required_checks: list[str]
    attribute_schema: list[dict[str, Any]]
    accepted_document_types: list[str]
    settings: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CheckCatalogueOut(BaseModel):
    check_types: list[dict[str, str]]
    document_types: list[dict[str, str]]
    attribute_data_types: list[dict[str, str]]
