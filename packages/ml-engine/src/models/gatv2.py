"""GATv2 cost model with global attention pooling (CPU-friendly)."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn
from torch_geometric.data import Data
from torch_geometric.nn import GATv2Conv
from torch_geometric.utils import softmax

from config import (
    EDGE_FEATURE_DIM,
    MODEL_DROPOUT,
    MODEL_HEADS,
    MODEL_HIDDEN_DIM,
    MODEL_LAYERS,
    NODE_FEATURE_DIM,
)


class GlobalAttentionPooling(nn.Module):
    """Attention-weighted graph readout: softmax(g(h_i)) applied per graph."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.gate = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(self, x: Tensor, batch: Tensor | None = None) -> Tensor:
        if batch is None:
            batch = torch.zeros(x.size(0), dtype=torch.long, device=x.device)
        scores = self.gate(x)
        weights = softmax(scores, batch)
        num_graphs = int(batch.max().item()) + 1 if batch.numel() else 1
        pooled = x.new_zeros((num_graphs, x.size(1)))
        pooled.index_add_(0, batch, weights * x)
        return pooled


class Gatv2CostModel(nn.Module):
    """3-layer GATv2 regressor predicting log(1 + execution_time_ms).

    Layer widths follow the constitution: h=128 with 4 -> 4 -> 1 attention
    heads, followed by global attention pooling and a 128 -> 64 -> 1 MLP.
    """

    def __init__(
        self,
        node_dim: int = NODE_FEATURE_DIM,
        edge_dim: int = EDGE_FEATURE_DIM,
        hidden_dim: int = MODEL_HIDDEN_DIM,
        heads: int = MODEL_HEADS,
        dropout: float = MODEL_DROPOUT,
        layers: int = MODEL_LAYERS,
    ) -> None:
        super().__init__()
        if hidden_dim % heads != 0:
            raise ValueError("hidden_dim must be divisible by heads")
        if layers != 3:
            raise ValueError("The enforced architecture is exactly 3 GATv2 layers")

        self.node_dim = node_dim
        self.edge_dim = edge_dim
        self.hidden_dim = hidden_dim
        self.heads = heads
        self.dropout_rate = dropout

        self.input_proj = nn.Linear(node_dim, hidden_dim)
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(dropout)

        per_head = hidden_dim // heads
        # Attention dropout is disabled inside GATv2Conv: dropping attention
        # coefficients makes the eval-mode attention distribution diverge from
        # training and collapses the regressor's output scale. Regularisation
        # is applied through the explicit 0.2 dropout layers below instead.
        self.layers = nn.ModuleList(
            [
                GATv2Conv(
                    hidden_dim,
                    per_head,
                    heads=heads,
                    edge_dim=edge_dim,
                    dropout=0.0,
                ),
                GATv2Conv(
                    hidden_dim,
                    per_head,
                    heads=heads,
                    edge_dim=edge_dim,
                    dropout=0.0,
                ),
                GATv2Conv(
                    hidden_dim,
                    hidden_dim,
                    heads=1,
                    edge_dim=edge_dim,
                    dropout=0.0,
                ),
            ]
        )
        self.pool = GlobalAttentionPooling(hidden_dim)
        self.norms = nn.ModuleList(
            [nn.LayerNorm(hidden_dim) for _ in range(len(self.layers))]
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
        )

    def forward(
        self, data: Data, return_attention: bool = False
    ) -> Tensor | tuple[Tensor, list[tuple[Tensor, Tensor]]]:
        edge_index = data.edge_index
        if edge_index is None:
            raise ValueError("Data.edge_index is required")
        edge_attr = getattr(data, "edge_attr", None)
        if edge_attr is None:
            edge_attr = edge_index.new_zeros((edge_index.size(1), self.edge_dim))

        x = self.dropout(self.activation(self.input_proj(data.x)))
        attentions: list[tuple[Tensor, Tensor]] = []
        for layer, norm in zip(self.layers, self.norms):
            x, (attended_edges, alpha) = layer(
                x,
                edge_index,
                edge_attr=edge_attr,
                return_attention_weights=True,
            )
            attentions.append((attended_edges, alpha))
            x = norm(self.activation(x))

        pooled = self.pool(x, getattr(data, "batch", None))
        prediction = self.head(pooled)
        if return_attention:
            return prediction, attentions
        return prediction

    def predict_log_latency(self, data: Data) -> float:
        """Inference-only helper that always disables gradients."""
        self.eval()
        with torch.no_grad():
            output = self.forward(data)
        return float(output.view(-1)[0].item())


def parameter_count(model: nn.Module) -> int:
    """Number of trainable parameters (reported in training logs)."""
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


@dataclass(frozen=True)
class AttentionSummary:
    """Node-level attention mass extracted from the last GATv2 layer."""

    node_index: int
    weight: float


def summarize_attention(
    edge_index: Tensor, alpha: Tensor, num_nodes: int
) -> tuple[AttentionSummary, ...]:
    """Aggregate incoming edge attention into a per-node explainability score."""
    if alpha.numel() == 0 or edge_index.size(1) == 0:
        return ()
    weights = alpha.view(-1).detach().cpu()
    targets = edge_index[1].detach().cpu()
    totals = torch.zeros(num_nodes, dtype=torch.float32)
    totals.index_add_(0, targets, weights)
    if float(totals.sum()) > 0:
        totals = totals / totals.sum()
    ranked = sorted(
        (
            AttentionSummary(node_index=index, weight=float(value))
            for index, value in enumerate(totals.tolist())
        ),
        key=lambda item: item.weight,
        reverse=True,
    )
    return tuple(ranked)
