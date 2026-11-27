"""Submission documents: R23 (model declaration), R24 (README sections), R25 (2-page Project Brief PDF).

Oracles come from the kit, not from our own files:
- START_HERE.md sec 8 checklist: README has setup, an architecture diagram, how each part works,
  the security design and known limitations; any model is declared in the README.
- check_submission.py: README >= 300 words; requirements.txt free of LLM / hosted-AI packages.
- docs/PROJECT_BRIEF.md: 2 pages maximum, sections team/pitch, architecture, how it works, USP,
  privacy-utility trade-off with measured numbers, security design, known limitations; the PDF is
  committed in the repo (example path docs/brief.pdf).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Kit check_submission.py BANNED pattern (LLM / hosted-AI packages), copied verbatim from the kit.
_KIT_BANNED = re.compile(
    r"^\s*(openai|anthropic|google-generativeai|google-genai|ollama|llama[-_]cpp|llama-index|"
    r"langchain\S*|vllm|mistralai|cohere|groq|together|litellm|gpt4all|ctransformers)\b",
    re.I | re.M,
)

# README section -> heading words that satisfy it (kit START_HERE sec 8 + R23 model declaration).
_README_SECTIONS = {
    "setup": ("setup",),
    "architecture": ("architecture",),
    "how each part works": ("how each part works", "how it works"),
    "security": ("security",),
    "limitations": ("limitations",),
    "models": ("models", "model"),
}

# Brief section -> heading words (kit docs/PROJECT_BRIEF.md "What it must cover").
_BRIEF_SECTIONS = {
    "pitch": ("in one paragraph", "pitch"),
    "architecture": ("architecture",),
    "how it works": ("how it works", "how each part works"),
    "usp": ("usp",),
    "trade-off": ("trade-off", "tradeoff"),
    "security": ("security",),
    "limitations": ("limitations",),
}


def _headings(markdown: str) -> list[str]:
    """Lower-cased markdown heading texts. O(len(markdown))."""
    return [m.group(1).strip().lower() for m in re.finditer(r"^#{1,6}\s+(.+)$", markdown, re.M)]


def _missing_sections(markdown: str, required: dict[str, tuple[str, ...]]) -> list[str]:
    """Required section names with no heading containing one of their words. O(headings x sections)."""
    heads = _headings(markdown)
    return [name for name, words in required.items() if not any(w in h for h in heads for w in words)]


def _pdf_page_count(data: bytes) -> int:
    """Count page objects (/Type /Page, not /Pages) in an uncompressed-xref PDF. O(len(data))."""
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))


def test_r24_readme_has_kit_checklist_sections_and_300_words(repo_root: Path) -> None:
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    assert _missing_sections(text, _README_SECTIONS) == []
    assert len(text.split()) >= 300  # kit check_submission threshold
    # an architecture *diagram*: at least one fenced block after the Architecture heading
    arch = text.lower().split("## architecture", 1)[1]
    assert "```" in arch.split("\n## ", 1)[0]


def test_r24_section_check_reports_a_missing_section() -> None:
    # Failure case: a README without a security heading must be reported, not passed.
    text = "# T\n## Setup\n## Architecture\n## How each part works\n## Models\n## Known limitations\n"
    assert _missing_sections(text, _README_SECTIONS) == ["security"]
    assert _missing_sections("", _README_SECTIONS) == list(_README_SECTIONS)


def test_r23_readme_declares_no_models_and_requirements_have_no_llm_packages(repo_root: Path) -> None:
    text = (repo_root / "README.md").read_text(encoding="utf-8").lower()
    assert "no llm" in text or "no llms" in text
    for req in ("requirements.txt", "requirements-dev.txt"):
        assert _KIT_BANNED.findall((repo_root / req).read_text(encoding="utf-8")) == [], req


def test_r23_banned_pattern_catches_an_llm_package() -> None:
    # Failure case: the copied kit pattern is not blind.
    assert _KIT_BANNED.findall("psutil==7.2.2\nopenai==1.0\nlangchain-core\n") == ["openai", "langchain-core"]


def test_r25_brief_pdf_exists_is_a_pdf_and_has_exactly_two_pages(repo_root: Path) -> None:
    pdf = repo_root / "docs" / "brief.pdf"
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF-")
    assert _pdf_page_count(data) == 2


def test_r25_page_counter_ignores_the_pages_tree_node() -> None:
    # Hand-built: one /Pages node + three /Page objects -> 3.
    fake = b"<< /Type /Pages /Count 3 >> << /Type /Page >> << /Type/Page >> << /Type /Page /X 1 >>"
    assert _pdf_page_count(fake) == 3


def test_r25_brief_source_covers_guideline_sections_and_unseen_data(repo_root: Path) -> None:
    text = (repo_root / "docs" / "PROJECT_BRIEF.md").read_text(encoding="utf-8")
    assert _missing_sections(text, _BRIEF_SECTIONS) == []
    low = text.lower()
    assert "did not tune on" in low  # kit: say how numbers change on data you did not tune on
    assert "<members>" not in low  # template placeholder filled in


def test_r25_brief_files_are_not_gitignored(repo_root: Path) -> None:
    # The PDF must be committed with the repo; check-ignore exits 1 when a path is NOT ignored.
    for rel in ("docs/brief.pdf", "docs/PROJECT_BRIEF.md", "README.md"):
        proc = subprocess.run(["git", "check-ignore", "-q", rel], cwd=repo_root, capture_output=True)
        assert proc.returncode == 1, f"{rel} is gitignored"
