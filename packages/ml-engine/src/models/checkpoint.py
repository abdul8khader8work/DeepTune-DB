"""Checkpoint persistence for the GATv2 cost model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import torch

from config import (
    EDGE_FEATURE_DIM,
    MODEL_DROPOUT,
    MODEL_HEADS,
    MODEL_HIDDEN_DIM,
    MODEL_LAYERS,
    NODE_FEATURE_DIM,
)
from models.gatv2 import Gatv2CostModel


@dataclass(frozen=True)
class ModelConfig:
    node_dim: int = NODE_FEATURE_DIM
    edge_dim: int = EDGE_FEATURE_DIM
    hidden_dim: int = MODEL_HIDDEN_DIM
    heads: int = MODEL_HEADS
    dropout: float = MODEL_DROPOUT
    layers: int = MODEL_LAYERS


def build_model(config: ModelConfig) -> Gatv2CostModel:
    return Gatv2CostModel(
        node_dim=config.node_dim,
        edge_dim=config.edge_dim,
        hidden_dim=config.hidden_dim,
        heads=config.heads,
        dropout=config.dropout,
        layers=config.layers,
    )


def save_checkpoint(
    path: str | Path,
    model: Gatv2CostModel,
    config: ModelConfig,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "config": asdict(config),
            "metadata": dict(metadata or {}),
        },
        destination,
    )
    return destination


def load_checkpoint(
    path: str | Path, map_location: str = "cpu"
) -> tuple[Gatv2CostModel, ModelConfig, dict[str, Any]]:
    checkpoint = torch.load(path, map_location=map_location, weights_only=True)
    if not isinstance(checkpoint, dict) or "state_dict" not in checkpoint:
        raise ValueError("Checkpoint is missing a state_dict")
    config = ModelConfig(**checkpoint.get("config", {}))
    model = build_model(config)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval()
    metadata = dict(checkpoint.get("metadata", {}))
    return model, config, metadata
