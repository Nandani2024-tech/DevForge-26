"""Tests for R10 cross-file/script linkage, conflict guard, and R11 canonical cluster PSNs."""
from __future__ import annotations

import json
import time
from pathlib import Path

from wards.config import PLACEHOLDERS, load_policy
from wards.linkage import RecordEvidence, link_records, normalise_name_key, normalise_strong_id
from wards.pipeline import run_pipeline
from wards.pseudo import date_shift_days, pseudonym


def test_r10_name_normalisation_and_strong_ids() -> None:
    # Transliteration with schwa deletion across Devanagari & Latin + honorific stripping
    assert normalise_name_key("Shri Rohan Kulkarni") == "kulkarni rohan"
    assert normalise_name_key("Kulkarni, Rohan ji") == "kulkarni rohan"
    deva_key = normalise_name_key("रोहन कुलकर्णी")
    assert deva_key is not None and "rohan" in deva_key and "kulakarn" in deva_key

    assert normalise_strong_id("phone", "+91-98765-43210") == ("phone", "9876543210")
    assert normalise_strong_id("aadhaar", "4123 4567 8901") == ("aadhaar", "412345678901")
    # Per-issuer IDs key on the digit core (02-domain R6/R11): "HSP/26/001234" -> 2,6,0,0,1,2,3,4
    assert normalise_strong_id("mrn", "HSP/26/001234") == ("mrn", "26001234")
    assert normalise_strong_id("mrn", "HSP-26-001234") == normalise_strong_id("mrn", "26/001234")


def test_r10_homonyms_with_different_dob_never_merged() -> None:
    recs = [
        RecordEvidence(0, "a.csv", "row:0", strong_ids=(), name_key="bhosale gaurav", dob_iso="1980-03-10"),
        RecordEvidence(1, "b.csv", "row:0", strong_ids=(), name_key="bhosale gaurav", dob_iso="1992-07-22"),
    ]
    res = link_records(recs)
    # Singletons with only weak evidence must stay unlinked (None)
    assert res.canonical_keys[0] is None
    assert res.canonical_keys[1] is None


def test_r10_conflict_guard_splits_transitive_and_shared_phone() -> None:
    # A~B on ID, B~C on name+DOB, C has a different same-type ID -> split into strong components
    recs = [
        RecordEvidence(0, "a.csv", "row:0", strong_ids=(("aadhaar", "411111111111"),), name_key="kulkarni rohan", dob_iso="1985-04-12"),
        RecordEvidence(1, "b.csv", "row:0", strong_ids=(("aadhaar", "411111111111"),), name_key="kulkarni rohan", dob_iso="1985-04-12"),
        RecordEvidence(2, "c.csv", "row:0", strong_ids=(("aadhaar", "422222222222"),), name_key="kulkarni rohan", dob_iso="1985-04-12"),
        RecordEvidence(3, "d.txt", "doc", strong_ids=(), name_key="kulkarni rohan", dob_iso="1985-04-12"),
    ]
    res = link_records(recs)
    assert res.canonical_keys[0] == "aadhaar:411111111111"
    assert res.canonical_keys[1] == "aadhaar:411111111111"
    assert res.canonical_keys[2] == "aadhaar:422222222222"
    assert res.canonical_keys[3] is None  # weak-only record inside conflicted cluster becomes null

    # Parent and child sharing one phone with conflicting DOBs/Aadhaars -> split off phone
    fam = [
        RecordEvidence(0, "p.csv", "row:0", strong_ids=(("aadhaar", "433333333333"), ("phone", "9876500001")), dob_iso="1972-01-01"),
        RecordEvidence(1, "c.csv", "row:0", strong_ids=(("aadhaar", "444444444444"), ("phone", "9876500001")), dob_iso="2005-05-05"),
        RecordEvidence(2, "w.txt", "doc", strong_ids=(("phone", "9876500001"),)),
    ]
    fam_res = link_records(fam)
    assert fam_res.canonical_keys[0] == "aadhaar:433333333333"
    assert fam_res.canonical_keys[1] == "aadhaar:444444444444"
    assert fam_res.canonical_keys[2] is None


