"""Edge-case, policy validation, quarantine, resource-sampling, and failure-exit tests."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from wards.config import PolicyError, load_policy
from wards.pipeline import run_pipeline
from wards.resources import MemorySampler


def test_policy_fails_closed_on_missing_and_invalid(tmp_path: Path) -> None:
    with pytest.raises(PolicyError) as missing_exc:
        load_policy(tmp_path / "does_not_exist.yaml")
    assert missing_exc.value.reason == "missing_policy_file"

    bad_range = tmp_path / "bad_range.yaml"
    bad_range.write_text(
        "age_band_years: 0\nage_top_code: 85\ndate_shift_max_days: 180\n"
        "date_shift_min_abs_days: 7\nlocation_level: district\npin_prefix_digits: 3\n"
        "min_group_size: 5\nrare_condition_max_profiles: 3\nrare_action: coarsen\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError) as range_exc:
        load_policy(bad_range)
    assert range_exc.value.reason == "invalid_policy_range"

    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text("age_band_years: 5\n", encoding="utf-8")
    with pytest.raises(PolicyError) as inc_exc:
        load_policy(incomplete)
    assert inc_exc.value.reason == "missing_policy_key"


def test_quarantine_edge_cases(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()

    (inp / "empty.csv").write_bytes(b"")
    (inp / "bad.json").write_text('{"visits": [{"a": 1', encoding="utf-8")
    (inp / "doc.pdf").write_bytes(b"%PDF-1.4\nfake\n")
    (inp / "img.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (inp / "note.xml").write_text("<doc><id>1</id></doc>", encoding="utf-8")
    (inp / "bad_bytes.txt").write_bytes(b"\x81\x8d\x90")
    (inp / "mislabeled.csv").write_text('{"uhid": "AB12345", "note": "ok"}', encoding="utf-8")
    (inp / "voted_col.csv").write_text("CustomKey,Note\nXYZ-9901,ok\nXYZ-9902,ok\n", encoding="utf-8")

    # 1,500-deep JSON must be caught and quarantined at Python's default recursion limit
    default_limit = sys.getrecursionlimit()
    deep_json = ('{"a":' * 1500) + "1" + ("}" * 1500)
    (inp / "deep.json").write_text(deep_json, encoding="utf-8")

    result = run_pipeline(inp=inp, out=out, secret=b"test-secret", policy=load_policy())
    assert sys.getrecursionlimit() == default_limit

    by_sha = {entry["input_sha256"]: entry for entry in result.report["files"]}
    empty_sha = hashlib.sha256(b"").hexdigest()
    assert by_sha[empty_sha]["status"] == "quarantined"
    assert by_sha[empty_sha]["output"] is None
    assert by_sha[empty_sha]["reason"] == "empty_file"

    deep_sha = hashlib.sha256(deep_json.encode("utf-8")).hexdigest()
    assert by_sha[deep_sha]["status"] == "quarantined"
    assert by_sha[deep_sha]["reason"] == "deep_json"

    for fname in ("bad.json", "doc.pdf", "img.jpg", "note.xml", "bad_bytes.txt"):
        sha = hashlib.sha256((inp / fname).read_bytes()).hexdigest()
        assert by_sha[sha]["status"] == "quarantined"
        assert by_sha[sha]["output"] is None
        assert not (out / "sanitized" / fname).exists()

    mislabeled_out = out / "sanitized" / "mislabeled.csv"
    assert mislabeled_out.is_file()
    parsed_mislabeled = json.loads(mislabeled_out.read_text(encoding="utf-8"))
    assert parsed_mislabeled["uhid"].startswith("PSN-")

    voted_out = (out / "sanitized" / "voted_col.csv").read_text(encoding="utf-8")
    assert "PSN-" in voted_out and "XYZ-9901" not in voted_out


def test_duplicate_byte_identical_files(tmp_path: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    payload = b"UHID,Name\nHOSP001,Asha\n"
    (inp / "a.csv").write_bytes(payload)
    (inp / "a_copy.csv").write_bytes(payload)

    result = run_pipeline(inp=inp, out=out, secret=b"dup-secret", policy=load_policy())
    assert result.report["counts"]["files_total"] == 2
    assert result.report["counts"]["files_sanitized"] == 2
    outputs = sorted(e["output"] for e in result.report["files"])
    assert outputs == ["sanitized/a.csv", "sanitized/a_copy.csv"]
    assert (out / "sanitized" / "a.csv").read_bytes() == (out / "sanitized" / "a_copy.csv").read_bytes()


def test_missing_secret_exits_nonzero_without_report(tmp_path: Path, repo_root: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "a.txt").write_text("UHID: H1001\n", encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if k != "RAKSHA_SECRET"}
    proc = subprocess.run(
        [sys.executable, str(repo_root / "main.py"), "--input", str(inp), "--output", str(out)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert not (out / "report.json").exists()


def test_bulk_export_linear_scaling(tmp_path: Path) -> None:
    timings: list[float] = []
    policy = load_policy()
    for n_rows in (1000, 10000):
        inp = tmp_path / f"in_{n_rows}"
        out = tmp_path / f"out_{n_rows}"
        inp.mkdir()
        records = [{"uhid": f"HSP{i:06d}", "test": "Hb", "value": 13.1} for i in range(n_rows)]
        (inp / "bulk.json").write_text(json.dumps({"results": records}), encoding="utf-8")
        t0 = time.monotonic()
        res = run_pipeline(inp=inp, out=out, secret=b"scale-secret", policy=policy)
        timings.append(time.monotonic() - t0)
        assert res.report["counts"]["records_processed"] == n_rows

    # Growth ratio, not absolute seconds (machine and suite-load independent): 10x records must
    # take <= 15x time; linear is ~10x, quadratic would be ~100x.
    assert timings[1] <= timings[0] * 15.0


def test_memory_sampler_positive_rss() -> None:
    with MemorySampler(interval_sec=0.02) as sampler:
        _ = bytearray(1024 * 1024)
        peak = sampler.stop()
    assert peak > 0.0
