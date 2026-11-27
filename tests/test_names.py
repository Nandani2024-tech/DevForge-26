"""Tests for R7 free-text name detection (Latin/Devanagari/Hinglish) and R8 medical preservation."""
from __future__ import annotations

import json
import time
import unicodedata
from pathlib import Path

from wards.channels import ChannelEvidence, redact_known_names_in_text
from wards.config import PLACEHOLDERS, load_policy
from wards.names import redact_names
from wards.pipeline import run_pipeline


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


def test_r7_r9_nursing_note_uses_pass1_evidence_keeps_lines(tmp_path: Path) -> None:
    # Invented full name absent from dev/input: structured CSV feeds Pass 1 evidence,
    # unlabelled timestamped nursing note gets redacted while preserving line count and K/C/O.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "patients.csv").write_text(
        "uhid,patient_name,dob\nZPQ-77101,Tarunesh Vadhwal,14-05-1988\n",
        encoding="utf-8",
    )
    note_in = (
        "UHID: ZPQ-77101\n"
        "08:30 - Tarunesh Vadhwal - K/C/O Hypothyroidism\n"
        "09:15 - Vitals stable, 650mg given.\n"
    )
    (inp / "nursing_note.txt").write_text(note_in, encoding="utf-8")

    run_pipeline(inp, out, b"r7-r9-note-secret", load_policy())
    note_out = (out / "sanitized" / "nursing_note.txt").read_text(encoding="utf-8")
    assert len(note_out.splitlines()) == len(note_in.splitlines())
    assert "Tarunesh" not in note_out and "Vadhwal" not in note_out
    assert PLACEHOLDERS["PATIENT_NAME"] in note_out
    assert "K/C/O Hypothyroidism" in note_out
    assert "650mg" in note_out


def test_r7_r9_protected_r8_span_word_stays_byte_identical(tmp_path: Path) -> None:
    # Even when a harvested given token matches a protected word (e.g. "Bed", "Parkinson"),
    # R8-protected spans (Bed 12, Parkinson's disease, Dr. ...) stay byte-identical.
    ev = ChannelEvidence()
    ev.add_name("Parkinson Kulkarni", "PATIENT_NAME")
    ev.name_tokens.add("bed")
    text = "Bed 12: Parkinson Kulkarni has Parkinson's disease; Dr. Kulkarni seen 650mg.\n"
    cleaned, _ = redact_known_names_in_text(text, ev, allow_single_tokens=True)
    assert "Bed 12:" in cleaned
    assert "Parkinson's disease" in cleaned
    assert "Dr. Kulkarni" in cleaned
    assert "650mg" in cleaned
    assert f"{PLACEHOLDERS['PATIENT_NAME']} has Parkinson's disease" in cleaned


def test_r7_r9_single_token_requires_active_patient_psn(tmp_path: Path) -> None:
    # A patient-free document (no PSN) only redacts multi-token name phrases, never single tokens.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "roster.json").write_text(
        json.dumps({"patient_ref": "ZPQ-77102", "patient_name": "Zoravar Sengupta"}),
        encoding="utf-8",
    )
    (inp / "ref_single.txt").write_text(
        "Summary of clinical protocol reviewed by Zoravar committee on sepsis.\n",
        encoding="utf-8",
    )
    (inp / "ref_full.txt").write_text(
        "Unlinked circular mentioning Zoravar Sengupta in ward notice.\n",
        encoding="utf-8",
    )

    run_pipeline(inp, out, b"r7-r9-single-gate", load_policy())
    out_single = (out / "sanitized" / "ref_single.txt").read_text(encoding="utf-8")
    out_full = (out / "sanitized" / "ref_full.txt").read_text(encoding="utf-8")
    assert "Zoravar" in out_single  # single token NOT touched when document has no patient PSN
    assert "Zoravar" not in out_full and "Sengupta" not in out_full
    assert PLACEHOLDERS["PATIENT_NAME"] in out_full


def test_r7_r9_all_caps_name_and_asha_protect_context() -> None:
    # All-caps "Name: ASHA THIROVAR" and "Name: DEVESH MENON" redact; community health-worker role stays.
    rx_caps = "Name: ASHA THIROVAR\nTab PCM 650mg BD\nReferred by ASHA worker.\n"
    cleaned_asha, cnt_asha = redact_names(rx_caps)
    assert cnt_asha >= 1
    assert "ASHA THIROVAR" not in cleaned_asha and "THIROVAR" not in cleaned_asha
    assert f"Name: {PLACEHOLDERS['PATIENT_NAME']}" in cleaned_asha
    assert "Referred by ASHA worker." in cleaned_asha

    rx_other = "Name: DEVESH MENON\nAge: 42 / M\n"
    cleaned_other, cnt_other = redact_names(rx_other)
    assert cnt_other == 1
    assert "DEVESH" not in cleaned_other and "MENON" not in cleaned_other
    assert f"Name: {PLACEHOLDERS['PATIENT_NAME']}" in cleaned_other


def test_r7_r9_whole_pipeline_plain_text_scales_linearly(tmp_path: Path) -> None:
    def _best_time(fn, runs: int = 3) -> float:
        best = float("inf")
        for _ in range(runs):
            t0 = time.perf_counter()
            fn()
            elapsed = time.perf_counter() - t0
            if elapsed < best:
                best = elapsed
        return best

    timings: list[float] = []
    for n_lines in (200, 1000, 5000):
        case_dir = tmp_path / f"case_{n_lines}"
        inp = case_dir / "in"
        out = case_dir / "out"
        inp.mkdir(parents=True)
        (inp / "roster.csv").write_text(
            "uhid,patient_name\nZPQ-88001,Zoravar Sengupta\nZPQ-88002,Mrinalini Goswami\n",
            encoding="utf-8",
        )
        line = "08:30 - Zoravar Sengupta - K/C/O HTN; Bed 4, Tab 650mg, Dr. Anil Mehta\n"
        (inp / "notes.txt").write_text("UHID: ZPQ-88001\n" + line * n_lines, encoding="utf-8")

        def _run() -> None:
            run_pipeline(inp, out, b"r7-r9-scale-secret", load_policy())

        timings.append(_best_time(_run))
        san_txt = (out / "sanitized" / "notes.txt").read_text(encoding="utf-8")
        assert "Zoravar" not in san_txt and "Sengupta" not in san_txt
        assert "Dr. Anil Mehta" in san_txt and "650mg" in san_txt

    # 25x input lines (200 -> 5000): linear stays far below quadratic (25^2 = 625x).
    assert timings[2] <= max(0.3, timings[0] * 40.0), timings
