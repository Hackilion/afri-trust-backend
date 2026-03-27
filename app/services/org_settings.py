"""Organisation JSON `settings` (branding, future keys)."""

from typing import Any, Optional

from app.models.organization import Organization
from app.schemas.org import BrandingOut, BrandingPatch


def org_settings_dict(org: Organization) -> dict[str, Any]:
    s = org.settings
    return s if isinstance(s, dict) else {}


def get_branding(org: Organization) -> BrandingOut:
    b = org_settings_dict(org).get("branding") or {}
    return BrandingOut(
        primary_color=str(b.get("primary_color") or "#6366f1"),
        accent_color=str(b.get("accent_color") or "#8b5cf6"),
        logo_url=str(b.get("logo_url") or ""),
        tagline=str(b.get("tagline") or ""),
    )


def apply_branding_patch(org: Organization, patch: BrandingPatch) -> None:
    s = org_settings_dict(org)
    br = dict(s.get("branding") or {})
    if patch.primary_color is not None:
        br["primary_color"] = patch.primary_color.strip() or "#6366f1"
    if patch.accent_color is not None:
        br["accent_color"] = patch.accent_color.strip() or "#8b5cf6"
    if patch.logo_url is not None:
        br["logo_url"] = patch.logo_url.strip()
    if patch.tagline is not None:
        br["tagline"] = patch.tagline.strip()[:500]
    s["branding"] = br
    org.settings = s
