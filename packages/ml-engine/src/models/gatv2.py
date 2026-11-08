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
    """Two-layer GATv2 regressor predicting log(1 + execution_time_ms).

    Patch 2 Task 4 / Constitution §3: the old 3-layer stack over-smoothed on
    shallow query plans (5-12 nodes), washing out the low-level scan topology
    that actually explains latency. The stack is now two layers wide
    (h=128, 4 -> 4 heads) plus a residual skip that carries the *raw* node
    features around both attention layers:

        H_out = activation(H2 + skip_proj(X))

    ``skip_proj`` exists purely for dimension parity: node features are 39-wide
    while the concatenated attention output is 128-wide, so a ``nn.Linear``
    projects the input into the residual space. When the widths match it
    collapses to ``nn.Identity()``.
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
        if layers != 2:
            raise ValueError(
                "The enforced architecture is exactly 2 GATv2 layers + residual"
            )

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
                )
                for _ in range(layers)
            ]
        )
        # Residual projection: node_dim -> hidden_dim (the concat width of the
        # final GATv2 layer). Identity when the widths already agree.
        self.skip_proj: nn.Module = (
            nn.Linear(node_dim, hidden_dim)
            if node_dim != hidden_dim
            else nn.Identity()
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

        # Skip path is projected from the raw features, not from the trained
        # projection, so it preserves the original operator/row/cost signal.
        skip = self.skip_proj(data.x)
        x = self.dropout(self.activation(self.input_proj(data.x)))
        attentions: list[tuple[Tensor, Tensor]] = []
        last = len(self.layers) - 1
        for index, (layer, norm) in enumerate(zip(self.layers, self.norms)):
            out, (attended_edges, alpha) = layer(
                x,
                edge_index,
                edge_attr=edge_attr,
                return_attention_weights=True,
            )
            attentions.append((attended_edges, alpha))
            if index == last:
                out = out + skip  # H_out = activation(H2 + skip_proj(X))
            x = norm(self.activation(out))

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
    """Aggregate incoming edge attention into a per-node explainability score.

    PyG returns ``alpha`` with one column per attention head once the final
    layer keeps ``concat=True`` (Patch 2: both layers use 4 heads). Each head's
    softmax already sums to one per target, so averaging across heads keeps the
    per-node mass on the same 0..1 scale as the single-head architecture.
    """
    if alpha.numel() == 0 or edge_index.size(1) == 0:
        return ()
    weights = alpha.detach().cpu()
    if weights.dim() > 1:
        weights = weights.mean(dim=-1)
    weights = weights.view(-1)
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
