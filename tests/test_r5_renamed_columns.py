"""R5 slice 1 tests: header-independent column/key classification, shape vote, address context, and D9."""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

from wards.channels import ChannelEvidence
from wards.columns import classify_csv_columns, find_non_patient_mrn_cols
from wards.config import PLACEHOLDERS, load_policy
from wards.pipeline import run_pipeline

_TEST_SECRET = b"r5-renamed-columns-secret"


def _best_elapsed_seconds(fn, runs: int = 3) -> float:
    best = float("inf")
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - t0
        if elapsed < best:
            best = elapsed
    return best


def test_r5_unknown_headers_by_value_shape_and_evidence(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    # Sibling file seeds Pass 1 runtime name evidence for an invented name absent from dev/input
    (inp / "roster.json").write_text(
        json.dumps({"patient_name": "Niharika Chatterjee", "patient_ref": "ZZQ/41/00091"}),
        encoding="utf-8",
    )
    csv_text = (
        "col0,col7,field_b,field_c,col_addr,col_pin,col_mail\n"
        "ZZQ/41/00091,Niharika Chatterjee,+91 9000012345,4819 2736 5014,"
        "\"H.No. 9182, Mohalla Xylonagar, near Xylotower, Tehsil Zoraganj, Distt. Nebulapur\",209801,niharika@example.org\n"
    )
    (inp / "unknown_cols.csv").write_text(csv_text, encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    rows = list(csv.reader(io.StringIO((out / "sanitized" / "unknown_cols.csv").read_text(encoding="utf-8"))))
    assert rows[0] == ["col0", "col7", "field_b", "field_c", "col_addr", "col_pin", "col_mail"]
    r = rows[1]
    assert r[0].startswith("PSN-")
    assert r[1] == PLACEHOLDERS["PATIENT_NAME"]
    assert r[2] == PLACEHOLDERS["PHONE"]
    assert r[3] == PLACEHOLDERS["AADHAAR"]
    assert "9182" not in r[4] and "Xylonagar" not in r[4] and "Xylotower" not in r[4]
    assert "Distt. Nebulapur" in r[4]
    assert r[5] == "209***"
    assert r[6] == PLACEHOLDERS["EMAIL"]


def test_r5_adjacent_address_part_columns_and_no_overredaction(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    csv_text = (
        "col_vit,col_dose,col_date,col_vil,col_h,col_loc,col_land,col_p\n"
        "120/80,500 mg BD,14-05-2026,village Gopalpur,42/A,Mohalla Xylonagar,near Xylotower,209801\n"
        "118/76,250 mg OD,18-05-2026,village Gopalpur,15-B,Sector 4,opp. Town Hall,209802\n"
    )
    (inp / "mixed.csv").write_text(csv_text, encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    rows = list(csv.reader(io.StringIO((out / "sanitized" / "mixed.csv").read_text(encoding="utf-8"))))
    # Clinical columns & visit dates under unknown headers are never redacted
    assert rows[1][0] == "120/80"
    assert rows[1][1] == "500 mg BD"
    assert rows[1][2] != PLACEHOLDERS["DOB"] and len(rows[1][2]) == 10
    # Adjacent address-part columns under unknown headers are caught by shape + adjacency
    assert rows[1][4] == PLACEHOLDERS["HOUSE"]
    assert rows[1][5] == PLACEHOLDERS["LOCALITY"]
    assert rows[1][6] == PLACEHOLDERS["LANDMARK"]
    assert rows[1][7] == "209***"


def test_r5_non_patient_id_under_unknown_header_never_links(tmp_path: Path) -> None:
    # Unlabelled transaction/visit column varies per visit for one patient; must never merge two people.
    header = ["col_pat", "col_evt", "patient_name"]
    body = [
        ["ZZQ/41/00091", "EVT-1001", "Niharika Chatterjee"],
        ["ZZQ/41/00091", "EVT-1002", "Niharika Chatterjee"],
    ]
    cols = classify_csv_columns(header, body, ChannelEvidence())
    assert find_non_patient_mrn_cols(header, body, cols) == {1}

    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "visits.csv").write_text(
        "uhid,col_evt,patient_name\n"
        "ZZQ/41/00091,EVT-1001,Niharika Chatterjee\n"
        "ZZQ/41/00091,EVT-1002,Niharika Chatterjee\n",
        encoding="utf-8",
    )
    (inp / "other.csv").write_text(
        "uhid,col_evt,patient_name\nZZQ/41/00099,EVT-1001,Devesh Menon\n",
        encoding="utf-8",
    )
    res = run_pipeline(inp, out, _TEST_SECRET, load_policy())
    psns_niharika = {r["patient"] for r in res.records if "visits.csv" in r["file"]}
    psns_devesh = {r["patient"] for r in res.records if "other.csv" in r["file"]}
    assert len(psns_niharika) == 1 and len(psns_devesh) == 1
    assert psns_niharika != psns_devesh


def test_r5_empty_and_header_only_csv(tmp_path: Path) -> None:
    assert classify_csv_columns([], [], ChannelEvidence()) == []
    assert classify_csv_columns(["col7", "col8"], [], ChannelEvidence()) == ["FREE_TEXT", "FREE_TEXT"]

    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "hdr_only.csv").write_text("col7,col8\n", encoding="utf-8")
    (inp / "empty.csv").write_text("", encoding="utf-8")

    res = run_pipeline(inp, out, _TEST_SECRET, load_policy())
    assert res.report["counts"]["files_sanitized"] == 1
    assert res.report["counts"]["files_quarantined"] == 1
    assert (out / "sanitized" / "hdr_only.csv").read_text(encoding="utf-8").strip() == "col7,col8"


def test_r5_json_nested_modifiers_int_id_and_address_shapes(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {
        "hosp_no": "ZZQ/41/00091",
        "full_name": {"first": "Niharika", "last": "Chatterjee", "local": "निहारिका चटर्जी"},
        "ids": {"uid_field": 481927365014},
        "residence_line": "H.No. 9182, Mohalla Xylonagar, near Xylotower, Tehsil Zoraganj, Distt. Nebulapur",
        "clinical": {"observation": "Hemoglobin 13.4 g/dL, BP 118/78 mmHg"},
    }
    (inp / "rec.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "rec.json").read_text(encoding="utf-8"))
    assert san["hosp_no"].startswith("PSN-")
    assert san["full_name"] == {
        "first": PLACEHOLDERS["PATIENT_NAME"],
        "last": PLACEHOLDERS["PATIENT_NAME"],
        "local": PLACEHOLDERS["PATIENT_NAME"],
    }
    assert san["ids"]["uid_field"] == 0
    assert "9182" not in san["residence_line"] and "Xylonagar" not in san["residence_line"]
    assert "Distt. Nebulapur" in san["residence_line"]
    assert san["clinical"]["observation"] == "Hemoglobin 13.4 g/dL, BP 118/78 mmHg"


def test_r5_column_classification_scales_linearly() -> None:
    ev = ChannelEvidence()
    ev.add_name("Niharika Chatterjee", "PATIENT_NAME")
    header = ["col0", "col1", "col2", "col3", "col4", "col5", "col6", "col7"]
    base_row = [
        "ZZQ/41/00091",
        "Niharika Chatterjee",
        "9000012345",
        "4819 2736 5014",
        "H.No. 9182, Mohalla Xylonagar, Distt. Nebulapur",
        "209801",
        "500 mg BD",
        "120/80",
    ]
    timings: list[float] = []
    for n_rows in (100, 1000, 10000):
        rows = [base_row] * n_rows

        def _run() -> None:
            cols = classify_csv_columns(header, rows, evidence=ev)
            assert cols[0] == "MRN" and cols[1] == "PATIENT_NAME" and cols[2] == "PHONE"
            assert cols[4] == "ADDRESS" and cols[6] == "FREE_TEXT"

        timings.append(_best_elapsed_seconds(_run))

    # Sample cap bounds classification; 100x input rows must stay within 5x of 100-row baseline
    assert timings[2] <= max(0.05, timings[0] * 5.0), timings


def test_r5_r8_name_modifier_alone_does_not_name_timestamp_or_language_keys(tmp_path: Path) -> None:
    # Hand-derived: "last"/"local" without a name word ("lastUpdated", "local_language") names a
    # timestamp or a language, not a person (FHIR meta.lastUpdated is an instant). Only the
    # name-bearing key is PII. Invented patient name, absent from dev/input.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {
        "patient_name": "Tarunesh Vadhwal",
        "lastUpdated": "2026-03-01T10:00:00Z",
        "local_language": "Hindi",
    }
    (inp / "rec.json").write_text(json.dumps(doc), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "rec.json").read_text(encoding="utf-8"))
    assert san["patient_name"] == PLACEHOLDERS["PATIENT_NAME"]
    assert san["lastUpdated"] != PLACEHOLDERS["PATIENT_NAME"]
    assert san["lastUpdated"].endswith("T10:00:00Z")  # still an instant (shifted date, same format)
    assert san["local_language"] == "Hindi"


def test_r5_r8_clinical_prose_in_json_notes_is_not_an_address(tmp_path: Path) -> None:
    # Hand-derived: notes with no person, ID or place value must survive unchanged (R8, no
    # over-redaction). "near" + a symptom and "district hospital" are clinical prose, not an
    # address part; an address needs a place value, not only a cue word.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {
        "notes": "Admitted via casualty, near drowning",
        "remarks": "Referred from district hospital for further management.",
    }
    (inp / "rec.json").write_text(json.dumps(doc), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "rec.json").read_text(encoding="utf-8"))
    assert san["notes"] == doc["notes"]
    assert san["remarks"] == doc["remarks"]


