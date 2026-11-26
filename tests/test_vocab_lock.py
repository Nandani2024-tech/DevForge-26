"""R22 guard: every module-level word/label/token list, set and string-keyed dict in wards/*.py
is frozen by tests/vocab_lock.json.

The lock is a sorted snapshot of the constants as committed at HEAD. A constant that gains, loses
or changes an entry, a new list constant, or a removed one fails this test with the constant name
and the added/removed words. Only Claude or the user changes the lock, in review, with a non-dev
source for each word (00-rules sec 4).

Regenerate the lock from HEAD (review only): python tests/test_vocab_lock.py --write-lock
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WARDS_DIR = REPO_ROOT / "wards"
LOCK_PATH = Path(__file__).resolve().parent / "vocab_lock.json"
# Reserved lock key: "<module>:<CONSTANT>:<word>" -> non-dev source for a word approved in review.
SOURCES_KEY = "_sources"
_COLLECTION_CALLS = frozenset({"frozenset", "set", "tuple", "list"})


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _string_elements(node: ast.AST) -> list[str] | None:
    """Entries of a literal collection whose elements are all str constants, else None. O(len)."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _COLLECTION_CALLS:
        if len(node.args) != 1 or node.keywords:
            return None
        node = node.args[0]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        vals = [_const_str(e) for e in node.elts]
        if not vals or any(v is None for v in vals):
            return None
        return [v for v in vals if v is not None]
    if isinstance(node, ast.Dict):
        keys = [_const_str(k) if k is not None else None for k in node.keys]
        if not keys or any(k is None for k in keys):
            return None
        out: list[str] = []
        for k, v in zip(keys, node.values):
            if isinstance(v, ast.Constant) and isinstance(v.value, (str, int, float)) and not isinstance(v.value, bool):
                out.append(f"{k}={v.value!r}")
            else:
                out.append(f"{k}")
        return out
    return None


def extract_vocab(source: str) -> dict[str, list[str]]:
    """Map NAME -> sorted entries for every module-level literal string collection. O(source size)."""
    tree = ast.parse(source)
    found: dict[str, list[str]] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            name, value = stmt.targets[0].id, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            name, value = stmt.target.id, stmt.value
        else:
            continue
        entries = _string_elements(value)
        if entries is not None:
            found[name] = sorted(entries)
    return found


def _module_sources_at_head() -> dict[str, str]:
    """wards/*.py as committed at HEAD (never the working tree). O(files)."""
    listing = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD", "wards/"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.split()
    sources: dict[str, str] = {}
    for rel in sorted(listing):
        if rel.endswith(".py"):
            sources[Path(rel).name] = subprocess.run(
                ["git", "show", f"HEAD:{rel}"],
                cwd=REPO_ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
            ).stdout
    return sources


def _module_sources_worktree() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WARDS_DIR.glob("*.py"))}


def build_lock(sources: dict[str, str]) -> dict[str, dict[str, list[str]]]:
    lock: dict[str, dict[str, list[str]]] = {}
    for mod in sorted(sources):
        vocab = extract_vocab(sources[mod])
        if vocab:
            lock[mod] = dict(sorted(vocab.items()))
    return lock


def _locked_vocab(lock: dict[str, object]) -> dict[str, dict[str, list[str]]]:
    """Lock entries without the reserved _sources map. O(entries)."""
    return {mod: v for mod, v in lock.items() if mod != SOURCES_KEY}  # type: ignore[misc]


def _diff(locked: dict[str, dict[str, list[str]]], current: dict[str, dict[str, list[str]]]) -> list[str]:
    problems: list[str] = []
    for mod in sorted(set(locked) | set(current)):
        old_mod, new_mod = locked.get(mod, {}), current.get(mod, {})
        for name in sorted(set(old_mod) | set(new_mod)):
            if name not in new_mod:
                problems.append(f"{mod}:{name} removed (locked {len(old_mod[name])} entries)")
                continue
            if name not in old_mod:
                problems.append(f"{mod}:{name} is a new list constant: added {new_mod[name]}")
                continue
            old_set, new_set = set(old_mod[name]), set(new_mod[name])
            added, removed = sorted(new_set - old_set), sorted(old_set - new_set)
            if added or removed:
                problems.append(f"{mod}:{name} added {added} removed {removed}")
            elif old_mod[name] != new_mod[name]:
                problems.append(f"{mod}:{name} duplicate entries changed")
    return problems


def test_r22_vocab_lock_file_exists_and_is_nonempty() -> None:
    assert LOCK_PATH.is_file(), "tests/vocab_lock.json is missing: the vocabulary guard cannot run"
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert isinstance(lock, dict) and lock, "tests/vocab_lock.json is empty"
    assert sum(len(v) for v in _locked_vocab(lock).values()) > 0


def test_r22_vocab_lock_sources_name_locked_words() -> None:
    # Every word approved in review carries a non-empty source and must exist in the lock.
    assert LOCK_PATH.is_file(), "tests/vocab_lock.json is missing: the vocabulary guard cannot run"
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    sources = lock.get(SOURCES_KEY, {})
    assert isinstance(sources, dict)
    vocab = _locked_vocab(lock)
    for ref, source in sorted(sources.items()):
        mod, name, word = ref.split(":", 2)
        assert isinstance(source, str) and source.strip(), f"{ref} has no source"
        assert word in vocab.get(mod, {}).get(name, []), f"{ref} is sourced but not in the lock"


def test_r22_word_lists_match_vocab_lock() -> None:
    assert LOCK_PATH.is_file(), "tests/vocab_lock.json is missing: the vocabulary guard cannot run"
    locked = _locked_vocab(json.loads(LOCK_PATH.read_text(encoding="utf-8")))
    current = build_lock(_module_sources_worktree())
    problems = _diff(locked, current)
    assert not problems, "word lists changed versus tests/vocab_lock.json:\n" + "\n".join(problems)


def test_r22_vocab_extractor_sees_every_collection_shape() -> None:
    # Invented constant names and words: the extractor must cover each literal shape it guards.
    src = (
        "A = ('zorb', 'quil')\n"
        "B = frozenset({'vex', 'trum'})\n"
        "C: tuple[str, ...] = ['plon']\n"
        "D = {'kel': 'X', 'mib': 3}\n"
        "E = frozenset(A) | frozenset(B)\n"
        "F = 7\n"
    )
    got = extract_vocab(src)
    assert got == {
        "A": ["quil", "zorb"],
        "B": ["trum", "vex"],
        "C": ["plon"],
        "D": ["kel='X'", "mib=3"],
    }
    changed = {"m.py": dict(got, A=["quil", "zorb", "glent"])}
    problems = _diff({"m.py": got}, changed)
    assert problems == ["m.py:A added ['glent'] removed []"]


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-lock"]:
        raise SystemExit("usage: python tests/test_vocab_lock.py --write-lock  (review only; snapshots HEAD)")
    # Keeps the reviewed _sources map; each sourced word must be committed at HEAD by then.
    previous = json.loads(LOCK_PATH.read_text(encoding="utf-8")) if LOCK_PATH.is_file() else {}
    new_lock: dict[str, object] = dict(build_lock(_module_sources_at_head()))
    if previous.get(SOURCES_KEY):
        new_lock[SOURCES_KEY] = previous[SOURCES_KEY]
    LOCK_PATH.write_text(
        json.dumps(new_lock, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
