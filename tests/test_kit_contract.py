"""Kit integration tests: validate_output, check_dev, check_submission, R3 shape diff, and spike check."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from wards.config import FILENAME_PLACEHOLDERS, PLACEHOLDERS
from wards.ingest import decode_bytes, is_json_content, json_pointer_unescape


def _compare_json_shape(inp_val: Any, san_val: Any, path: str = "$") -> None:
    assert type(inp_val) is type(san_val), f"type mismatch at {path}: {type(inp_val)} vs {type(san_val)}"
    if isinstance(inp_val, dict):
        assert len(inp_val) == len(san_val), f"key count mismatch at {path}"
        for k_in, k_san in zip(inp_val.keys(), san_val.keys()):
            if k_in != k_san:
                assert any(ph in k_san for ph in PLACEHOLDERS.values()), f"unexpected non-PII key rename at {path}: {k_in} -> {k_san}"
            _compare_json_shape(inp_val[k_in], san_val[k_san], f"{path}.{k_san}")
    elif isinstance(inp_val, list):
        assert len(inp_val) == len(san_val), f"list length mismatch at {path}"
        for idx, (a, b) in enumerate(zip(inp_val, san_val)):
            _compare_json_shape(a, b, f"{path}[{idx}]")


def _resolve_pointer(doc: Any, pointer: str) -> Any:
    cur = doc
    for raw_tok in pointer.lstrip("/").split("/"):
        tok = json_pointer_unescape(raw_tok)
        if isinstance(cur, list):
            cur = cur[int(tok)]
        else:
            cur = cur[tok]
    return cur


def _contains_token(node: Any, token: str) -> bool:
    if isinstance(node, str):
        return token in node
    if isinstance(node, list):
        return any(_contains_token(item, token) for item in node)
    if isinstance(node, dict):
        return any(_contains_token(v, token) for v in node.values())
    return False


def test_kit_contract_shape_and_spike(tmp_path: Path, repo_root: Path, kit_dir: Path) -> None:
    dev_input = kit_dir / "dev" / "input"
    out_dir = tmp_path / "dev_out"
    env = dict(os.environ, RAKSHA_SECRET="practice")
    # Kit tools print emoji; force UTF-8 stdio so a cp1252 console pipe does not crash them.
    kit_env = dict(env, PYTHONIOENCODING="utf-8")

    run_proc = subprocess.run(
        [sys.executable, str(repo_root / "main.py"), "--input", str(dev_input), "--output", str(out_dir)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert run_proc.returncode == 0, run_proc.stderr

    # 1. validate_output.py -> CONTRACT OK with 0 WARN
    val_proc = subprocess.run(
        [
            sys.executable,
            str(kit_dir / "validate_output.py"),
            "--input",
            str(dev_input),
            "--output",
            str(out_dir),
        ],
        cwd=repo_root,
        env=kit_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert val_proc.returncode == 0, val_proc.stdout + val_proc.stderr
    assert "CONTRACT OK" in val_proc.stdout
    assert "WARN" not in val_proc.stdout

    # 2. check_dev.py -> RAW COPIES: 0, MEDICAL DATA KEPT >= 97%, and slice-2b name reductions
    dev_proc = subprocess.run(
        [sys.executable, str(kit_dir / "check_dev.py"), "--output", str(out_dir)],
        cwd=repo_root,
        env=kit_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert dev_proc.returncode == 0, dev_proc.stdout + dev_proc.stderr
    assert "RAW COPIES: 0" in dev_proc.stdout
    med_match = re.search(r"MEDICAL DATA KEPT:.*?(\d+\.\d+)%", dev_proc.stdout)
    assert med_match is not None, dev_proc.stdout
    assert float(med_match.group(1)) >= 97.0

    overall_match = re.search(r"PERSONAL DATA:.*?\(\s*(\d+\.\d+)% leaked", dev_proc.stdout)
    pname_match = re.search(r"PATIENT_NAME\s+leaked\s+\d+\s*/\s*\d+\s+(\d+\.\d+)%", dev_proc.stdout)
    canary_match = re.search(r"CANARIES:\s+(\d+)\s+of\s+(\d+)", dev_proc.stdout)
    lang_match = re.search(r"by language:.*?deva\s+(\d+\.\d+)%,\s*hinglish\s+(\d+\.\d+)%", dev_proc.stdout)
    assert overall_match and pname_match and canary_match and lang_match, dev_proc.stdout
    assert float(overall_match.group(1)) < 16.0
    assert float(pname_match.group(1)) < 33.9
    assert int(canary_match.group(1)) < 3
    assert float(lang_match.group(1)) < 100.0
    assert float(lang_match.group(2)) < 100.0

    # 3. check_submission.py --repo . --run -> READY TO SUBMIT
    sub_proc = subprocess.run(
        [sys.executable, str(kit_dir / "check_submission.py"), "--repo", str(repo_root), "--run"],
        cwd=repo_root,
        env=kit_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert sub_proc.returncode == 0, sub_proc.stdout + sub_proc.stderr
    assert "READY TO SUBMIT" in sub_proc.stdout

    # 4. Shape diff: every sanitized file vs input has 0 structural/line/type differences (R3),
    # allowing only PII renames on filenames, headers, and keys (R9)
    import hashlib

    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    counts = report["counts"]
    assert counts["files_total"] == len(report["files"])
    assert counts["files_sanitized"] + counts["files_quarantined"] == counts["files_total"]

    inp_by_sha: dict[str, list[str]] = {}
    for p in sorted((p for p in dev_input.rglob("*") if p.is_file()), key=lambda p: p.relative_to(dev_input).as_posix()):
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        inp_by_sha.setdefault(sha, []).append(p.relative_to(dev_input).as_posix())
    sha_cursor: dict[str, int] = {}

    sanitized_dir = out_dir / "sanitized"
    for entry in report["files"]:
        if entry["status"] != "sanitized":
            continue
        sha = entry["input_sha256"]
        idx = sha_cursor.get(sha, 0)
        sha_cursor[sha] = idx + 1
        inp_rel = inp_by_sha[sha][idx]
        out_rel = str(entry["output"]).replace("sanitized/", "", 1)

        inp_file = dev_input / inp_rel
        san_file = sanitized_dir / out_rel
        assert san_file.is_file()
        assert Path(out_rel).suffix == Path(inp_rel).suffix
        if out_rel != inp_rel:
            assert not inp_rel.startswith("clean/"), f"clean file renamed: {inp_rel} -> {out_rel}"
            assert any(ph in out_rel for ph in FILENAME_PLACEHOLDERS.values()), f"non-PII rename: {out_rel}"

        inp_text = decode_bytes(inp_file.read_bytes())
        assert inp_text is not None
        san_text = san_file.read_text(encoding="utf-8")

        ext = inp_file.suffix.lower()
        if ext == ".json" or (ext in (".csv", ".tsv") and is_json_content(inp_text)):
            _compare_json_shape(json.loads(inp_text), json.loads(san_text), out_rel)
        elif ext in (".csv", ".tsv"):
            delim = "\t" if ext == ".tsv" else ","
            inp_rows = list(csv.reader(io.StringIO(inp_text, newline=""), delimiter=delim))
            san_rows = list(csv.reader(io.StringIO(san_text, newline=""), delimiter=delim))
            assert len(inp_rows) == len(san_rows), f"row count mismatch in {out_rel}"
            assert len(inp_rows[0]) == len(san_rows[0]), f"header count mismatch in {out_rel}"
            for h_in, h_san in zip(inp_rows[0], san_rows[0]):
                if h_in != h_san:
                    assert any(ph in h_san for ph in PLACEHOLDERS.values()), f"non-PII header rename in {out_rel}"
            assert [len(r) for r in inp_rows] == [len(r) for r in san_rows], f"col count mismatch in {out_rel}"
        else:
            assert len(inp_text.splitlines()) == len(san_text.splitlines()), f"line count mismatch in {out_rel}"

    # 5. Spike check: >= 95% of non-null records.jsonl claims appear inside their exported record
    records = [
        json.loads(line)
        for line in (out_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert counts["records_processed"] == len(records)
    non_null = [r for r in records if r["patient"] is not None]
    assert counts["records_linked"] == len(non_null)
    assert len(non_null) > 0

    found = 0
    json_cache: dict[str, Any] = {}
    csv_cache: dict[str, list[list[str]]] = {}
    text_cache: dict[str, str] = {}

    for rec in non_null:
        rel_out = rec["file"]
        san_file = out_dir / rel_out
        psn = rec["patient"]
        loc = rec["loc"]

        if loc.startswith("row:"):
            if rel_out not in csv_cache:
                delim = "\t" if san_file.suffix.lower() == ".tsv" else ","
                csv_cache[rel_out] = list(csv.reader(io.StringIO(san_file.read_text(encoding="utf-8"), newline=""),
                                                     delimiter=delim))
            row_idx = int(loc.split(":", 1)[1]) + 1
            if psn in csv_cache[rel_out][row_idx]:
                found += 1
        elif loc.startswith("/"):
            if rel_out not in json_cache:
                json_cache[rel_out] = json.loads(san_file.read_text(encoding="utf-8"))
            subtree = _resolve_pointer(json_cache[rel_out], loc)
            if _contains_token(subtree, psn):
                found += 1
        else:
            if rel_out not in text_cache:
                text_cache[rel_out] = san_file.read_text(encoding="utf-8")
            if psn in text_cache[rel_out]:
                found += 1

    assert found / len(non_null) >= 0.95
