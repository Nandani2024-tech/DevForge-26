"""Keyed HMAC pseudonyms, per-patient date shifts, and age banding."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    """Compute raw HMAC-SHA256 digest. O(len(msg))."""
    return hmac.new(key, msg, hashlib.sha256).digest()


def slot_patient_key(normalised_slot_value: str) -> str:
    """Build the temporary spike key from a normalised ID-slot value.

    Task 3 replaces this with the canonical cross-record cluster key.
    """
    return f"slot:{normalised_slot_value}"


def pseudonym(patient_key: str, secret: bytes) -> str:
    """Derive a stable, non-reversible PSN-XXXXXX identifier via HMAC-SHA256."""
    digest = hmac_sha256(secret, patient_key.encode("utf-8"))
    n = int.from_bytes(digest[:5], "big")
    code = "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(6))
    return f"PSN-{code}"


def date_shift_days(
    patient_key: str,
    secret: bytes,
    max_days: int,
    min_abs_days: int,
) -> int:
    """Return a deterministic non-zero shift in [-max_days, -min_abs_days] U [min_abs_days, max_days]."""
    if max_days < 1:
        raise ValueError("max_days must be positive")
    lo_abs = max(1, min(min_abs_days, max_days))
    span = max_days - lo_abs + 1
    digest = hmac_sha256(secret, b"shift|" + patient_key.encode("utf-8"))
    idx = int.from_bytes(digest[:4], "big") % (2 * span)
    if idx < span:
        return -(lo_abs + idx)
    return lo_abs + (idx - span)


def shift_date(value: dt.date, offset_days: int) -> dt.date:
    """Shift a calendar date by offset_days, preserving exact day intervals."""
    return value + dt.timedelta(days=offset_days)


def age_band(age: int, width: int, top_code: int | None = None) -> str:
    """Map an integer age to a fixed-width band containing the true age."""
    if width < 1:
        raise ValueError("width must be positive")
    if top_code is not None and age >= top_code:
        return f"{top_code}+"
    lo = (age // width) * width
    return f"{lo}-{lo + width - 1}"
