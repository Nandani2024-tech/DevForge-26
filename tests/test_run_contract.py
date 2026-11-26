"""Run-contract tests: R17 (no input paths in stdout/stderr), R19 (byte determinism), R21 (input untouched)."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


def _write_inputs(inp: Path) -> None:
    # Folder and file names carry a fake patient name: a hidden channel (R9/R17).
    folder = inp / "Ramesh_Kumar_ward"
    folder.mkdir(parents=True)
    (folder / "visit.csv").write_text("UHID,Name,Hb\nHOSP0001,Ramesh Kumar,13.1\n", encoding="utf-8")
    (folder / "note.txt").write_text("UHID: HOSP0001\nPatient name: Ramesh Kumar\n", encoding="utf-8")
    (inp / "broken.pdf").write_bytes(b"%PDF-1.4\n")


def _run(repo_root: Path, inp: Path, out: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, RAKSHA_SECRET="unit-secret", PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(repo_root / "main.py"), "--input", str(inp), "--output", str(out)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_r17_stdout_stderr_carry_no_input_paths_or_secret(tmp_path: Path, repo_root: Path) -> None:
    inp = tmp_path / "in"
    _write_inputs(inp)
    proc = _run(repo_root, inp, tmp_path / "out")
    assert proc.returncode == 0, proc.stderr
    streams = proc.stdout + proc.stderr
    for forbidden in ("Ramesh", "Kumar", "visit", "note", "broken", "HOSP0001", "unit-secret"):
        assert forbidden not in streams, f"stdout/stderr leaks an input-derived token: {forbidden!r}"


def test_r19_two_runs_are_byte_identical(tmp_path: Path, repo_root: Path) -> None:
    inp = tmp_path / "in"
    _write_inputs(inp)
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    assert _run(repo_root, inp, out_a).returncode == 0
    assert _run(repo_root, inp, out_b).returncode == 0
    assert _tree_digest(out_a / "sanitized") == _tree_digest(out_b / "sanitized")
    assert (out_a / "records.jsonl").read_bytes() == (out_b / "records.jsonl").read_bytes()


def test_r21_input_folder_is_not_modified(tmp_path: Path, repo_root: Path) -> None:
    inp = tmp_path / "in"
    _write_inputs(inp)
    before = _tree_digest(inp)
    assert _run(repo_root, inp, tmp_path / "out").returncode == 0
    assert _tree_digest(inp) == before
