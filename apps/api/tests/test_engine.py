"""Engine loader: every failure mode must degrade to heuristics, never raise."""

import pytest

from src.core.config import Settings
from src.services.engine import default_checkpoint_path, load_engine


def _settings(**overrides: object) -> Settings:
    base = Settings(_env_file=None)
    return base.model_copy(update=overrides)


def test_disabled_engine_reports_heuristic_backend() -> None:
    bundle = load_engine(_settings(ml_enabled=False))
    assert bundle.available is False
    assert bundle.status.backend == "heuristic"
    assert bundle.status.enabled is False
    assert "ML_ENABLED" in (bundle.status.error or "")


def test_missing_engine_source_is_reported() -> None:
    bundle = load_engine(_settings(ml_engine_src="Z:/definitely/not/here"))
    assert bundle.available is False
    assert "engine source not found" in (bundle.status.error or "")


def test_missing_checkpoint_is_reported(tmp_path) -> None:
    bundle = load_engine(_settings(ml_checkpoint_path=str(tmp_path / "nope.pt")))
    assert bundle.available is False
    assert "checkpoint not found" in (bundle.status.error or "")


def test_unreadable_checkpoint_does_not_raise(tmp_path) -> None:
    broken = tmp_path / "broken.pt"
    broken.write_bytes(b"not a torch checkpoint")
    bundle = load_engine(_settings(ml_checkpoint_path=str(broken)))
    assert bundle.available is False
    assert bundle.status.error is not None


@pytest.mark.skipif(
    not default_checkpoint_path().is_file(),
    reason="demo checkpoint is git-ignored; run `make ml-train` first",
)
def test_real_checkpoint_loads_and_describes_the_model() -> None:
    bundle = load_engine(_settings())
    assert bundle.available is True
    status = bundle.status
    assert status.backend == "gnn"
    assert status.layers == 3
    assert status.heads == 4
    assert status.hidden_dim == 128
    assert status.parameters and status.parameters > 0
