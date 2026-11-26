"""Tests for R9 hidden-channel cleaning: filenames/folders, headers, keys, and export metadata."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import wards.pipeline as pipeline_mod
from wards.channels import (
    ChannelEvidence,
    build_output_rename_map,
    clean_channel_text,
    clean_csv_header,
    clean_dict_keys,
    clean_path_or_url,
    looks_like_path_or_url,
)
from wards.config import load_policy
from wards.ingest import json_pointer_escape, json_pointer_unescape
from wards.patterns import extract_phone_core
from wards.pipeline import run_pipeline


def test_r9_phone_and_pointer_oracles() -> None:
    assert extract_phone_core("098765 43210") == "9876543210"
    assert extract_phone_core("+91-98765-43210") == "9876543210"
    assert extract_phone_core("1-0-1") is None
    assert extract_phone_core("650mg") is None
    assert extract_phone_core("117/82") is None

    assert "/" + json_pointer_escape("a/b") == "/a~1b"
    assert "/" + json_pointer_escape("m~n") == "/m~0n"
    assert json_pointer_unescape("~01") == "~1"


def test_r9_filename_folder_and_clean_preservation(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    (inp / "clean").mkdir(parents=True)
    (inp / "Rohan_Kulkarni_ward").mkdir(parents=True)

    (inp / "clean" / "ward_protocol.txt").write_text("Paracetamol 650mg 1-0-1.\n", encoding="utf-8")
    (inp / "Rohan_Kulkarni_ward" / "summary_Rohan_Kulkarni_UHID-901234.txt").write_text(
        "Name: Rohan Kulkarni\nUHID: UHID-901234\nDiagnosis: viral fever\n",
        encoding="utf-8",
    )
    (inp / "9876543210_lab_report.txt").write_text("Mobile: 9876543210\nHb 13.2 g/dL\n", encoding="utf-8")

    policy = load_policy()
    result = run_pipeline(inp, out, b"channel-test-secret", policy)

    outputs = {e["output"] for e in result.report["files"] if e["status"] == "sanitized"}
    assert "sanitized/clean/ward_protocol.txt" in outputs
    for rel in outputs:
        assert "Rohan" not in rel
        assert "Kulkarni" not in rel
        assert "901234" not in rel
        assert "9876543210" not in rel
        assert rel.endswith(".txt")
        for bad_ch in '<>:"\\|?*':
            assert bad_ch not in rel


def test_r9_collisions_and_duplicate_sha_files(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    # Exact duplicate bytes in two different files -> both listed in report.json with distinct outputs
    dup_bytes = b"Name: Manish Joshi\nUHID: UHID-882211\n"
    (inp / "Manish_Joshi_copy_a.txt").write_bytes(dup_bytes)
    (inp / "Manish_Joshi_copy_b.txt").write_bytes(dup_bytes)

    # Two distinct files that clean to the exact same stem + pre-existing untouched collision target
    (inp / "PATIENT_NAME_PHONE.txt").write_text("No PII here.\n", encoding="utf-8")
    (inp / "Gaurav_Bhosale_9876543210.txt").write_text("Name: Gaurav Bhosale\nMob: 9876543210\n", encoding="utf-8")
    (inp / "Tarun_Solanki_9123456789.txt").write_text("Name: Tarun Solanki\nMob: 9123456789\n", encoding="utf-8")

    policy = load_policy()
    result = run_pipeline(inp, out, b"collision-secret", policy)

    sanitized_entries = [e for e in result.report["files"] if e["status"] == "sanitized"]
    assert len(sanitized_entries) == 5
    dup_sha = hashlib.sha256(dup_bytes).hexdigest()
    dup_entries = [e for e in sanitized_entries if e["input_sha256"] == dup_sha]
    assert len(dup_entries) == 2
    assert dup_entries[0]["output"] != dup_entries[1]["output"]

    out_paths = [e["output"] for e in sanitized_entries]
    assert len(set(out_paths)) == 5
    assert "sanitized/PATIENT_NAME_PHONE.txt" in out_paths


def test_r9_devanagari_names_digit_ids_and_doctor_kept() -> None:
    ev = ChannelEvidence()
    ev.add_name("कल्पना गोखले", "PATIENT_NAME")
    ev.add_name("Meera Kulkarni", "PATIENT_NAME")
    ev.add_mrn("ADM000999")

    cleaned_deva, cnt_deva = clean_channel_text("रिपोर्ट_कल्पना_गोखले_९८७६५४३२१०", ev, filename_safe=True)
    assert cnt_deva == 2
    assert "कल्पना" not in cleaned_deva and "गोखले" not in cleaned_deva
    assert "९८७६५४३२१०" not in cleaned_deva
    assert "PATIENT_NAME" in cleaned_deva and "PHONE" in cleaned_deva

    cleaned_id, cnt_id = clean_channel_text("nursing_adm000999_ipd-2026-00888", ev, filename_safe=True)
    assert cnt_id == 2
    assert "adm000999" not in cleaned_id and "ipd-2026-00888" not in cleaned_id

    # R8: Dr.-prefixed doctor names preserved even if a token collides with Pass 1 patient names
    cleaned_doc, cnt_doc = clean_channel_text("Dr_Meera_Kulkarni_round_notes", ev, filename_safe=True)
    assert cnt_doc == 0
    assert cleaned_doc == "Dr_Meera_Kulkarni_round_notes"


def test_r9_json_keys_collisions_headers_and_pointers(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    payload = {
        "Nikhil_Deshmukh_visits": [
            {
                "patient_id": "HSP-771122",
                "note": "Patient: Nikhil Deshmukh seen; attendant: Tarun Solanki",
                "path": "D:\\HIS\\exports\\Nikhil_Deshmukh_771122\\visit.json",
            }
        ],
        "by_uhid": {
            "HSP-771122": {"visits": 1},
            "HSP-771123": {"visits": 2},
        },
        "by_name": {
            "Nikhil Deshmukh": "HSP-771122",
            "Unknown Canary": "HSP-771123",
        },
    }
    (inp / "index.json").write_text(json.dumps(payload), encoding="utf-8")

    csv_content = "time,HSP-771122 Nikhil,HSP-771123 Tarun\n08:00,120/80,118/78\n"
    (inp / "vitals.csv").write_text(csv_content, encoding="utf-8")

    policy = load_policy()
    result = run_pipeline(inp, out, b"json-key-secret", policy)

    san_json = json.loads((out / "sanitized" / "index.json").read_text(encoding="utf-8"))
    top_keys = list(san_json.keys())
    assert len(top_keys) == 3
    assert "Nikhil" not in top_keys[0]
    assert len(san_json["by_uhid"]) == 2
    assert list(san_json["by_uhid"].keys()) == ["[MRN]", "[MRN]_2"]
    assert list(san_json["by_name"].keys()) == ["[PATIENT_NAME]", "[PATIENT_NAME]_2"]
    # Export path inside JSON stripped PII while preserving drive + filename
    cleaned_meta_path = san_json[top_keys[0]][0]["path"]
    assert "Nikhil" not in cleaned_meta_path and "771122" not in cleaned_meta_path
    assert cleaned_meta_path.startswith("D:\\HIS\\exports\\") and cleaned_meta_path.endswith("\\visit.json")

    # records.jsonl never holds the raw PII top-level key
    recs_text = (out / "records.jsonl").read_text(encoding="utf-8")
    assert "Nikhil" not in recs_text
    json_rec = [json.loads(line) for line in recs_text.splitlines() if "index.json" in line][0]
    assert json_rec["loc"] == f"/{json_pointer_escape(top_keys[0])}/0"

    # CSV headers preserve exact column count and non-PII header
    csv_lines = (out / "sanitized" / "vitals.csv").read_text(encoding="utf-8").splitlines()
    headers = csv_lines[0].split(",")
    assert len(headers) == 3
    assert headers[0] == "time"
    assert "Nikhil" not in csv_lines[0] and "HSP-771122" not in csv_lines[0]


def test_r9_metadata_value_shape_and_fhir_meta_source(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    assert looks_like_path_or_url("https://ward.example/exports/Rohan_Kulkarni/rec.json")
    assert looks_like_path_or_url("D:\\HIS\\exports\\Rohan_Kulkarni_098123\\doc.json")
    assert not looks_like_path_or_url("117/82")
    assert not looks_like_path_or_url("HSP/26/009999")

    bundle = {
        "resourceType": "Bundle",
        "id": "b-01",
        "type": "document",
        "meta": {"source": "https://hosp.example/exports/Rohan_Kulkarni_098123/bundle.json"},
        "entry": [
            {
                "fullUrl": "urn:uuid:11111111-1111-1111-1111-111111111111",
                "resource": {
                    "resourceType": "Patient",
                    "id": "p-01",
                    "identifier": [{"system": "https://hosp.example/uhid", "value": "UHID-098123"}],
                    "name": [{"text": "Rohan Kulkarni", "given": ["Rohan"], "family": "Kulkarni"}],
                },
            }
        ],
    }
    (inp / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")

    policy = load_policy()
    run_pipeline(inp, out, b"fhir-meta-secret", policy)

    out_bundle = json.loads((out / "sanitized" / "bundle.json").read_text(encoding="utf-8"))
    assert out_bundle["resourceType"] == "Bundle"
    assert out_bundle["entry"][0]["fullUrl"] == "urn:uuid:11111111-1111-1111-1111-111111111111"
    assert out_bundle["entry"][0]["resource"]["identifier"][0]["system"] == "https://hosp.example/uhid"
    assert "Rohan" not in out_bundle["meta"]["source"]
    assert "098123" not in out_bundle["meta"]["source"]
    assert out_bundle["meta"]["source"].startswith("https://hosp.example/exports/")


def test_r9_determinism_privacy_and_failure_no_echo(tmp_path: Path, repo_root: Path, monkeypatch) -> None:
    inp = tmp_path / "in"
    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"
    inp.mkdir()

    (inp / "Priya_Nair_9876543210.txt").write_text("Name: Priya Nair\nPhone: 9876543210\n", encoding="utf-8")

    env = dict(os.environ, RAKSHA_SECRET="det-channel-secret")
    for out_dir in (out_a, out_b):
        proc = subprocess.run(
            [sys.executable, str(repo_root / "main.py"), "--input", str(inp), "--output", str(out_dir)],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "Priya" not in proc.stdout + proc.stderr
        assert "9876543210" not in proc.stdout + proc.stderr

    # Byte-identical report outputs, renames, and records
    assert (out_a / "records.jsonl").read_bytes() == (out_b / "records.jsonl").read_bytes()
    rep_a = json.loads((out_a / "report.json").read_text(encoding="utf-8"))
    assert "Priya" not in json.dumps(rep_a)

    # Failure case: content processing error on a PII-named file quarantines without echoing filename or exception text
    out_err = tmp_path / "out_err"

    def _boom(*_args, **_kwargs):
        raise ValueError("secret_filename_echo_Priya_Nair")

    monkeypatch.setattr(pipeline_mod, "_process_text", _boom)
    res_err = run_pipeline(inp, out_err, b"det-channel-secret", load_policy())
    assert res_err.report["counts"]["files_quarantined"] == 1
    assert "Priya" not in json.dumps(res_err.report)
    assert "secret_filename_echo" not in json.dumps(res_err.report)


def test_r9_channel_cleaner_scales_linearly() -> None:
    ev = ChannelEvidence()
    ev.add_name("Rohan Kulkarni", "PATIENT_NAME")
    ev.add_mrn("UHID-901234")

    # 1. Per-string cleaner scaling: 10x input -> <= 18x time (linear = ~10x)
    seg = "Rohan_Kulkarni_UHID-901234_Dr_Meera_Kulkarni_note_"
    timings_text: list[float] = []
    for repeats in (200, 2000, 20000):
        payload = seg * repeats
        t0 = time.perf_counter()
        cleaned, cnt = clean_channel_text(payload, ev, filename_safe=True)
        elapsed = time.perf_counter() - t0
        assert cnt == 2 * repeats
        assert "Rohan" not in cleaned and "Dr_Meera_Kulkarni" in cleaned
        timings_text.append(elapsed)
    assert timings_text[2] <= max(0.2, timings_text[1] * 18.0), timings_text

    # 2. All-colliding rename map scaling: 200 -> 2,000 -> 20,000 colliding paths (amortised O(1))
    timings_map: list[float] = []
    for n_files in (200, 2000, 20000):
        paths = [f"Rohan_Kulkarni_UHID-{100000 + i}/report.txt" for i in range(n_files)]
        t0 = time.perf_counter()
        rmap = build_output_rename_map(paths, ev)
        elapsed = time.perf_counter() - t0
        assert len(set(rmap.values())) == n_files
        assert rmap[paths[0]] == "PATIENT_NAME_MRN/report.txt"
        assert rmap[paths[1]] == "PATIENT_NAME_MRN/report_2.txt"
        timings_map.append(elapsed)
    assert timings_map[2] <= max(0.3, timings_map[1] * 15.0), timings_map

    # 3. All-colliding dict key deduplication scaling: 1,000 -> 10,000 colliding keys (amortised O(1))
    timings_keys: list[float] = []
    for n_keys in (1000, 10000):
        keys = [f"HSP-{100000 + i}" for i in range(n_keys)]
        t0 = time.perf_counter()
        cleaned_keys, cnt = clean_dict_keys(keys, ev)
        elapsed = time.perf_counter() - t0
        assert cnt == n_keys
        assert len(set(cleaned_keys)) == n_keys
        assert cleaned_keys[0] == "[MRN]" and cleaned_keys[1] == "[MRN]_2"
        timings_keys.append(elapsed)
    assert timings_keys[1] <= max(0.2, timings_keys[0] * 15.0), timings_keys


def test_r9_r22_condition_year_filename_is_not_an_mrn() -> None:
    # Hand-derived: "<clinical word>-<4-digit year>" carries no ID label, no ID-meaning
    # prefix and no harvested MRN core, so it is not PII. The verdict must not depend
    # on whether the word happens to appear in the practice data's file names (R22).
    # Words chosen to be absent from dev/input file names.
    ev = ChannelEvidence()
    for stem in ("malaria-2026_summary", "typhoid-2025_followup", "asthma-2024_clinic_notes"):
        cleaned, cnt = clean_channel_text(stem, ev, filename_safe=True)
        assert (cleaned, cnt) == (stem, 0), stem


def test_r9_id_meaning_prefix_with_digits_is_still_an_mrn() -> None:
    # Hand-derived: an ID-meaning prefix (uhid/mrn) followed by a digit run is an MRN.
    ev = ChannelEvidence()
    cleaned, cnt = clean_channel_text("summary_uhid-4471", ev, filename_safe=True)
    assert cnt == 1 and "4471" not in cleaned
