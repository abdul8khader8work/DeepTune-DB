"""Patch 3, Task 3: the shadow DB must never be backed by host RAM again."""

from __future__ import annotations

from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def _text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def _shadow_block() -> list[str]:
    lines = _text().splitlines()
    start = lines.index("  shadow_db:")
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return [line.strip() for line in block]


def test_shadow_db_has_no_tmpfs_mount() -> None:
    mounts = [line.strip() for line in _shadow_block()]
    assert "tmpfs:" not in mounts
    assert "/var/lib/postgresql/data" in _text()


def test_shadow_db_mounts_the_named_volume() -> None:
    assert "- shadow_data:/var/lib/postgresql/data" in _shadow_block()


def test_top_level_volume_is_declared() -> None:
    lines = _text().splitlines()
    volumes_at = max(index for index, line in enumerate(lines) if line == "volumes:")
    declared = [line.strip() for line in lines[volumes_at + 1 :] if line.strip()]
    assert "shadow_data:" in declared
    assert "shm_size: 256mb" in _shadow_block()
