"""ONNX export must be a bit-for-bit stand-in for the PyTorch forward.

The exported graph is only worth shipping if it scores plans of *any* size the
same way the trained model does, so these tests export a checkpoint, run it
through onnxruntime for a range of graph shapes, and compare against the live
PyTorch forward. They also pin the two operational guarantees: metadata travels
inside the artifact, and a missing artifact degrades to torch instead of
raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

from inference import InferenceConfig, load_optimizer
from models.checkpoint import ModelConfig, build_model, load_checkpoint, save_checkpoint
from models.onnx import (
    ONNX_OUTPUT_NAMES,
    OnnxModelScorer,
    export_onnx,
    make_session,
    run_attention,
    run_log_latency,
)
from parsers.explain import plan_to_graph
from parsers.schema import SchemaCatalog
from training.workload import build_demo_catalog, generate_workload

#: Parity budget: float32 reordering only, three orders below the 1e-3 gate.
PARITY_TOLERANCE = 1e-4


@pytest.fixture()
def checkpoint(tmp_path: Path) -> tuple[Any, ModelConfig, dict[str, Any], Path]:
    config = ModelConfig()
    model = build_model(config)
    path = tmp_path / "random.pt"
    metadata = {"epoch": 3, "seed": 11, "curriculum": "unit-test"}
    save_checkpoint(path, model, config, metadata=metadata)
    loaded, loaded_config, loaded_metadata = load_checkpoint(path)
    return loaded, loaded_config, loaded_metadata, path


@pytest.fixture()
def graphs() -> list[Any]:
    """Plans of 2-12 nodes, so the dynamic axes are genuinely exercised."""
    catalog: SchemaCatalog = build_demo_catalog()
    data = []
    for tier, count in ((1, 6), (2, 6), (3, 6)):
        for sample in generate_workload(tier, count, seed=2024, catalog=catalog).samples:
            data.append(
                plan_to_graph(
                    sample.plan,
                    catalog=catalog,
                    execution_time_ms=sample.execution_time_ms,
                ).data
            )
    sizes = {int(graph.num_nodes) for graph in data}
    assert len(sizes) >= 4, "the fixture must span several graph sizes"
    return data


def _export(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
    destination: Path,
    sample: Any,
) -> Path:
    model, config, metadata, _ = checkpoint
    return export_onnx(model, destination, sample, config, metadata)


def test_onnx_scores_match_torch_for_every_graph_size(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
    graphs: list[Any],
    tmp_path: Path,
) -> None:
    model = checkpoint[0]
    destination = _export(checkpoint, tmp_path / "model.onnx", graphs[0])
    session = make_session(destination)

    worst = 0.0
    for graph in graphs:
        with torch.no_grad():
            expected = float(model(graph).view(-1)[0].item())
        actual = run_log_latency(session, graph)
        worst = max(worst, abs(expected - actual))

    assert worst < PARITY_TOLERANCE, f"onnx drifted from torch by {worst:.2e}"


def test_onnx_attention_matches_torch(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
    graphs: list[Any],
    tmp_path: Path,
) -> None:
    model = checkpoint[0]
    destination = _export(checkpoint, tmp_path / "model.onnx", graphs[0])
    session = make_session(destination)

    graph = graphs[-1]
    with torch.no_grad():
        _, attentions = model(graph, return_attention=True)
    expected_edges, expected_alpha = attentions[-1]

    pair = run_attention(session, graph)
    assert pair is not None
    edges, alpha = pair
    assert torch.equal(edges, expected_edges.cpu())
    drift = float((alpha.view(-1) - expected_alpha.cpu().view(-1)).abs().max())
    assert drift < PARITY_TOLERANCE


def test_export_embeds_checkpoint_metadata(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
    graphs: list[Any],
    tmp_path: Path,
) -> None:
    destination = _export(checkpoint, tmp_path / "model.onnx", graphs[0])
    metadata = OnnxModelScorer(destination).metadata

    assert metadata["epoch"] == "3"
    assert metadata["seed"] == "11"
    assert metadata["hidden_dim"] == str(ModelConfig().hidden_dim)
    assert metadata["heads"] == str(ModelConfig().heads)
    assert metadata["layers"] == str(ModelConfig().layers)
    assert int(metadata["parameters"]) > 0


def test_exported_artifact_has_the_documented_io(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
    graphs: list[Any],
    tmp_path: Path,
) -> None:
    destination = _export(checkpoint, tmp_path / "model.onnx", graphs[0])
    session = make_session(destination)

    assert [item.name for item in session.get_inputs()] == ["x", "edge_index", "edge_attr"]
    assert [item.name for item in session.get_outputs()] == list(ONNX_OUTPUT_NAMES)

    output = session.run(["log_latency"], {
        "x": np.ascontiguousarray(graphs[0].x.numpy()),
        "edge_index": np.ascontiguousarray(graphs[0].edge_index.numpy()),
        "edge_attr": np.ascontiguousarray(graphs[0].edge_attr.numpy()),
    })[0]
    assert np.asarray(output).size == 1


def test_scorer_rejects_edgeless_graphs(
    graphs: list[Any],
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
    tmp_path: Path,
) -> None:
    destination = _export(checkpoint, tmp_path / "model.onnx", graphs[0])
    scorer = OnnxModelScorer(destination)
    single_node = plan_to_graph(
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Plan Rows": 10,
                "Actual Rows": 10,
                "Total Cost": 12.0,
                "Plan Width": 8,
            },
            "Execution Time": 1.0,
        }
    )
    assert int(single_node.data.edge_index.size(1)) == 0
    with pytest.raises(ValueError):
        scorer.predict_log_latency(single_node)


def test_optimizer_prefers_onnx_when_the_artifact_exists(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
    graphs: list[Any],
    join_sql: str,
    explain_payload: dict[str, Any],
    catalog: SchemaCatalog,
) -> None:
    model, config, metadata, path = checkpoint
    onnx_path = path.with_suffix(".onnx")
    export_onnx(model, onnx_path, graphs[0], config, metadata)

    optimizer = load_optimizer(InferenceConfig(checkpoint_path=str(path)))
    assert optimizer.runtime == "onnx"
    assert optimizer.parameter_count > 0
    report = optimizer.optimize(join_sql, explain_payload, catalog)
    assert report.recommendations


def test_optimizer_falls_back_to_torch_without_an_artifact(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
) -> None:
    optimizer = load_optimizer(InferenceConfig(checkpoint_path=str(checkpoint[3])))
    assert optimizer.runtime == "torch"


def test_optimizer_falls_back_to_torch_for_a_corrupt_artifact(
    checkpoint: tuple[Any, ModelConfig, dict[str, Any], Path],
) -> None:
    _, _, _, path = checkpoint
    path.with_suffix(".onnx").write_bytes(b"not an onnx graph")
    optimizer = load_optimizer(InferenceConfig(checkpoint_path=str(path)))
    assert optimizer.runtime == "torch"
