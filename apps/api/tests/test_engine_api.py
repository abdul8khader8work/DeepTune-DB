"""Phase 4 endpoints: engine status and the streaming copilot socket."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.core.config import Settings
from src.core.security import create_access_token
from src.schemas.analysis import (
    AnalysisResult,
    AttentionHotspot,
    DAGEdge,
    DAGNode,
    IndexRecommendation,
)
from src.services.runs import RecommendationState, Run

RESULT = AnalysisResult(
    run_id="run-test",
    status="completed",
    engine="gnn",
    original_metrics={"cost": 1000.0, "time_ms": 400.0},
    optimized_metrics={"cost": 250.0, "time_ms": 100.0},
    original_dag=[
        DAGNode(
            id="node_1",
            operation_type="Seq Scan",
            relation_name="orders",
            estimated_cost=1000.0,
            estimated_rows=100_000,
            gnn_attention_score=1.0,
        )
    ],
    optimized_dag=[
        DAGNode(
            id="node_1",
            operation_type="Index Scan",
            relation_name="orders",
            estimated_cost=250.0,
            estimated_rows=1_000,
            gnn_attention_score=0.9,
        )
    ],
    edges=[
        DAGEdge(id="edge_node_1_node_1", source="node_1", target="node_1", rows_transferred=1)
    ],
    recommendations=[
        IndexRecommendation(
            id="run-test:cand-1",
            sql_statement='CREATE INDEX CONCURRENTLY "idx_orders_status" ON "public"."orders" ("status")',
            target_table="orders",
            target_columns=["status"],
            predicted_speedup_factor=2.0,
            validated_speedup_factor=None,
            storage_overhead_bytes=4096,
            write_impact_percentage=1.5,
            confidence_score=0.8,
            explanation="test",
        )
    ],
    attention=[AttentionHotspot(node_index=0, operator="Seq Scan", relation="orders", weight=0.9)],
    symbolic_trace=["depth 1: 3 configurations"],
    speedup_factor=4.0,
    symbolic_candidate_count=3,
)


def _seed_run(client: TestClient, run_id: str = "run-test") -> None:
    """Inject a completed run without touching the registry's async lock."""
    state = client.app.state.deeptune
    state.runs._runs[run_id] = Run(  # noqa: SLF001 - test seam
        run_id=run_id,
        connection_id="conn-1",
        status="completed",
        progress=100,
        log="Analysis complete.",
        result=RESULT.model_copy(update={"run_id": run_id}),
        recommendations={
            item.id: RecommendationState(
                recommendation=item, connection_id="conn-1", sql_query="SELECT 1"
            )
            for item in RESULT.recommendations
        },
    )


def test_engine_status_is_public(client: TestClient) -> None:
    response = client.get("/api/v1/engine/status")
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] in {"gnn", "heuristic"}
    assert isinstance(body["available"], bool)
    assert body["label"]


def test_engine_status_reports_the_loaded_checkpoint(client: TestClient) -> None:
    body = client.get("/api/v1/engine/status").json()
    if body["available"]:
        assert body["checkpoint"]
        assert body["layers"] == 3
        assert body["heads"] == 4
    else:
        assert body["error"]


def test_engine_status_reports_the_inference_runtime(client: TestClient) -> None:
    body = client.get("/api/v1/engine/status").json()
    assert body["runtime"] in {"onnx", "torch", "heuristic"}
    if body["available"]:
        assert body["runtime"] in {"onnx", "torch"}
        # A checkpoint with a sibling .onnx must be scored by onnxruntime.
        if body["checkpoint"] and Path(f"{body['checkpoint']}.onnx").is_file():
            assert body["runtime"] == "onnx"
    else:
        assert body["runtime"] == "heuristic"


def test_copilot_streams_the_explanation(
    client: TestClient, settings: Settings
) -> None:
    _seed_run(client)
    token = create_access_token("pytest", settings)

    with client.websocket_connect(
        f"/api/v1/ws/copilot/run-test?token={token}"
    ) as socket:
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        assert ready["engine"] == "gnn"

        text = ""
        tools = []
        while True:
            frame = socket.receive_json()
            if frame["type"] == "done":
                break
            if frame["type"] == "token":
                text += frame["text"]
            elif frame["type"] == "tool":
                tools.append(frame["tool"])

    assert "400" in text
    assert "CREATE INDEX CONCURRENTLY" in text
    assert "read_plan" in tools


def test_copilot_thinks_before_every_tool_and_streams_in_small_chunks(
    client: TestClient, settings: Settings
) -> None:
    _seed_run(client)
    token = create_access_token("pytest", settings)

    frames = []
    with client.websocket_connect(
        f"/api/v1/ws/copilot/run-test?token={token}"
    ) as socket:
        socket.receive_json()
        while True:
            frame = socket.receive_json()
            if frame["type"] == "done":
                break
            frames.append(frame)

    tool_positions = [index for index, frame in enumerate(frames) if frame["type"] == "tool"]
    assert tool_positions
    for position in tool_positions:
        assert frames[position - 1]["type"] == "thinking"

    chunks = [frame["text"] for frame in frames if frame["type"] == "token"]
    assert chunks
    assert all(0 < len(chunk) <= 3 for chunk in chunks)


def test_copilot_answers_a_follow_up_question(
    client: TestClient, settings: Settings
) -> None:
    _seed_run(client)
    token = create_access_token("pytest", settings)

    with client.websocket_connect(
        f"/api/v1/ws/copilot/run-test?token={token}"
    ) as socket:
        socket.receive_json()
        while socket.receive_json()["type"] != "done":
            continue

        socket.send_json({"type": "question", "text": "what is the write risk?"})
        text = ""
        tools = []
        while True:
            frame = socket.receive_json()
            if frame["type"] == "done":
                break
            if frame["type"] == "token":
                text += frame["text"]
            elif frame["type"] == "tool":
                tools.append(frame["tool"])

    assert "write amplification" in text.lower()
    assert "symbolic_filter" in tools


def test_copilot_rejects_a_missing_token(client: TestClient) -> None:
    _seed_run(client)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/v1/ws/copilot/run-test"):
            pass
    assert excinfo.value.code == 4401


def test_copilot_rejects_an_unknown_run(
    client: TestClient, settings: Settings
) -> None:
    token = create_access_token("pytest", settings)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(
            f"/api/v1/ws/copilot/does-not-exist?token={token}"
        ):
            pass
    assert excinfo.value.code == 4404
