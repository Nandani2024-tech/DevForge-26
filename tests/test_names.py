"""Tests for R7 free-text name detection (Latin/Devanagari/Hinglish) and R8 medical preservation."""
from __future__ import annotations

import time
import unicodedata

from wards.names import redact_names


def test_r7_label_relation_and_honorific_oracles() -> None:
    cases = (
        ("Name: Ravi Kumar, Age 34", "Ravi Kumar", "Age 34"),
        ("नाम: सुनीता देवी", "सुनीता देवी", "नाम:"),
        ("Chetan S/o Kartik Sen", "Chetan", "S/o [RELATIVE]"),
        ("C/O Suresh Yadav, Gram Tarapur", "Suresh Yadav", "Gram Tarapur"),
        ("Shri Rakesh ji came", "Rakesh", "came"),
        ("Name: Kumar, Ravi", "Kumar, Ravi", "Name: [PATIENT_NAME]"),
        ("Name: R. K. Bhatia, Age 40", "R. K. Bhatia", "Age 40"),
        ("Name: Bhatia R K", "Bhatia R K", "Name: [PATIENT_NAME]"),
        ("Name: Ravi Kumar.", "Ravi Kumar", "Name: [PATIENT_NAME]."),
        ("(S/o Kartik)", "Kartik", "(S/o [RELATIVE])"),
        ("Patient: Ravi कुमार, S/o Kartik यादव", "Ravi कुमार", "Patient:"),
        ("Summary for Raghav Bedi, 38 yrs", "Raghav Bedi", "Summary for"),
        ("Record of Deepak Chauhan, 44 yrs", "Deepak Chauhan", "Record of"),
        ("Accompanied by Tarun Solanki", "Tarun Solanki", "Accompanied by"),
        ("Contacted by Manish Joshi", "Manish Joshi", "Contacted by"),
        ("Deepak babu came for review", "Deepak babu", "came for review"),
    )
    for text, secret_name, must_keep in cases:
        cleaned, count = redact_names(text)
        assert count >= 1, text
        for part in secret_name.replace(",", "").split():
            assert part not in cleaned, f"{part!r} leaked in {cleaned!r}"
        assert must_keep in cleaned


def test_r8_medical_context_preserved() -> None:
    keep_samples = (
        "C/O fever x 3 days",
        "K/C/O DM, HTN",
        "H/O asthma x 5 yrs",
        "Dr. Anil Mehta advised Tab Dolo 650mg 1-0-1",
        "Parkinson's disease and Down syndrome",
        "Ward 4 (Medicine), Bed 12, ASHA worker",
    )
    for sample in keep_samples:
        cleaned, count = redact_names(sample)
        assert count == 0, (sample, cleaned)
        assert cleaned == sample


def test_r7_edge_cases_and_nfd_devanagari() -> None:
    assert redact_names("") == ("", 0)
    assert redact_names("Name:") == ("Name:", 0)
    assert redact_names("Name:\nAge: 40") == ("Name:\nAge: 40", 0)
    assert redact_names("Name:   Age: 40") == ("Name:   Age: 40", 0)

    # NFD decomposed Devanagari (precomposed U+095E vs NFD U+092B + U+093C) must match identically to NFC
    nfc = "नाम: \u095eातिमा बीबी"
    nfd = unicodedata.normalize("NFD", nfc)
    assert len(nfd) != len(nfc)
    cleaned_nfd, count_nfd = redact_names(nfd)
    assert count_nfd == 1
    assert "\u095eातिमा" not in cleaned_nfd and "\u092b\u093cातिमा" not in cleaned_nfd
    assert cleaned_nfd == "नाम: [PATIENT_NAME]"

    # Unmatched NFD text must keep its exact input bytes unchanged (WARN H4)
    unmatched_nfd = "दवा: \u092b\u093cोलेट 5 mg"
    assert redact_names(unmatched_nfd) == (unmatched_nfd, 0)