def test_r5_r8_free_text_keys_and_bare_address_cues_preserve_prose(tmp_path: Path) -> None:
    # Free-text keys (complaints/history/notes/remarks) use text cleaners only; unknown keys with
    # bare cue words lacking a place value are never misclassified as address parts.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {
        "complaints": "Dyspnea, near syncope, H.No. mention only without digit",
        "history": "Referred from Tehsil Hospital, sector wise camp.",
        "col_unknown": "Admitted via casualty, near drowning; district policy applies",
        "col_bare": "District",
    }
    (inp / "notes.json").write_text(json.dumps(doc), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "notes.json").read_text(encoding="utf-8"))
    assert san == doc


def test_r5_pass1_and_pass2_csv_slot_decisions_agree() -> None:
    ev = ChannelEvidence()
    ev.add_name("Tarunesh Vadhwal", "PATIENT_NAME")
    header = ["col_pat", "col_evt", "col_who"]
    body = [
        ["ZZQ/41/00091", "EVT-1001", "Tarunesh Vadhwal"],
        ["ZZQ/41/00091", "EVT-1002", "Tarunesh Vadhwal"],
    ]
    pass1_cols = classify_csv_columns(header, body, ev)
    # Emulate Pass 2 after same evidence is enriched; slot/ID column assignments stay identical.
    ev.add_mrn("ZZQ/41/00091")
    pass2_cols = classify_csv_columns(header, body, ev)
    assert pass1_cols == ["MRN", "MRN", "PATIENT_NAME"]
    assert pass2_cols == pass1_cols
    assert find_non_patient_mrn_cols(header, body, pass1_cols) == {1}
    assert find_non_patient_mrn_cols(header, body, pass2_cols) == {1}


