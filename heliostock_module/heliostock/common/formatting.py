from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

import pandas as pd


def numeric_or_none(value: Any) -> float | None:
    """Return a finite float or None for missing/non-numeric values."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric) or not math.isfinite(numeric):
        return None
    return numeric


def format_number(value: Any, digits: int = 0, suffix: str = "") -> str:
    numeric = numeric_or_none(value)
    if numeric is None:
        return "n.d."
    formatted = f"{numeric:,.{digits}f}".replace(",", " ")
    return f"{formatted} {suffix}".strip()


def format_mwh_from_kwh(value: Any, digits: int = 0) -> str:
    numeric = numeric_or_none(value)
    if numeric is None:
        return "n.d."
    return format_number(numeric / 1000.0, digits, "MWh")


def format_percent(value: Any, digits: int = 0) -> str:
    return format_number(value, digits, "%")


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def safe_slug(text: str, *, fallback: str = "projet", max_length: int = 80) -> str:
    """ASCII slug safe for filenames and later database keys."""
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9_.-]+", "-", ascii_text).strip("._-")
    return slug[:max_length] or fallback


def owner_slug(email: str) -> str:
    return safe_slug(normalize_email(email) or "anonymous", fallback="anonymous")