def test_r7_hinglish_and_deva_clinical_subjects() -> None:
    text = (
        "गिरीश नेगी को 4 दिन से खांसी है।\n"
        "Pallavi ka BP 132/86 hai.\n"
        "Imran Lokhande (attendant, bed 5)\n"
        "Name: Asha Kumari, 32 yrs. Referred by ASHA worker.\n"
        "Asha's attendant and Tejas Chachu called.\n"
        "Dr. Vikram Joglekar reviewed the patient.\n"
    )
    cleaned, count = redact_names(text)
    assert count >= 6
    assert len(cleaned.splitlines()) == 6
    for pii in ("गिरीश", "नेगी", "Pallavi", "Imran", "Lokhande", "Asha", "Kumari", "Tejas", "Chachu"):
        assert pii not in cleaned
    assert "ASHA worker" in cleaned
    assert "BP 132/86" in cleaned
    assert "Dr. Vikram Joglekar" in cleaned


def test_r7_dense_text_scales_linearly() -> None:
    line = "Name: Ravi Kumar, Age 34. Chetan S/o Kartik Sen. C/O fever x 3 days. Dr. Anil Mehta 650mg 1-0-1.\n"
    timings: list[float] = []
    for n_lines in (200, 2000, 20000):
        payload = line * n_lines
        t0 = time.perf_counter()
        cleaned, count = redact_names(payload)
        elapsed = time.perf_counter() - t0
        assert count == 3 * n_lines
        assert "Ravi" not in cleaned and "Kartik" not in cleaned
        assert "Dr. Anil Mehta" in cleaned
        timings.append(elapsed)

    # 10x input (2,000 -> 20,000): linear gives ~10x time, quadratic ~100x.
    assert timings[2] <= max(0.3, timings[1] * 15.0), timings


def test_r7_r8_protect_mask_and_label_boundaries_hand_derived() -> None:
    # Hand-derived (invented names, not from dev): a K/C/O or H/O clause protects the
    # clinical term, not a person introduced later in the same clause by an honorific.
    cleaned, _ = redact_names("K/C/O HTN, brought by Shri Sunil Thakur")
    assert "K/C/O HTN" in cleaned
    assert "Sunil" not in cleaned and "Thakur" not in cleaned
    cleaned, _ = redact_names("H/O asthma, Smt. Leela Pillai accompanied")
    assert "H/O asthma" in cleaned
    assert "Leela" not in cleaned and "Pillai" not in cleaned

    # Devanagari label value stops at the next label word: "उम्र" (age) is not part of the name.
    cleaned, count = redact_names("नाम: अर्जुन प्रसाद, उम्र 40")
    assert count == 1
    assert "अर्जुन" not in cleaned and "प्रसाद" not in cleaned
    assert "उम्र 40" in cleaned

    # A role word before "<name> S/o <relative>" must not cancel the patient-name match.
    cleaned, _ = redact_names("Patient Vinod Rana S/o Samar Rana")
    assert "Vinod" not in cleaned and "Samar" not in cleaned
    assert cleaned.startswith("Patient ")


def test_r7_second_label_or_relation_on_same_line_is_found() -> None:
    # Hand-derived (invented names): each label/relation marker starts its own span;
    # an earlier match must not swallow the rest of the line.
    cleaned, _ = redact_names("Name: Bhavesh Nair, Father Name: Ganpat Nair")
    assert "Bhavesh" not in cleaned and "Ganpat" not in cleaned
    assert "Father Name:" in cleaned
    cleaned, _ = redact_names("Guardian: Ganpat Nair | Name: Bhavesh Nair")
    assert "Ganpat" not in cleaned and "Bhavesh" not in cleaned
    cleaned, _ = redact_names("Kiran S/o Balwant Rao W/o Nitin Rao")
    assert "Balwant" not in cleaned and "Nitin" not in cleaned


def test_r7_single_long_line_scales_linearly() -> None:
    # Target O(bytes) (04-idea-scope). One line with no newline, 10x size step:
    # linear growth gives ~10x time; quadratic gives ~100x. Allow up to 20x.
    def run(n: int) -> float:
        payload = "Shri Rakesh ji came, " * n
        t0 = time.perf_counter()
        cleaned, count = redact_names(payload)
        elapsed = time.perf_counter() - t0
        assert count == n
        assert "Rakesh" not in cleaned
        return elapsed

    small = run(300)
    large = run(3000)
    assert large <= max(0.5, small * 20.0), (small, large)
