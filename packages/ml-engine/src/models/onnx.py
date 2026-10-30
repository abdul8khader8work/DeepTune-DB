"""ONNX export and onnxruntime scoring for the GATv2 cost model.

Why this file re-implements the forward pass
--------------------------------------------
``torch.onnx.export`` cannot trace ``GATv2Conv`` and ``GlobalAttentionPooling``
as written. Both convert tensors to Python ints mid-graph:

* ``GATv2Conv`` calls ``maybe_num_nodes`` -> ``int(edge_index.max()) + 1``
* ``GlobalAttentionPooling`` calls ``batch.max().item()``

The tracer bakes the *trace-time* graph size into the exported graph, so every
prediction for a plan with a different node count is silently wrong (measured
drift of up to 5.07 in log-latency space, i.e. ~160x in milliseconds).

:class:`OnnxExportModel` therefore re-implements the exact same arithmetic with
shape-polymorphic tensor ops, reusing the trained parameters by reference:

* aggregation runs through a dense ``[E, N]`` indicator matrix and ``matmul``
  instead of scatter-add, because ONNX leaves duplicate ``ScatterElements``
  indices undefined.
* the attention softmax subtracts a *per-target* maximum. A global maximum is
  algebraically equivalent but underflows after two layers, where the score
  range spans hundreds of nats.
* self-loop features reproduce PyG's ``fill_value='mean'`` exactly: the mean of
  the attributes of the edges pointing *at* each node.

``export_onnx(..., verify=True)`` and ``tests/test_onnx.py`` assert parity with
the PyG forward, so the two implementations cannot drift apart unnoticed.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Protocol, Sequence, TypeAlias

import numpy as np
import torch
from torch import Tensor, nn
from torch.nn import functional as F
from torch_geometric.data import Data

from config import EDGE_FEATURE_DIM
from models.checkpoint import MetadataValue, ModelConfig
from models.gatv2 import Gatv2CostModel, parameter_count

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from onnxruntime import InferenceSession
    from torch_geometric.nn import GATv2Conv

ONNX_OPSET = 17
ONNX_INPUT_NAMES = ("x", "edge_index", "edge_attr")
ONNX_OUTPUT_NAMES = ("log_latency", "attended_edges", "attention")

#: Metadata keys mirrored from the ``.pt`` checkpoint into the ``.onnx`` file.
_METADATA_KEYS = (
    "epoch",
    "seed",
    "parameters",
    "curriculum",
    "hidden_dim",
    "layers",
    "heads",
)

_EPS = 1e-16

#: GATv2Conv's self-loop feature: ``'mean'``, a constant, or a feature vector.
FillValue: TypeAlias = str | float | Tensor


class GraphLike(Protocol):
    """Minimal view of a ``PlanGraph`` (keeps this module parser-agnostic)."""

    @property
    def data(self) -> Data: ...


def _loop_attr(
    edge_attr: Tensor, dst: Tensor, num_nodes: Tensor, fill_value: FillValue
) -> Tensor:
    """Self-loop features, mirroring ``compute_loop_attr`` in PyG.

    ``GATv2Conv`` defaults to ``fill_value='mean'``, which is the mean of the
    attributes of edges *pointing at* each node (not a global mean). Empty
    in-neighbourhoods fall back to zero, exactly like PyG's scatter reduction.
    """
    width = edge_attr.size(1)
    if isinstance(fill_value, str):
        if fill_value != "mean":
            raise NotImplementedError(f"unsupported self-loop fill_value={fill_value!r}")
        indicator = _indicator(dst, num_nodes, edge_attr)
        counts = indicator.sum(dim=0).clamp(min=1.0).unsqueeze(1)
        totals = indicator.t().matmul(edge_attr)
        return totals / counts
    if isinstance(fill_value, Tensor):
        return fill_value.to(edge_attr.dtype).view(1, -1).expand(num_nodes, width)
    return edge_attr.new_full((num_nodes, width), float(fill_value))


def _with_self_loops(
    edge_index: Tensor, edge_attr: Tensor, num_nodes: Tensor, fill_value: FillValue = "mean"
) -> tuple[Tensor, Tensor, Tensor]:
    """Drop existing self-loops, then append one per node (GATv2Conv semantics)."""
    src, dst = edge_index[0], edge_index[1]
    keep = src != dst
    src = src[keep]
    dst = dst[keep]
    edge_attr = edge_attr[keep]
    loops = torch.arange(num_nodes, device=edge_index.device)
    loop_attr = _loop_attr(edge_attr, dst, num_nodes, fill_value)
    src = torch.cat([src, loops])
    dst = torch.cat([dst, loops])
    edge_attr = torch.cat([edge_attr, loop_attr], dim=0)
    return src, dst, edge_attr


def _indicator(dst: Tensor, num_nodes: Tensor, like: Tensor) -> Tensor:
    """``[num_edges, num_nodes]`` indicator with ``indicator[e, dst[e]] = 1``.

    A matrix product replaces scatter-add because ONNX leaves duplicate indices
    in ``ScatterElements`` undefined. Every duplicate here writes the same
    constant ``1.0``, so the indicator is exact regardless of write order, and
    ``matmul`` keeps both dimensions dynamic. Transposing the result (instead of
    scattering along dim 0) is what keeps every edge in its own row.
    """
    matrix = like.new_zeros((dst.size(0), num_nodes))
    return matrix.scatter_(1, dst.unsqueeze(1), 1.0)


def _segment_max(scores: Tensor, indicator: Tensor) -> Tensor:
    """Per-target maximum over incoming edges (``scatter_max``, ONNX-safe).

    A global max would be mathematically equivalent but numerically fatal: after
    two layers the score range spans hundreds of nats, so ``exp(score - global_max)``
    underflows to zero for every node except one and the softmax denominator
    becomes zero.
    """
    mask = indicator.unsqueeze(-1) > 0
    floor = scores.new_full(
        (indicator.size(0), indicator.size(1), scores.size(1)), float("-inf")
    )
    return torch.where(mask, scores.unsqueeze(1), floor).amax(dim=0)


def _scatter_softmax(scores: Tensor, indicator: Tensor, dst: Tensor) -> Tensor:
    """Per-target softmax over incoming edges, with a dynamic node dimension."""
    node_max = _segment_max(scores, indicator)
    weights = (scores - node_max[dst]).exp()
    totals = indicator.t().matmul(weights)
    return weights / (totals[dst] + _EPS)


def _gat_layer(
    layer: GATv2Conv, hidden: Tensor, src: Tensor, dst: Tensor, edge_attr: Tensor
) -> tuple[Tensor, Tensor]:
    """One ``GATv2Conv`` layer with ``concat=True`` and no residual branch."""
    heads, channels = layer.heads, layer.out_channels
    left = layer.lin_l(hidden).view(-1, heads, channels)
    right = layer.lin_r(hidden).view(-1, heads, channels)
    source = left[src]
    target = right[dst]
    scores = target + source
    if layer.lin_edge is not None and edge_attr is not None:
        scores = scores + layer.lin_edge(edge_attr).view(-1, heads, channels)
    scores = F.leaky_relu(scores, layer.negative_slope)
    raw = (scores * layer.att).sum(dim=-1)
    indicator = _indicator(dst, hidden.size(0), raw)
    alpha = _scatter_softmax(raw, indicator, dst)
    messages = (source * alpha.unsqueeze(-1)).reshape(source.size(0), heads * channels)
    out = indicator.t().matmul(messages)
    if layer.bias is not None:
        out = out + layer.bias
    return out, alpha


class OnnxExportModel(nn.Module):
    """Traceable, tensor-in/tensor-out mirror of :class:`Gatv2CostModel`.

    Scores exactly one graph per call (the beam search never batches), which is
    what makes the single-graph attention pooling unambiguous.
    """

    def __init__(self, model: Gatv2CostModel) -> None:
        super().__init__()
        self.model = model

    def forward(
        self, x: Tensor, edge_index: Tensor, edge_attr: Tensor
    ) -> tuple[Tensor, Tensor, Tensor]:
        model = self.model
        hidden = model.dropout(model.activation(model.input_proj(x)))
        attended_edges = edge_index
        attention = x.new_zeros((0, 1))
        for layer, norm in zip(model.layers, model.norms):
            src, dst, attr = _with_self_loops(
                edge_index, edge_attr, x.size(0), layer.fill_value
            )
            out, alpha = _gat_layer(layer, hidden, src, dst, attr)
            hidden = norm(model.activation(out))
            attended_edges = torch.stack([src, dst])
            attention = alpha
        scores = model.pool.gate(hidden)
        weights = torch.softmax(scores, dim=0)
        pooled = (weights * hidden).sum(dim=0, keepdim=True)
        prediction = model.head(pooled)
        return prediction.view(-1), attended_edges, attention


def _dynamic_axes() -> dict[str, dict[int, str]]:
    return {
        "x": {0: "num_nodes"},
        "edge_index": {1: "num_edges"},
        "edge_attr": {0: "num_edges"},
        "attended_edges": {1: "num_edges"},
        "attention": {0: "num_edges"},
    }


def _attach_metadata(
    path: Path,
    config: ModelConfig,
    metadata: Mapping[str, MetadataValue],
    parameters: int,
) -> None:
    """Copy the checkpoint metadata into the ONNX proto so inference needs no .pt."""
    import onnx

    model = onnx.load(str(path))
    entries = {
        key: str(value) for key, value in asdict(config).items()
    }
    for key in _METADATA_KEYS:
        if key in metadata:
            entries[key] = str(metadata[key])
    entries["parameters"] = str(parameters)
    entries["onnx_opset"] = str(ONNX_OPSET)
    existing = {item.key: item for item in model.metadata_props}
    for key, value in entries.items():
        if key in existing:
            existing[key].value = value
        else:
            model.metadata_props.add(key=key, value=value)
    onnx.save(model, str(path))


def export_onnx(
    model: Gatv2CostModel,
    path: str | Path,
    sample: Data,
    config: ModelConfig,
    metadata: Mapping[str, MetadataValue] | None = None,
    verify: bool = True,
    opset: int = ONNX_OPSET,
) -> Path:
    """Export ``model`` to ``path`` and optionally prove parity with PyTorch."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wrapper = OnnxExportModel(model).eval()
    model.eval()

    x = sample.x.detach().clone()
    edge_index = sample.edge_index.detach().clone()
    edge_attr = sample.edge_attr.detach().clone()

    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (x, edge_index, edge_attr),
            str(destination),
            input_names=list(ONNX_INPUT_NAMES),
            output_names=list(ONNX_OUTPUT_NAMES),
            dynamic_axes=_dynamic_axes(),
            opset_version=opset,
            do_constant_folding=True,
            dynamo=False,
        )

    _attach_metadata(destination, config, metadata or {}, parameter_count(model))

    if verify:
        session = make_session(destination)
        with torch.no_grad():
            expected = float(model(sample).view(-1)[0].item())
        actual = run_log_latency(session, sample)
        drift = abs(expected - actual)
        if drift > 1e-3:
            destination.unlink(missing_ok=True)
            raise RuntimeError(
                "ONNX export failed parity check: "
                f"torch={expected:.6f} onnx={actual:.6f} drift={drift:.6f}"
            )
    return destination


