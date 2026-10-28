"""Model contract: architecture, attention pooling, and checkpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
import torch
from torch_geometric.data import Batch

from models.checkpoint import ModelConfig, build_model, load_checkpoint, save_checkpoint
from models.gatv2 import Gatv2CostModel, parameter_count, summarize_attention
from parsers.explain import plan_to_graph


def _graph(explain_payload: dict[str, object]):
    return plan_to_graph(explain_payload).data


def test_architecture_is_exactly_three_gatv2_layers() -> None:
    model = Gatv2CostModel()
    assert len(model.layers) == 3
    assert model.hidden_dim == 128
    assert [layer.heads for layer in model.layers] == [4, 4, 1]
    assert model.head[0].out_features == 64
    assert model.head[-1].out_features == 1


def test_forward_returns_one_prediction_per_graph(explain_payload: dict[str, object]) -> None:
    model = Gatv2CostModel()
    model.eval()
    batch = Batch.from_data_list([_graph(explain_payload), _graph(explain_payload)])
    with torch.no_grad():
        output = model(batch)
    assert output.shape == (2, 1)
    assert torch.isfinite(output).all()


def test_attention_weights_normalise_per_target_node(explain_payload: dict[str, object]) -> None:
    model = Gatv2CostModel()
    model.eval()
    batch = Batch.from_data_list([_graph(explain_payload), _graph(explain_payload)])
    with torch.no_grad():
        _, attentions = model(batch, return_attention=True)
    assert len(attentions) == 3
    edge_index, alpha = attentions[-1]
    totals = torch.zeros(int(batch.num_nodes))
    totals.index_add_(0, edge_index[1], alpha.view(-1))
    attended = totals > 0
    assert attended.any()
    assert torch.allclose(totals[attended], torch.ones_like(totals[attended]), atol=1e-5)


def test_predict_does_not_require_grad(explain_payload: dict[str, object]) -> None:
    model = Gatv2CostModel()
    value = model.predict_log_latency(_graph(explain_payload))
    assert isinstance(value, float)
    assert torch.isfinite(torch.tensor(value))


def test_summarize_attention_ranks_nodes() -> None:
    edge_index = torch.tensor([[1, 2], [0, 0]])
    alpha = torch.tensor([[0.25], [0.75]])
    summary = summarize_attention(edge_index, alpha, num_nodes=3)
    assert summary[0].node_index == 0
    assert summary[0].weight == pytest.approx(1.0)


def test_checkpoint_round_trip(tmp_path: Path, explain_payload: dict[str, object]) -> None:
    config = ModelConfig()
    model = build_model(config)
    path = tmp_path / "model.pt"
    save_checkpoint(path, model, config, metadata={"epoch": 3})

    restored, restored_config, metadata = load_checkpoint(path)
    assert restored_config == config
    assert metadata["epoch"] == 3
    assert parameter_count(restored) == parameter_count(model)

    graph = _graph(explain_payload)
    model.eval()
    with torch.no_grad():
        expected = model(graph)
        actual = restored(graph)
    assert torch.allclose(expected, actual)


def test_invalid_architecture_is_rejected() -> None:
    with pytest.raises(ValueError):
        Gatv2CostModel(layers=2)
    with pytest.raises(ValueError):
        Gatv2CostModel(hidden_dim=130, heads=4)
