"""Tests for R12 format-preserving date parsing, convention voting, and per-patient shifting."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from wards.config import load_policy
from wards.dates import DATE_ORDER_DMY, DATE_ORDER_MDY, infer_date_order, parse_dob_iso, shift_dates_in_text
from wards.pipeline import run_pipeline


def test_r12_format_preservation_and_intervals() -> None:
    sample = "DMY: 28/03/2026 | MDY-dash: 03-28-2026 | ISO: 2026-04-06 | Time: 2026-04-06T09:30:00+05:30"
    shifted_dmy, cnt = shift_dates_in_text("28/03/2026 and 06/04/2026", 17, order=DATE_ORDER_DMY)
    assert cnt == 2 and shifted_dmy == "14/04/2026 and 23/04/2026"

    shifted_mdy, cnt_m = shift_dates_in_text("03-28-2026 to 04-06-2026", 17, order=DATE_ORDER_MDY)
    assert cnt_m == 2 and shifted_mdy == "04-14-2026 to 04-23-2026"

    shifted_iso, cnt_i = shift_dates_in_text(
        "2026-03-28 and 2026-04-06T14:15:00+05:30", 17, order=DATE_ORDER_DMY
    )
    assert cnt_i == 2
    assert shifted_iso == "2026-04-14 and 2026-04-23T14:15:00+05:30"
    assert "09:30:00+05:30" in shift_dates_in_text(sample, 17, order=DATE_ORDER_DMY)[0]

    # Single-digit unpadded dates keep single-digit formatting when day/month < 10
    s_unpadded, _ = shift_dates_in_text("2/3/2026", 2, order=DATE_ORDER_DMY)
    assert s_unpadded == "4/3/2026"

    # Leap-year boundaries
    assert shift_dates_in_text("2024-02-28", 2)[0] == "2024-03-01"
    assert shift_dates_in_text("2026-02-28", 2)[0] == "2026-03-02"


def test_r12_convention_voting_and_dob_parsing() -> None:
    assert infer_date_order(["14/06/1980", "01/02/2026"]) == DATE_ORDER_DMY
    assert infer_date_order(["01/13/2026", "02/28/2026", "03/04/2026"]) == DATE_ORDER_MDY
    assert parse_dob_iso("14/06/1980", order=DATE_ORDER_DMY) == "1980-06-14"
    assert parse_dob_iso("06/14/1980", order=DATE_ORDER_MDY) == "1980-06-14"


def test_r12_null_patient_record_keeps_intra_record_intervals(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "unlinked.txt").write_text(
        "Name: Meera Deshmukh\nAdmit: 28/03/2026\nDischarge: 06/04/2026\n",
        encoding="utf-8",
    )
    policy = load_policy()
    res = run_pipeline(inp, out, b"r12-secret", policy)
    assert res.records[0]["patient"] is None

    san = (out / "sanitized" / "unlinked.txt").read_text(encoding="utf-8")
    assert "28/03/2026" not in san and "06/04/2026" not in san
    lines = san.splitlines()
    d_adm = dt.datetime.strptime(lines[1].split(": ", 1)[1], "%d/%m/%Y").date()
    d_dis = dt.datetime.strptime(lines[2].split(": ", 1)[1], "%d/%m/%Y").date()
    assert (d_dis - d_adm).days == 9


def test_r12_ambiguous_or_invalid_date_never_left_raw() -> None:
    reasons: dict[str, int] = {}
    out, cnt = shift_dates_in_text("DOB: 31/02/2026", 17, order=DATE_ORDER_DMY, reason_counts=reasons)
    assert cnt == 1
    assert "31/02/2026" not in out
    assert reasons["ambiguous_or_invalid_date"] == 1


def test_r12_yearless_date_takes_the_year_of_the_same_text() -> None:
    # Hand-derived, +2 days; a two-digit day stays two digits wide ("28" -> "02").
    # 2023 is not a leap year: 2023-02-27 -> 2023-03-01, 28 Feb -> 02 Mar.
    out, _ = shift_dates_in_text("Visit 2023-02-27. Review 28 Feb.", 2)
    assert out == "Visit 2023-03-01. Review 02 Mar."
    # 2024 is a leap year: 2024-02-27 -> 2024-02-29, 28 Feb -> 01 Mar.
    out, _ = shift_dates_in_text("Visit 2024-02-27. Review 28 Feb.", 2)
    assert out == "Visit 2024-02-29. Review 01 Mar."
