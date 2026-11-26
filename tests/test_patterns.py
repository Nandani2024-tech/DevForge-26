"""Tests for R6 identifier/phone detection, Devanagari digits, Verhoeff, and medical preserve rules."""
from __future__ import annotations

import time

from wards.patterns import extract_phone_core, redact_identifiers, verhoeff_valid


def test_verhoeff_oracles() -> None:
    assert verhoeff_valid("2363") is True
    assert verhoeff_valid("2364") is False
    assert verhoeff_valid("9427") is True
    assert verhoeff_valid("") is False
    assert verhoeff_valid("12A4") is False


def test_phone_oracles_and_devanagari_digits() -> None:
    assert extract_phone_core("+91-98765-43210") == "9876543210"
    assert extract_phone_core("098765 43210") == "9876543210"
    assert extract_phone_core("९८७६५४३२१०") == "9876543210"

    cleaned, count = redact_identifiers("Call +91-98765-43210 or ९८७६५४३२१० now")
    assert count == 2
    assert "98765" not in cleaned
    assert "९८७६५४३२१०" not in cleaned
    assert cleaned.count("[PHONE]") == 2


def test_preserve_medical_values_untouched() -> None:
    for sample in ("Dolo 650mg 1-1-1 x 5 days", "BP 117/82", "plt 1,45,000", "PSN-7Q2K9D"):
        cleaned, count = redact_identifiers(sample)
        assert count == 0
        assert cleaned == sample


def test_all_r6_identifier_types_and_line_count() -> None:
    text = (
        "Aadhaar: 4123 4567 8901 and ४१२३ ४५६७ ८९०१\n"
        "Masked: XXXX XXXX 4321 and ****-****-1234\n"
        "ABHA: 91-1020-3040-5060 Addr: patient.one@abdm\n"
        "PAN: ABCDE1234F Email: person@example.org\n"
        "Policy No: POL-998811 Scheme ID: SCH-11223344\n"
        "IPD No: IPD-2099-00999 UHID: PSN-7Q2K9D\n"
    )
    cleaned, count = redact_identifiers(text)
    assert count >= 11
    assert len(cleaned.splitlines()) == len(text.splitlines())
    for secret_val in (
        "4123 4567 8901",
        "४१२३",
        "4321",
        "1234",
        "91-1020-3040-5060",
        "patient.one@abdm",
        "ABCDE1234F",
        "person@example.org",
        "SCH-11223344",
        "POL-998811",
        "IPD-2099-00999",
    ):
        assert secret_val not in cleaned
    assert "PSN-7Q2K9D" in cleaned


def test_r6_ids_before_sentence_punctuation_are_redacted() -> None:
    # Hand-derived: an ID ending a sentence is still an ID; the full stop is prose, not part
    # of a decimal (no digit follows it). Expected: value gone, punctuation kept.
    cases = (
        ("Mobile 8111222333.", "8111222333", "Mobile [PHONE]."),
        ("ABHA 91-1020-3040-5060.", "91-1020-3040-5060", "ABHA [ABHA]."),
        ("Aadhaar 4123 4567 8901.", "4123 4567 8901", "Aadhaar [AADHAAR]."),
        ("Call 9876543210!", "9876543210", "Call [PHONE]!"),
    )
    for text, surface, expected in cases:
        cleaned, count = redact_identifiers(text)
        assert surface not in cleaned, text
        assert cleaned == expected
        assert count == 1


def test_r6_decimal_lab_value_after_ten_digits_not_a_phone() -> None:
    # A digit after the dot makes it a number, not sentence-final punctuation.
    cleaned, count = redact_identifiers("value 9876543210.5 units")
    assert count == 0
    assert cleaned == "value 9876543210.5 units"


def test_labelled_dob_village_address_and_pin_preserve_district() -> None:
    text = (
        "DOB: 14/06/1980\n"
        "ग्राम: तारापुर\n"
        "Address: Plot 99, Lane 7, Block Nine, Gram Nandipur, Tehsil North, Distt. Kanpur - 209999\n"
        "Date of Admission: 02/01/2026\n"
    )
    cleaned, count = redact_identifiers(text)
    assert count == 4
    assert len(cleaned.splitlines()) == 4
    assert "14/06/1980" not in cleaned and "[DOB]" in cleaned
    assert "तारापुर" not in cleaned and "[VILLAGE]" in cleaned
    assert "Plot 99" not in cleaned and "Nandipur" not in cleaned and "209999" not in cleaned
    assert "[ADDRESS]" in cleaned and "[PIN]" in cleaned
    assert "Distt. Kanpur" in cleaned
    assert "Date of Admission: 02/01/2026" in cleaned


def test_r6_dense_text_scales_linearly() -> None:
    sample_line = "UHID: X-123. Mobile 9876543210. PAN ABCDE1234F. Aadhaar 4123 4567 8901. Dolo 650mg 1-1-1.\n"
    timings: list[float] = []
    for n_lines in (2000, 20000):
        payload = sample_line * n_lines
        t0 = time.monotonic()
        cleaned, count = redact_identifiers(payload)
        elapsed = time.monotonic() - t0
        assert count == 4 * n_lines
        assert "9876543210" not in cleaned
        timings.append(elapsed)

    assert timings[1] < 2.0
    assert timings[1] <= max(0.25, timings[0] * 20.0)
