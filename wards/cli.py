"""CLI entry point for Secret Wards."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from wards.config import PolicyError, load_policy, require_secret
from wards.pipeline import run_pipeline


def _clean_cli_path(raw: str) -> Path:
    """Allowed exception E1 (.hackathon/00-rules.md sec 13): strip Windows shlex.quote quotes."""
    if os.name == "nt" and len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return Path(raw[1:-1])
    return Path(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Secret Wards privacy firewall")
    parser.add_argument("--input", required=True, help="Read-only input directory")
    parser.add_argument("--output", required=True, help="Output directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    inp = _clean_cli_path(args.input)
    out = _clean_cli_path(args.output)

    try:
        secret = require_secret("RAKSHA_SECRET")
    except RuntimeError:
        print("error: RAKSHA_SECRET is required", file=sys.stderr)
        return 1

    if not inp.is_dir():
        print("error: input directory does not exist", file=sys.stderr)
        return 1

    try:
        policy = load_policy()
    except PolicyError as exc:
        print(f"error: {exc.reason}", file=sys.stderr)
        return 1

    report_path = out / "report.json"

    try:
        result = run_pipeline(inp=inp, out=out, secret=secret, policy=policy)
    except Exception as exc:  # noqa: BLE001 - fail closed without leaking content
        if report_path.exists():
            report_path.unlink(missing_ok=True)
        print(f"error: pipeline_failed ({type(exc).__name__})", file=sys.stderr)
        return 1

    if not (out / "sanitized").is_dir() or not report_path.is_file() or not (out / "records.jsonl").is_file():
        if report_path.exists():
            report_path.unlink(missing_ok=True)
        print("error: incomplete_output", file=sys.stderr)
        return 1

    counts = result.report["counts"]
    print(
        f"files {counts['files_total']} sanitized {counts['files_sanitized']} "
        f"quarantined {counts['files_quarantined']} records {counts['records_processed']} "
        f"linked {counts['records_linked']}"
    )
    return 0
