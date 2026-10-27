"""Offline validators for Indian identifiers (no network, no CAPTCHA)."""

from __future__ import annotations

import re

_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_RE = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
_CIN_RE = re.compile(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")

# GST state codes (01-38) plus 97 (other territory) and 99 (centre jurisdiction).
_VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}


def gstin_checksum(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARSET.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _CHARSET[(36 - total % 36) % 36]


def validate_gstin(gstin: str) -> tuple[bool, str]:
    """Return (is_valid, reason). Checks format, state code and checksum digit."""
    g = gstin.strip().upper()
    m = _GSTIN_RE.match(g)
    if not m:
        return False, "does not match the 15-character GSTIN format"
    if m.group(1) not in _VALID_STATE_CODES:
        return False, f"state code {m.group(1)} is not a valid GST state code"
    if gstin_checksum(g[:14]) != g[14]:
        return False, "checksum character does not match"
    return True, "format, state code and checksum are valid"


def gstin_pan(gstin: str) -> str:
    return gstin.strip().upper()[2:12]


def validate_cin(cin: str) -> bool:
    return bool(_CIN_RE.match(cin.strip().upper()))
