"""Shared pytest fixtures for Secret Wards."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KIT_DIR = REPO_ROOT.parent / "Secret-Wards-ToolKit"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def kit_dir() -> Path:
    if not KIT_DIR.is_dir():
        pytest.skip("Secret-Wards-ToolKit directory not found alongside repo")
    return KIT_DIR