def test_r5_facility_header_with_unique_ids_pseudonymised_and_facility_names_kept(tmp_path: Path) -> None:
    # Req 1 & 3: A PRESERVE_EXACT/facility-word header holding high-cardinality strict R6 IDs
    # is promoted to MRN and pseudonymised; a column of facility names stays preserved.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    csv_text = (
        "Hospital Number,Facility Name,Patient Name\n"
        "VND/88/00101,Vindhyanagar Medical Centre,Tarunesh Vadhwal\n"
        "VND/88/00102,Narmadapur Primary Clinic,Ilavani Deshkoter\n"
        "VND/88/00103,Vindhyanagar Medical Centre,Raghavendra Kulkarni\n"
    )
    (inp / "fac_ids.csv").write_text(csv_text, encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    rows = list(csv.reader(io.StringIO((out / "sanitized" / "fac_ids.csv").read_text(encoding="utf-8"))))
    assert [r[0].startswith("PSN-") for r in rows[1:]] == [True, True, True]
    assert len({r[0] for r in rows[1:]}) == 3
    assert [r[1] for r in rows[1:]] == [
        "Vindhyanagar Medical Centre",
        "Narmadapur Primary Clinic",
        "Vindhyanagar Medical Centre",
    ]


def test_r5_house_abbreviations_hno_variants_caught_by_locked_vocab_rule(tmp_path: Path) -> None:
    # Req 2 & 3: "H.No. 42", "H. No. 42", "H No 42" all match via _HOUSE_TOKENS ("hno") rule.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    doc = {
        "slot_a": "H.No. 42",
        "slot_b": "H. No. 42",
        "slot_c": "H No 42",
        "slot_full": "H. No. 42, Mohalla Xylonagar, Distt. Nebulapur",
    }
    (inp / "houses.json").write_text(json.dumps(doc), encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    san = json.loads((out / "sanitized" / "houses.json").read_text(encoding="utf-8"))
    assert san["slot_a"] == PLACEHOLDERS["HOUSE"]
    assert san["slot_b"] == PLACEHOLDERS["HOUSE"]
    assert san["slot_c"] == PLACEHOLDERS["HOUSE"]
    assert "42" not in san["slot_full"] and "Xylonagar" not in san["slot_full"]
    assert "Distt. Nebulapur" in san["slot_full"]


def test_r5_low_cardinality_facility_codes_stay_preserved_while_patient_ids_psn(tmp_path: Path) -> None:
    # Req 4: Low-cardinality repeated facility/department codes under a facility header stay byte-identical;
    # high-cardinality patient IDs under a facility header are pseudonymised (CSV + JSON records).
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    csv_text = (
        "Hospital ID,Facility Code,Patient Name\n"
        "KPR/77/00011,FAC-8101,Tarunesh Vadhwal\n"
        "KPR/77/00012,FAC-8101,Ilavani Deshkoter\n"
        "KPR/77/00013,FAC-8102,Raghavendra Kulkarni\n"
        "KPR/77/00014,FAC-8102,Sunanda Gokhale\n"
        "KPR/77/00015,FAC-8101,Devika Suryavanshi\n"
        "KPR/77/00016,FAC-8102,Pranav Agnihotri\n"
    )
    (inp / "dept.csv").write_text(csv_text, encoding="utf-8")
    (inp / "batch.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"hospital_no": "KPR/77/00011", "facility_id": "FAC-8101", "name": "Tarunesh Vadhwal"},
                    {"hospital_no": "KPR/77/00012", "facility_id": "FAC-8101", "name": "Ilavani Deshkoter"},
                    {"hospital_no": "KPR/77/00013", "facility_id": "FAC-8102", "name": "Raghavendra Kulkarni"},
                    {"hospital_no": "KPR/77/00014", "facility_id": "FAC-8102", "name": "Sunanda Gokhale"},
                    {"hospital_no": "KPR/77/00015", "facility_id": "FAC-8101", "name": "Devika Suryavanshi"},
                    {"hospital_no": "KPR/77/00016", "facility_id": "FAC-8102", "name": "Pranav Agnihotri"},
                ]
            }
        ),
        encoding="utf-8",
    )

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    rows = list(csv.reader(io.StringIO((out / "sanitized" / "dept.csv").read_text(encoding="utf-8"))))
    assert all(r[0].startswith("PSN-") for r in rows[1:])
    assert [r[1] for r in rows[1:]] == ["FAC-8101", "FAC-8101", "FAC-8102", "FAC-8102", "FAC-8101", "FAC-8102"]

    san_json = json.loads((out / "sanitized" / "batch.json").read_text(encoding="utf-8"))
    assert all(e["hospital_no"].startswith("PSN-") for e in san_json["entries"])
    assert [e["facility_id"] for e in san_json["entries"]] == [
        "FAC-8101", "FAC-8101", "FAC-8102", "FAC-8102", "FAC-8101", "FAC-8102"
    ]


