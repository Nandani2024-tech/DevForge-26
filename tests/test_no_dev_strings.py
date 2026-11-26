"""Permanent R22 guard: ensure no dev truth surfaces appear in code, config, or tests."""
from __future__ import annotations

import json
from pathlib import Path


def test_no_dev_truth_surfaces_in_repo(repo_root: Path, kit_dir: Path) -> None:
    truth_path = kit_dir / "dev" / "truth" / "truth.json"
    assert truth_path.is_file(), f"Missing truth fixture: {truth_path}"

    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    surfaces = sorted(
        {
            e["surface"].strip().casefold()
            for f in truth["files"].values()
            for u in f["units"].values()
            for e in u["entities"]
            if len(e["surface"].strip()) >= 6 or len(e["surface"].strip().split()) >= 2
        }
    )

    self_path = Path(__file__).resolve()
    targets: list[Path] = [repo_root / "main.py"]
    for sub in ("wards", "tests", "config"):
        sub_dir = repo_root / sub
        if sub_dir.is_dir():
            targets.extend(sorted(p for p in sub_dir.rglob("*") if p.is_file()))

    hits: list[str] = []
    for file_path in targets:
        if file_path.resolve() == self_path:
            continue
        if file_path.suffix not in (".py", ".yaml", ".toml", ".txt", ".md"):
            continue
        rel = file_path.relative_to(repo_root).as_posix()
        for lineno, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
            low = line.casefold()
            if any(surf in low for surf in surfaces):
                # Print only file and line number, never the matched value
                hits.append(f"{rel}:{lineno}")

    assert not hits, "Dev truth surfaces found at: " + ", ".join(hits)
