from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class BrandingOut(BaseModel):
    primary_color: str = "#6366f1"
    accent_color: str = "#8b5cf6"
    logo_url: str = ""
    tagline: str = ""


class BrandingPatch(BaseModel):
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    logo_url: Optional[str] = None
    tagline: Optional[str] = None


class OrgSettingsOut(BaseModel):
    org_id: UUID
    org_name: str
    branding: BrandingOut


class OrgSettingsPatch(BaseModel):
    branding: Optional[BrandingPatch] = None


class OrgUserOut(BaseModel):
    id: UUID
    email: str
    display_name: Optional[str] = None
    role: str
    email_verified: bool
    invite_pending: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrgUserInvite(BaseModel):
    email: EmailStr
    role: str = Field(..., description="admin, reviewer, or viewer")

    @field_validator("role")
    @classmethod
    def role_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("admin", "reviewer", "viewer"):
            raise ValueError("role must be admin, reviewer, or viewer")
        return v


class OrgUserInviteResponse(BaseModel):
    user_id: UUID
    email: str
    role: str
    invite_token: str
    invite_expires_at: datetime
    join_link: str


class OrgUserRolePatch(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("admin", "reviewer", "viewer", "owner"):
            raise ValueError("role must be owner, admin, reviewer, or viewer")
        return v


class OrgUserSelfPatch(BaseModel):
    display_name: Optional[str] = Field(None, max_length=255)

    @field_validator("display_name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        return s or None
