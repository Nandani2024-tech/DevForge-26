"""Tests for R17 side-channel privacy across stdout, stderr, report.json, records.jsonl, and errors."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from wards import pipeline
from wards.config import load_policy


def test_r17_no_pii_or_secret_in_side_channels(tmp_path: Path, repo_root: Path) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    priv_tmp = tmp_path / "priv_tmp"
    priv_tmp.mkdir()
    folder = inp / "clinic_batch"
    folder.mkdir(parents=True)

    pii_tokens = [
        "CanaryPerson",
        "9876543210",
        "8265 7330 7111",
        "ABCDE1234F",
        "canary.user@example.org",
        "RampurKalan",
        "top-secret-fixture-key",
    ]
    (folder / "visit_01.csv").write_text(
        "UHID,Patient Name,Village,Phone,Aadhaar,PAN,Email\n"
        "CLI-50001,CanaryPerson,RampurKalan,9876543210,8265 7330 7111,ABCDE1234F,canary.user@example.org\n",
        encoding="utf-8",
    )

    env = dict(
        os.environ,
        RAKSHA_SECRET="top-secret-fixture-key",
        PYTHONIOENCODING="utf-8",
        TMPDIR=str(priv_tmp),
        TEMP=str(priv_tmp),
        TMP=str(priv_tmp),
    )
    proc = subprocess.run(
        [sys.executable, str(repo_root / "main.py"), "--input", str(inp), "--output", str(out)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr

    side_blobs = [
        proc.stdout,
        proc.stderr,
        (out / "report.json").read_text(encoding="utf-8"),
        (out / "records.jsonl").read_text(encoding="utf-8"),
    ]
    for f in priv_tmp.rglob("*"):
        if f.is_file():
            side_blobs.append(f.read_text(encoding="utf-8", errors="replace"))

    combined = "\n".join(side_blobs)
    for token in pii_tokens:
        assert token not in combined, f"side channel leaked {token!r}"


def test_cleaning_error_quarantines_without_echoing_message(tmp_path: Path, monkeypatch) -> None:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    secret_surface = "SENSITIVE_SURFACE_9988776655"
    (inp / "note.txt").write_text(f"Note: {secret_surface}\n", encoding="utf-8")

    def boom(_parsed, _make_psn, _stats):
        raise ValueError(f"failed near {secret_surface}")

    monkeypatch.setattr(pipeline, "_process_text", boom)
    res = pipeline.run_pipeline(inp=inp, out=out, secret=b"err-secret", policy=load_policy())

    entry = res.report["files"][0]
    assert entry["status"] == "quarantined"
    assert entry["output"] is None
    assert entry["reason"] == "processing_error"
    assert secret_surface not in json.dumps(res.report)
    assert not (out / "sanitized" / "note.txt").exists()
