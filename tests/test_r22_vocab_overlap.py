"""Permanent R22 vocabulary-overlap ratchet against a reviewed non-dev allowlist (D6)."""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

_TOKEN_RE = re.compile(r"[a-z\u0900-\u097f]+")


def _tokens(text: str) -> list[str]:
    return [w for w in _TOKEN_RE.findall(text.casefold()) if len(w) >= 3]


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """Return id() of docstring ast.Constant nodes (first statement of Module/ClassDef/FunctionDef)."""
    doc_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body:
                first = node.body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    doc_ids.add(id(first.value))
    return doc_ids


def _top_level_owner(stmt: ast.stmt) -> str:
    if isinstance(stmt, ast.Assign) and stmt.targets and isinstance(stmt.targets[0], ast.Name):
        return stmt.targets[0].id
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return stmt.name
    return "<module>"


def _extract_code_triples(repo_root: Path) -> set[tuple[str, str, str]]:
    triples: set[tuple[str, str, str]] = set()
    py_files: list[Path] = [repo_root / "main.py"]
    py_files.extend(sorted((repo_root / "wards").rglob("*.py")))

    for py_path in py_files:
        rel = py_path.relative_to(repo_root).as_posix()
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=rel)
        doc_ids = _docstring_node_ids(tree)
        for stmt in tree.body:
            owner = _top_level_owner(stmt)
            for node in ast.walk(stmt):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
                    for word in _tokens(node.value):
                        triples.add((word, rel, owner))
    return triples


def _extract_config_triples(repo_root: Path) -> set[tuple[str, str, str]]:
    triples: set[tuple[str, str, str]] = set()
    config_dir = repo_root / "config"
    assert config_dir.is_dir(), f"Missing config directory: {config_dir}"
    for cfg_path in sorted(p for p in config_dir.rglob("*") if p.is_file()):
        rel = cfg_path.relative_to(repo_root).as_posix()
        for raw_line in cfg_path.read_text(encoding="utf-8").splitlines():
            clean = raw_line.split("#", 1)[0]
            if not clean.strip():
                continue
            if ":" in clean:
                owner_part = clean.split(":", 1)[0].strip()
                owner = owner_part if owner_part else "<module>"
            else:
                owner = "<module>"
            for word in _tokens(clean):
                triples.add((word, rel, owner))
    return triples


def _load_allowlist(allowlist_path: Path) -> set[tuple[str, str, str]]:
    assert allowlist_path.is_file(), f"Missing allowlist fixture: {allowlist_path}"
    allowed: set[tuple[str, str, str]] = set()
    for lineno, raw in enumerate(allowlist_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|", 3)]
        assert len(parts) == 4, f"Malformed allowlist line {lineno}"
        allowed.add((parts[0], parts[1], parts[2]))
    return allowed


def test_r22_vocab_overlap_ratchet(repo_root: Path, kit_dir: Path) -> None:
    dev_input = kit_dir / "dev" / "input"
    assert dev_input.is_dir(), f"Missing dev/input fixture: {dev_input}"

    dev_filename_tokens: set[str] = set()
    dev_content_counts: Counter[str] = Counter()
    for p in sorted(dev_input.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(dev_input).as_posix()
        dev_filename_tokens.update(_tokens(rel))
        txt = p.read_bytes().decode("utf-8", "ignore")
        dev_content_counts.update(set(_tokens(txt)))

    allowed = _load_allowlist(repo_root / "tests" / "r22_vocab_allowlist.txt")
    code_triples = _extract_code_triples(repo_root) | _extract_config_triples(repo_root)

    unallowed: list[str] = []
    for word, rel_file, owner in code_triples:
        is_flagged = (word in dev_filename_tokens) or (1 <= dev_content_counts[word] <= 3)
        if is_flagged and (word, rel_file, owner) not in allowed:
            unallowed.append(f"{rel_file}:{owner}:{word}")

    assert not unallowed, "Unallowlisted dev-overlapping words: " + ", ".join(sorted(unallowed))