def test_r5_tie_break_half_distinct_patient_ids_under_facility_header_are_pseudonymised(tmp_path: Path) -> None:
    # Privacy-first tie-break: each invented patient appears exactly twice, so the ID column is
    # exactly half distinct (3 of 6). distinct >= COLUMN_ID_MIN_CARDINALITY_RATIO * values (0.5 * 6 = 3)
    # holds, so the facility-word header is overruled and every value becomes a PSN, never kept raw.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    ids = ["QMT/52/00701", "QMT/52/00701", "QMT/52/00702", "QMT/52/00702", "QMT/52/00703", "QMT/52/00703"]
    names = ["Oruvel Tamsika", "Oruvel Tamsika", "Jharvin Pelloti", "Jharvin Pelloti", "Saunika Drevar", "Saunika Drevar"]
    csv_text = "Hospital ID,Patient Name\n" + "".join(f"{i},{n}\n" for i, n in zip(ids, names))
    (inp / "repeat_visits.csv").write_text(csv_text, encoding="utf-8")
    (inp / "repeat_visits.json").write_text(
        json.dumps({"entries": [{"hospital_no": i, "name": n} for i, n in zip(ids, names)]}),
        encoding="utf-8",
    )

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    rows = list(csv.reader(io.StringIO((out / "sanitized" / "repeat_visits.csv").read_text(encoding="utf-8"))))
    csv_ids = [r[0] for r in rows[1:]]
    san_json = json.loads((out / "sanitized" / "repeat_visits.json").read_text(encoding="utf-8"))
    json_ids = [e["hospital_no"] for e in san_json["entries"]]
    for got in (csv_ids, json_ids):
        assert all(v.startswith("PSN-") for v in got), got
        assert not any(raw in got for raw in ids)
        # the two rows of one patient carry one pseudonym; different patients get different ones
        assert got[0] == got[1] and got[2] == got[3] and got[4] == got[5]
        assert len({got[0], got[2], got[4]}) == 3


