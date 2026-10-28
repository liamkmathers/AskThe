"""Deterministic IDs.

Derived records get IDs computed from their inputs, so rebuilding from raw files
produces the same IDs and links between records survive a rebuild.
"""

import re
import unicodedata


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if not slug:
        raise ValueError(f"cannot make a slug from {text!r}")
    return slug


def video_id(creator_slug: str, platform_id: str) -> str:
    return f"{creator_slug}:{platform_id}"


def segment_id(video_id: str, index: int) -> str:
    return f"{video_id}:s{index:04d}"


def claim_id(video_id: str, index: int) -> str:
    return f"{video_id}:c{index:04d}"


def entity_id(creator_slug: str, canonical_name: str) -> str:
    return f"{creator_slug}:e:{slugify(canonical_name)}"


def version_id(entity_id: str, label: str) -> str:
    return f"{entity_id}:v:{slugify(label)}"
