"""Load the Phase 3 neuro-symbolic engine exactly once, inside the lifespan.

The engine is a pure Python library that lives in ``packages/ml-engine/src``. It
is not a published wheel, so this module puts that directory on ``sys.path`` and
imports the ``inference`` facade. Nothing here may import FastAPI or a database
driver, and no training code is allowed in ``apps/api`` (see AGENTS.md).

The loader is deliberately total: a missing checkpoint, a CPU-only host without
torch, or a corrupt file must degrade the API to the Phase 2 heuristic path
instead of preventing startup.
"""

from __future__ import annotations

import importlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.config import Settings

logger = logging.getLogger(__name__)

_ENGINE_RELATIVE = Path("packages") / "ml-engine"


def _repo_root() -> Path:
    """Find the repository root by looking for ``packages/ml-engine``.

    A fixed ``parents[4]`` breaks in the Docker image, where the API lives at
    ``/app/src`` and the engine is copied next to it at
    ``/app/packages/ml-engine``.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / _ENGINE_RELATIVE).is_dir():
            return parent
    return here.parents[min(3, len(here.parents) - 1)]


_REPO_ROOT = _repo_root()


def default_engine_src() -> Path:
    return _REPO_ROOT / _ENGINE_RELATIVE / "src"


def default_checkpoint_path() -> Path:
    return _REPO_ROOT / _ENGINE_RELATIVE / "weights" / "demo-final.pt"


@dataclass(frozen=True)
class EngineStatus:
    """Serialisable description of what the API actually loaded."""

    enabled: bool
    available: bool
    backend: str
    device: str
    checkpoint: str | None
    model_version: str | None
    parameters: int | None
    hidden_dim: int | None
    layers: int | None
    heads: int | None
    error: str | None = None

    @property
    def label(self) -> str:
        return "GATv2 (neuro-symbolic)" if self.available else "heuristic fallback"


@dataclass(frozen=True)
class EngineBundle:
    optimizer: Any | None
    status: EngineStatus

    @property
    def available(self) -> bool:
        return self.optimizer is not None


def _unavailable(status: EngineStatus, reason: str) -> EngineBundle:
    logger.warning("ML engine unavailable: %s", reason)
    return EngineBundle(
        optimizer=None,
        status=EngineStatus(
            enabled=status.enabled,
            available=False,
            backend="heuristic",
            device=status.device,
            checkpoint=status.checkpoint,
            model_version=None,
            parameters=None,
            hidden_dim=None,
            layers=None,
            heads=None,
            error=reason,
        ),
    )


def _resolve_src(settings: Settings) -> Path:
    configured = settings.ml_engine_src.strip()
    return Path(configured).expanduser().resolve() if configured else default_engine_src()


def _resolve_checkpoint(settings: Settings) -> Path:
    configured = settings.ml_checkpoint_path.strip()
    return (
        Path(configured).expanduser().resolve()
        if configured
        else default_checkpoint_path()
    )


def _ensure_importable(src: Path) -> None:
    """Append the engine source root so ``import inference`` resolves."""
    entry = str(src)
    if entry not in sys.path:
        sys.path.append(entry)


def _describe(optimizer: Any) -> tuple[str | None, int | None, int | None, int | None, int | None]:
    config = getattr(optimizer, "model_config", None)
    metadata = getattr(optimizer, "metadata", {}) or {}
    version = str(metadata.get("version") or metadata.get("run_name") or "v1.0")
    parameters = getattr(optimizer, "_model", None)
    count = None
    if parameters is not None and hasattr(parameters, "parameters"):
        count = sum(p.numel() for p in parameters.parameters())
    hidden = getattr(config, "hidden_dim", None)
    layers = getattr(config, "layers", None)
    heads = getattr(config, "heads", None)
    return version, count, hidden, layers, heads


def load_engine(settings: Settings) -> EngineBundle:
    """Build the ``PlanOptimizer`` once. Never raises."""
    base = EngineStatus(
        enabled=settings.ml_enabled,
        available=False,
        backend="heuristic",
        device=settings.ml_device,
        checkpoint=None,
        model_version=None,
        parameters=None,
        hidden_dim=None,
        layers=None,
        heads=None,
    )

    if not settings.ml_enabled:
        return _unavailable(base, "ML_ENABLED is false")

    src = _resolve_src(settings)
    if not (src / "inference.py").is_file():
        return _unavailable(base, f"engine source not found at {src}")

    checkpoint = _resolve_checkpoint(settings)
    if not checkpoint.is_file():
        return _unavailable(
            base,
            f"checkpoint not found at {checkpoint} (run `make ml-train`)",
        )

    try:
        _ensure_importable(src)
        inference = importlib.import_module("inference")
        optimizer = inference.PlanOptimizer(
            inference.InferenceConfig(
                checkpoint_path=str(checkpoint),
                device=settings.ml_device,
            )
        )
    except Exception as exc:  # noqa: BLE001 - startup must survive any engine fault
        logger.exception("ML engine failed to load")
        return _unavailable(base, f"{exc.__class__.__name__}: {exc}")

    version, count, hidden, layers, heads = _describe(optimizer)
    logger.info(
        "ML engine ready: GATv2 %s on %s (%s parameters)",
        version,
        settings.ml_device,
        f"{count:,}" if count else "unknown",
    )
    return EngineBundle(
        optimizer=optimizer,
        status=EngineStatus(
            enabled=True,
            available=True,
            backend="gnn",
            device=settings.ml_device,
            checkpoint=str(checkpoint),
            model_version=version,
            parameters=count,
            hidden_dim=hidden,
            layers=layers,
            heads=heads,
            error=None,
        ),
    )