def test_r5_r8_medical_dose_lab_drug_and_ambiguous_columns_stay_byte_identical(tmp_path: Path) -> None:
    # Req 5: medical > strict R6 ID w/ high cardinality > header meaning.
    # Dose, lab values, frequency/cadence, short drug codes, and mixed ambiguous cols stay unchanged.
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    csv_text = (
        "Hospital No,Dosage,Lab Result,Drug Code,Clinical Note Col,Col Mixed\n"
        "ZRN-44001,650mg,245 mg/dL,PCM-650,BD x 5 days,PCM-650\n"
        "ZRN-44002,500 mg,7.2 %,AMX-500,OD x 7 days,650mg\n"
        "ZRN-44003,1-0-1,13.8 g/dL,AZM-500,BD x 3 days,Vindhyanagar Clinic\n"
        "ZRN-44004,BD x 5 days,98.6 IU,MET-500,1-0-1,ZRN-44991\n"
    )
    (inp / "rx.csv").write_text(csv_text, encoding="utf-8")

    run_pipeline(inp, out, _TEST_SECRET, load_policy())
    rows = list(csv.reader(io.StringIO((out / "sanitized" / "rx.csv").read_text(encoding="utf-8"))))
    orig = list(csv.reader(io.StringIO(csv_text)))
    assert all(r[0].startswith("PSN-") for r in rows[1:])
    # Hand-derived (R6, MISTAKES "every ID value is replaced by the PSN or redacted"): the MRN-shaped
    # 'ZRN-44991' in the mixed column is an identifier, so it is redacted; every other cell is clinical.
    expected = [r[1:] for r in orig[1:]]
    expected[3][4] = PLACEHOLDERS["MRN"]
    assert [r[1:] for r in rows[1:]] == expected


def _write_bulk_csv(inp: Path, n_rows: int) -> None:
    # Invented shapes: a repeated facility code, a per-patient ID, a per-visit ref, a dose.
    lines = ["Facility Code,Hospital ID,Visit Ref,Dosage"]
    lines += [f"FAC-81{j % 3},KPR/77/{j:06d},EVT-{j},650mg" for j in range(n_rows)]
    (inp / "bulk.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_r5_r20_column_decisions_are_made_once_per_column_not_per_row(tmp_path: Path, monkeypatch) -> None:
    # The override vote is a per-column decision: its call count must not grow with the row count
    # (a per-row re-vote made a 10k-row CSV 25x slower). Spy only counts, then calls the real function.
    import wards.columns as columns_mod

    real = columns_mod.resolve_preserve_exact_override
    counts: list[int] = []
    for n_rows in (50, 2000):
        calls = {"n": 0}

        def _spy(cells, _real=real, _calls=calls):
            _calls["n"] += 1
            return _real(cells)

        monkeypatch.setattr(columns_mod, "resolve_preserve_exact_override", _spy)
        inp = tmp_path / f"in{n_rows}"
        inp.mkdir()
        _write_bulk_csv(inp, n_rows)
        run_pipeline(inp, tmp_path / f"out{n_rows}", _TEST_SECRET, load_policy())
        counts.append(calls["n"])
    monkeypatch.setattr(columns_mod, "resolve_preserve_exact_override", real)
    assert counts[0] > 0
    assert counts[0] == counts[1], counts


def test_r5_r20_whole_pipeline_csv_scales_linearly(tmp_path: Path) -> None:
    # Whole pipeline (Pass 1 + Pass 2) on 500 / 2,000 / 8,000 rows, best of 3 each.
    # 16x the rows may cost at most 16 x 1.6 = 25.6x the time (linear with noise headroom).
    timings: list[float] = []
    for n_rows in (500, 2000, 8000):
        inp = tmp_path / f"in{n_rows}"
        inp.mkdir()
        _write_bulk_csv(inp, n_rows)
        run_no = {"k": 0}

        def _run(_inp=inp, _n=n_rows, _r=run_no) -> None:
            _r["k"] += 1
            run_pipeline(_inp, tmp_path / f"out{_n}_{_r['k']}", _TEST_SECRET, load_policy())

        timings.append(_best_elapsed_seconds(_run))
    assert timings[1] <= timings[0] * 4 * 1.6, timings
    assert timings[2] <= timings[0] * 16 * 1.6, timings