def make_session(path: str | Path) -> InferenceSession:
    """Build a single-threaded onnxruntime session (deterministic and fast)."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def _feeds(data: Data) -> dict[str, np.ndarray]:
    edge_attr = getattr(data, "edge_attr", None)
    if edge_attr is None:
        edge_attr = torch.zeros((0, EDGE_FEATURE_DIM), dtype=torch.float32)
    return {
        "x": np.ascontiguousarray(data.x.detach().cpu().numpy()),
        "edge_index": np.ascontiguousarray(data.edge_index.detach().cpu().numpy()),
        "edge_attr": np.ascontiguousarray(edge_attr.detach().cpu().numpy()),
    }


def run_log_latency(session: InferenceSession, data: Data) -> float:
    """Run the ONNX graph and return the predicted ``log1p(latency_ms)``."""
    output = session.run(["log_latency"], _feeds(data))[0]
    return float(np.asarray(output).reshape(-1)[0])


def run_attention(session: InferenceSession, data: Data) -> tuple[Tensor, Tensor] | None:
    """Return ``(edge_index, alpha)`` for the last attention layer, if any."""
    edges, alpha = session.run(["attended_edges", "attention"], _feeds(data))
    edges_tensor = torch.as_tensor(np.asarray(edges), dtype=torch.long)
    alpha_tensor = torch.as_tensor(np.asarray(alpha), dtype=torch.float32)
    if edges_tensor.numel() == 0 or alpha_tensor.numel() == 0:
        return None
    return edges_tensor, alpha_tensor


class OnnxModelScorer:
    """``GraphScorer`` backed by onnxruntime instead of a live PyTorch forward."""

    def __init__(self, onnx_path: str | Path) -> None:
        self.path = Path(onnx_path)
        self._session = make_session(self.path)
        self._metadata = dict(self._session.get_modelmeta().custom_metadata_map)

    @property
    def metadata(self) -> dict[str, str]:
        return dict(self._metadata)

    def predict_log_latency(self, graph: GraphLike) -> float:
        data = graph.data
        if int(data.edge_index.size(1)) == 0 or int(data.x.size(0)) == 0:
            raise ValueError("ONNX scorer needs at least one node and one edge")
        return run_log_latency(self._session, data)

    def attention(self, graph: GraphLike) -> tuple[Tensor, Tensor] | None:
        return run_attention(self._session, graph.data)

    def benchmark(self, graphs: Sequence[GraphLike], repeats: int = 25) -> dict[str, float]:
        """Median wall-clock latency per graph, for the docs' sub-50 ms claim."""
        import time

        timings: list[float] = []
        for graph in graphs:
            feeds = _feeds(graph.data)
            self._session.run(["log_latency"], feeds)  # warm-up
            started = time.perf_counter()
            for _ in range(repeats):
                self._session.run(["log_latency"], feeds)
            timings.append((time.perf_counter() - started) / repeats * 1000.0)
        ordered = sorted(timings)
        median = ordered[len(ordered) // 2] if ordered else 0.0
        return {
            "median_ms": round(median, 3),
            "max_ms": round(max(ordered, default=0.0), 3),
            "graphs": float(len(ordered)),
        }


__all__ = [
    "ONNX_OPSET",
    "OnnxExportModel",
    "OnnxModelScorer",
    "export_onnx",
    "make_session",
    "run_attention",
    "run_log_latency",
]
