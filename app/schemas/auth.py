from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from app.schemas.org import BrandingOut


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    org_name: str
    legal_name: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

    @field_validator("org_name")
    @classmethod
    def org_name_not_empty(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("Organization name must be at least 2 characters")
        return v.strip()


class RegisterResponse(BaseModel):
    org_id: UUID
    user_id: UUID
    message: str
    verification_email_sent: bool = False
    """Always False; verification is token-based (no outbound email)."""
    email_verify_token: Optional[str] = None
    """One-time token for POST /verify-email or open `email_verify_link`."""
    email_verify_otp: Optional[str] = None
    """Optional 6-digit code; same value stored for POST /verify-email with email+otp."""
    email_verify_link: Optional[str] = None
    """Convenience URL for the identity app verify page (includes email and token)."""


class VerifyEmailRequest(BaseModel):
    """Verify via `token` or `email` + 6-digit `otp` from the API registration/resend response."""

    token: Optional[str] = None
    email: Optional[EmailStr] = None
    otp: Optional[str] = None

    @model_validator(mode="after")
    def token_or_otp(self) -> "VerifyEmailRequest":
        t = (self.token or "").strip()
        if t:
            self.token = t
            return self
        raw_otp = (self.otp or "").strip().replace(" ", "")
        if self.email and raw_otp and len(raw_otp) == 6 and raw_otp.isdecimal():
            self.otp = raw_otp
            return self
        raise ValueError(
            "Provide `token` from the registration response (or verify link), or `email` plus the 6-digit `otp` from the response."
        )


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ResendVerificationResponse(BaseModel):
    detail: str
    email_verify_token: Optional[str] = None
    email_verify_otp: Optional[str] = None
    email_verify_link: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    role: str
    email_verified: bool
    org_name: str
    org_plan: str
    display_name: Optional[str] = None
    branding: Optional[BrandingOut] = None

    model_config = {"from_attributes": True}


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    display_name: Optional[str] = None

    @field_validator("token")
    @classmethod
    def token_strip(cls, v: str) -> str:
        t = (v or "").strip()
        if not t:
            raise ValueError("token is required")
        return t

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

    @field_validator("display_name")
    @classmethod
    def name_len(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        if len(s) > 255:
            raise ValueError("display_name too long")
        return s or None


class AcceptInviteResponse(BaseModel):
    user_id: UUID
    org_id: UUID
    message: str
