"""Tenant slug helpers (TENANT-ONBOARD)."""
from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_DASH_RE = re.compile(r"-{2,}")


def slugify_name(name: str, *, max_length: int = 64) -> str:
    """Lowercase slug from a display name: only ``[a-z0-9-]``, collapsed dashes."""
    raw = (name or "").strip().lower().replace("_", "-").replace(" ", "-")
    slug = _SLUG_RE.sub("-", raw)
    slug = _DASH_RE.sub("-", slug).strip("-")
    if not slug:
        slug = "workspace"
    return slug[:max_length].rstrip("-") or "workspace"


def is_valid_slug(slug: str) -> bool:
    """True when slug is non-empty, lowercase, and matches ``[a-z0-9-]+`` (no leading/trailing dash)."""
    if not slug or len(slug) > 64:
        return False
    if slug != slug.lower():
        return False
    if slug.startswith("-") or slug.endswith("-"):
        return False
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug))