def test_r10_r11_secrets_change_psn_and_keep_partition(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "hosp_a.csv").write_text(
        "uhid,name,dob,phone,visit_date\n"
        "HSP-1001,Rohan Kulkarni,14/06/1985,9876543210,10/03/2026\n"
        "HSP-1002,Meera Deshmukh,02/08/1990,,12/03/2026\n",
        encoding="utf-8",
    )
    (inp / "hosp_b.json").write_text(
        json.dumps(
            {
                "visits": [
                    {"patient_ref": "CLI-9901", "name": "Rohan Kulkarni", "phone": "+91-9876543210", "visit_date": "2026-03-19"}
                ]
            }
        ),
        encoding="utf-8",
    )
    (inp / "weak_only.txt").write_text("Name: Meera Deshmukh\nDate: 15/03/2026\n", encoding="utf-8")

    policy = load_policy()
    out_x = tmp_path / "out_x"
    out_y = tmp_path / "out_y"
    res_x = run_pipeline(inp, out_x, b"secret-alpha-x", policy)
    res_y = run_pipeline(inp, out_y, b"secret-beta-y", policy)

    recs_x = {f"{r['file']}|{r['loc']}": r["patient"] for r in res_x.records}
    recs_y = {f"{r['file']}|{r['loc']}": r["patient"] for r in res_y.records}

    # Same patient across hosp_a row:0 and hosp_b /visits/0 gets identical PSN under secret X, and different under Y
    psn_x_a = recs_x["sanitized/hosp_a.csv|row:0"]
    psn_x_b = recs_x["sanitized/hosp_b.json|/visits/0"]
    assert psn_x_a is not None and psn_x_a == psn_x_b
    assert recs_x["sanitized/hosp_a.csv|row:1"] is not None
    assert recs_x["sanitized/hosp_a.csv|row:1"] != psn_x_a
    # Weak-only single name note stays unlinked (None)
    assert recs_x["sanitized/weak_only.txt|doc"] is None

    psn_y_a = recs_y["sanitized/hosp_a.csv|row:0"]
    psn_y_b = recs_y["sanitized/hosp_b.json|/visits/0"]
    assert psn_y_a is not None and psn_y_a == psn_y_b
    assert psn_x_a != psn_y_a

    # Same partition across secrets
    assert (psn_x_a == psn_x_b) == (psn_y_a == psn_y_b)

    # Keyed shifts differ across secrets & across patients
    off_x_1 = date_shift_days("k1", b"secret-alpha-x", policy.date_shift_max_days, policy.date_shift_min_abs_days)
    off_y_1 = date_shift_days("k1", b"secret-beta-y", policy.date_shift_max_days, policy.date_shift_min_abs_days)
    assert off_x_1 != off_y_1
    assert pseudonym("phone:9876543210", b"secret-alpha-x") != pseudonym("phone:9876543210", b"secret-beta-y")


def test_r10_linkage_scales_linearly() -> None:
    timings: list[float] = []
    for n in (500, 5000):
        recs = [
            RecordEvidence(
                i,
                f"f_{i // 100}.csv",
                f"row:{i}",
                strong_ids=((("mrn", f"id{i // 2}"), ("phone", f"98{i // 2:08d}"))),
                name_key=f"person {i // 2}",
            )
            for i in range(n)
        ]
        t0 = time.perf_counter()
        res = link_records(recs)
        timings.append(time.perf_counter() - t0)
        assert len(res.canonical_keys) == n
        assert res.canonical_keys[0] == res.canonical_keys[1]
    assert timings[1] <= max(0.15, timings[0] * 18.0), timings


