"""Boundary checks for the pure ML engine (AGENTS.md section 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

FORBIDDEN_IMPORTS = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "psycopg2",
)


def _source_files() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if path.is_file())


@pytest.mark.parametrize("module", FORBIDDEN_IMPORTS)
def test_engine_never_imports_web_or_database_layers(module: str) -> None:
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        assert f"import {module}" not in text, f"{path} imports {module}"
        assert f"from {module}" not in text, f"{path} imports {module}"


def test_cost_model_never_reports_accuracy() -> None:
    for path in _source_files():
        text = path.read_text(encoding="utf-8").lower()
        assert '"accuracy"' not in text, path
        assert "'accuracy'" not in text, path


def test_engine_contains_expected_packages() -> None:
    packages = {path.name for path in SRC.iterdir() if path.is_dir()}
    assert {"parsers", "models", "search", "training"}.issubset(packages)
    assert (SRC / "inference.py").is_file()
    assert (SRC / "config.py").is_file()
