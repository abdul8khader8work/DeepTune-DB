"""Model package: GATv2 architecture and checkpoint helpers."""

from models.checkpoint import ModelConfig, build_model, load_checkpoint, save_checkpoint
from models.gatv2 import (
    AttentionSummary,
    Gatv2CostModel,
    GlobalAttentionPooling,
    parameter_count,
    summarize_attention,
)

__all__ = [
    "AttentionSummary",
    "Gatv2CostModel",
    "GlobalAttentionPooling",
    "ModelConfig",
    "build_model",
    "load_checkpoint",
    "parameter_count",
    "save_checkpoint",
    "summarize_attention",
]
