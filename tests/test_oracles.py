"""Hand-derived and RFC test oracles (02-domain.md sec 5)."""
from __future__ import annotations

import datetime as dt
import hashlib

from wards.config import load_policy
from wards.ingest import decode_bytes, json_pointer_escape, json_pointer_unescape
from wards.pseudo import age_band, date_shift_days, hmac_sha256, pseudonym, shift_date


def test_hmac_sha256_rfc4231_tc2() -> None:
    digest = hmac_sha256(b"Jefe", b"what do ya want for nothing?")
    assert digest.hex() == "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"


def test_pseudonym_keyed_and_deterministic() -> None:
    s1 = b"practice-secret"
    s2 = b"other-secret"
    p1 = pseudonym("slot:HOSP-99001", s1)
    p1_repeat = pseudonym("slot:HOSP-99001", s1)
    p2 = pseudonym("slot:HOSP-99001", s2)
    assert p1 == p1_repeat
    assert p1 != p2
    assert p1.startswith("PSN-")
    assert len(p1) == 10
    assert "99001" not in p1


def test_json_pointer_rfc6901() -> None:
    assert f"/{json_pointer_escape('a/b')}" == "/a~1b"
    assert f"/{json_pointer_escape('m~n')}" == "/m~0n"
    assert json_pointer_unescape("~01") == "~1"


def test_age_band_oracle() -> None:
    width = load_policy().age_band_years
    cases = [(0, "0-4"), (4, "0-4"), (5, "5-9"), (48, "45-49"), (50, "50-54"), (97, "95-99")]
    for age, expected in cases:
        assert age_band(age, width=width) == expected


def test_shift_date_intervals_and_leap_years() -> None:
    admit = dt.date(2026, 3, 28)
    discharge = dt.date(2026, 4, 6)
    shifted_admit = shift_date(admit, 17)
    shifted_discharge = shift_date(discharge, 17)
    assert shifted_admit == dt.date(2026, 4, 14)
    assert shifted_discharge == dt.date(2026, 4, 23)
    assert (shifted_discharge - shifted_admit).days == (discharge - admit).days == 9

    assert shift_date(dt.date(2024, 2, 28), 2) == dt.date(2024, 3, 1)
    assert shift_date(dt.date(2026, 2, 28), 2) == dt.date(2026, 3, 2)


def test_date_shift_days_bounds_and_non_zero() -> None:
    policy = load_policy()
    for idx in range(50):
        offset = date_shift_days(
            f"patient-{idx}",
            b"secret-a",
            max_days=policy.date_shift_max_days,
            min_abs_days=policy.date_shift_min_abs_days,
        )
        assert -policy.date_shift_max_days <= offset <= policy.date_shift_max_days
        assert abs(offset) >= policy.date_shift_min_abs_days
        assert offset != 0


def test_decode_bytes_oracles() -> None:
    assert decode_bytes(b"\xff\xfeA\x00") == "A"
    assert decode_bytes(b"\x93hi\x94") == "\u201chi\u201d"
    assert decode_bytes(b"\xef\xbb\xbfhello") == "hello"
    assert decode_bytes(b"\x81") is None


def test_empty_sha256_oracle() -> None:
    assert hashlib.sha256(b"").hexdigest() == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