def test_r10_per_hospital_ids_link_but_never_conflict() -> None:
    # One patient, two hospitals: different MRNs, shared phone -> one cluster (MRNs are not a conflict).
    recs = [
        RecordEvidence(0, "h1.csv", "row:0", strong_ids=(("mrn", "5503317"), ("phone", "9123400077"))),
        RecordEvidence(1, "h2.json", "/v/0", strong_ids=(("mrn", "88123"), ("phone", "9123400077"))),
        RecordEvidence(2, "h1.txt", "doc", strong_ids=(("mrn", "5503317"),)),
    ]
    res = link_records(recs)
    # Canonical key = min of sorted member keys: "mrn:5503317" < "mrn:88123" < "phone:..."
    assert res.canonical_keys[0] == res.canonical_keys[1] == res.canonical_keys[2] == "mrn:5503317"


def test_r10_split_groups_never_share_a_key_from_a_dropped_edge() -> None:
    # Two people with one MRN digit core (two hospitals reuse the number) and different DOBs:
    # the MRN edge is dropped by the guard, so neither keeps "mrn:..." as a shared key.
    recs = [
        RecordEvidence(0, "h1.csv", "row:0", strong_ids=(("mrn", "40021"),), name_key="qorvel tanshi", dob_iso="1971-02-03"),
        RecordEvidence(1, "h2.csv", "row:0", strong_ids=(("mrn", "40021"),), name_key="ubrak yelmo", dob_iso="1999-11-30"),
        RecordEvidence(2, "h2.csv", "row:1", strong_ids=(("mrn", "40021"), ("aadhaar", "455566667777")), dob_iso="1999-11-30"),
    ]
    res = link_records(recs)
    keys = [res.canonical_keys[i] for i in range(3)]
    assert keys[2] == "aadhaar:455566667777"
    assert keys[0] is None and keys[1] is None  # no lifelong ID: null, never a merged key
    assert len({k for k in keys if k is not None}) == 1


def test_r10_two_lifelong_ids_of_one_type_conflict() -> None:
    recs = [
        RecordEvidence(0, "a.csv", "row:0", strong_ids=(("pan", "ABCPZ1234K"), ("phone", "9988776655"))),
        RecordEvidence(1, "b.csv", "row:0", strong_ids=(("pan", "XYZPQ9876L"), ("phone", "9988776655"))),
    ]
    res = link_records(recs)
    assert res.canonical_keys[0] == "pan:ABCPZ1234K"
    assert res.canonical_keys[1] == "pan:XYZPQ9876L"


def test_r10_visit_and_bill_ids_are_not_patient_evidence(tmp_path: Path) -> None:
    # Two different patients share nothing but a bill number shape; the bill column must not link them.
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "t.csv").write_text(
        "Bill No,MRN,Visit ID,Hb\nBQ-90017,QX00771,VZ-30001,11.0\nBQ-90017,QX00772,VZ-30001,12.0\n",
        encoding="utf-8",
    )
    res = run_pipeline(inp, tmp_path / "out", b"bill-secret", load_policy())
    psns = [r["patient"] for r in res.records]
    assert psns[0] is not None and psns[1] is not None and psns[0] != psns[1]


def test_r11_null_patient_id_slot_is_redacted_not_kept(tmp_path: Path) -> None:
    # One UHID, two different DOBs: the guard nulls both records. Their ID slot must not
    # keep the original value (it gets the [MRN] placeholder instead of a PSN).
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    for idx, dob in enumerate(("1966-01-15", "2001-09-09")):
        doc = {"lab": "Hb panel", "patient": {"uhid": "QZT-0099812", "dob": dob}, "result": 11.2}
        (inp / f"r{idx}.json").write_text(json.dumps(doc), encoding="utf-8")
    res = run_pipeline(inp, out, b"null-secret", load_policy())
    assert [r["patient"] for r in res.records] == [None, None]
    for idx in range(2):
        san = json.loads((out / "sanitized" / f"r{idx}.json").read_text(encoding="utf-8"))
        assert san["patient"]["uhid"] == PLACEHOLDERS["MRN"]
        assert san["result"] == 11.2
