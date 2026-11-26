"""Tests for R13 age banding, top-coding, district preservation, and PIN prefix generalisation."""
from __future__ import annotations

import json
from pathlib import Path

from wards.config import load_policy
from wards.generalise import generalise_address_field, generalise_age_field, generalise_pin_str, generalise_text_qis
from wards.pipeline import run_pipeline
from wards.pseudo import age_band


def test_r13_age_band_raw_and_top_coded() -> None:
    policy = load_policy()
    w, top = policy.age_band_years, policy.age_top_code
    for age in range(0, 105):
        band = age_band(age, width=w, top_code=top)
        if age >= top:
            assert band == f"{top}+"
        else:
            lo_str, hi_str = band.split("-")
            lo, hi = int(lo_str), int(hi_str)
            assert lo <= age <= hi and hi - lo + 1 == w

    assert generalise_age_field("48/F", w, top) == ("45-49/F", 1)
    assert generalise_age_field("97 Y / M", w, top) == ("85+ Y / M", 1)
    assert generalise_age_field("52 वर्ष / पुरुष", w, top) == ("50-54 वर्ष / पुरुष", 1)


def test_r13_pin_and_address_keep_district_and_prefix() -> None:
    assert generalise_pin_str("226001", 3) == ("226***", 1)
    assert generalise_pin_str("२०८००१", 3) == ("208***", 1)

    addr_out, cnt = generalise_address_field(
        "Plot 99, Block Nine, Gram Nandipur, Tehsil North, Distt. Kanpur - 209999",
        location_level="district",
        prefix_digits=3,
    )
    assert cnt == 1
    assert "Plot 99" not in addr_out and "Nandipur" not in addr_out
    assert "Distt. Kanpur" in addr_out
    assert "209***" in addr_out and "209999" not in addr_out


def test_r13_free_text_keeps_durations_and_rates() -> None:
    sample = (
        "Age: 48/F. H/O DM x 12 yrs, 7 yrs back TB. Pulse 78/min. "
        "BP 120/80. Dolo 650 mg 1-0-1. PIN: 226001."
    )
    out, cnt = generalise_text_qis(sample, width=5, top_code=85, prefix_digits=3)
    assert cnt == 2
    assert "Age: 45-49/F" in out
    assert "12 yrs" in out and "7 yrs back" in out
    assert "Pulse 78/min" in out and "BP 120/80" in out and "650 mg 1-0-1" in out
    assert "226***" in out and "226001" not in out


def test_r13_end_to_end_json_age_int_to_band_and_district(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {
        "patient": {
            "uhid": "CLI-55001",
            "name": "Gaurav Bhosale",
            "age": 97,
            "village": "Nandipur",
            "house": "House 99",
            "locality": "North Block",
            "landmark": "Near Canal",
            "district": "Kanpur",
            "pin": "209999",
        }
    }
    (inp / "pat.json").write_text(json.dumps(doc), encoding="utf-8")
    run_pipeline(inp, out, b"r13-secret", load_policy())
    san = json.loads((out / "sanitized" / "pat.json").read_text(encoding="utf-8"))["patient"]
    assert san["age"] == "85+"
    assert san["district"] == "Kanpur"
    assert san["pin"] == "209***"
    assert san["village"] == "[VILLAGE]"
    assert san["house"] == "[HOUSE]"
    assert san["locality"] == "[LOCALITY]"
    assert san["landmark"] == "[LANDMARK]"


def test_r13_age_banded_only_in_age_context() -> None:
    sample = "Pt 48 Y / M, DM x 12 yrs, TB 3 yrs back. RR 22/min, BP 130/90, Age/Sex: 97/F, 52 वर्ष / पुरुष"
    out, cnt = generalise_text_qis(sample, width=5, top_code=85, prefix_digits=3)
    # Hand-derived: 48 -> 45-49, 97 -> 85+ (top-code), 52 -> 50-54; nothing else changes.
    assert cnt == 3
    assert "45-49 Y / M" in out and "Age/Sex: 85+/F" in out and "50-54 वर्ष / पुरुष" in out
    assert "x 12 yrs" in out and "3 yrs back" in out and "RR 22/min" in out and "BP 130/90" in out


def test_r13_unlabelled_pin_after_district_keeps_prefix(tmp_path: Path) -> None:
    # The R6 address detector finds the PIN; the R13 policy keeps its 3-digit prefix.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "ds.txt").write_text(
        "Address: Ward 4, Gram Zelvanpur, Tehsil Ortho, Distt. Quillabad - 284731\nDx: AGE\n",
        encoding="utf-8",
    )
    run_pipeline(inp, out, b"pin-secret", load_policy())
    text = (out / "sanitized" / "ds.txt").read_text(encoding="utf-8")
    assert "284731" not in text and "284***" in text
    assert "Zelvanpur" not in text and "Quillabad" in text


def test_r13_invalid_age_gets_placeholder_never_a_band() -> None:
    from wards.config import MAX_VALID_AGE, PLACEHOLDERS
    from wards.generalise import generalise_age_int

    age_ph = PLACEHOLDERS["AGE"]
    assert generalise_age_field("-2 वर्ष", 5, 85) == (f"{age_ph} वर्ष", 1)
    assert generalise_age_field(f"{MAX_VALID_AGE + 1} Y", 5, 85) == (f"{age_ph} Y", 1)
    assert generalise_age_int(-3, 5, 85) == age_ph
    assert generalise_age_int(MAX_VALID_AGE + 1, 5, 85) == age_ph
    # Boundaries stay ages: 0 -> 0-4, MAX_VALID_AGE -> top-code band.
    assert generalise_age_int(0, 5, 85) == "0-4"
    assert generalise_age_int(MAX_VALID_AGE, 5, 85) == "85+"
    out, cnt = generalise_text_qis("Age: -1. Age: 48/F", width=5, top_code=85, prefix_digits=3)
    assert out == f"Age: {age_ph}. Age: 45-49/F" and cnt == 2
