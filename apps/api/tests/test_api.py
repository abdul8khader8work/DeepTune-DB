"""HTTP contract: health, auth, validation, legacy aliases, CORS."""

from fastapi.testclient import TestClient

ANALYZE_BODY = {
    "connection_id": "does-not-exist",
    "sql_query": "SELECT * FROM users WHERE id = 1",
    "optimization_goal": "balanced",
}


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["auth_enabled"] is True
    assert body["metadata_store"] == "memory"


def test_openapi_is_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/queries/analyze" in paths
    assert "/api/v1/databases/connect" in paths


def test_protected_route_requires_token(client: TestClient) -> None:
    response = client.get("/api/v1/databases/anything/schema")
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "UNAUTHORIZED"


def test_invalid_token_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/databases/anything/schema",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


def test_unknown_connection_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(
        "/api/v1/databases/missing/schema", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "CONNECTION_NOT_FOUND"


def test_non_select_sql_is_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/queries/analyze",
        json={**ANALYZE_BODY, "sql_query": "DELETE FROM users"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "INVALID_SQL"


def test_body_validation_uses_error_envelope(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/queries/analyze",
        json={"connection_id": "x", "sql_query": "SELECT 1", "optimization_goal": "nope"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "VALIDATION_ERROR"


def test_analyze_accepts_and_background_run_fails_gracefully(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    accepted = client.post(
        "/api/v1/queries/analyze", json=ANALYZE_BODY, headers=auth_headers
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]

    status = client.get(f"/api/v1/queries/{run_id}/status", headers=auth_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "failed"

    results = client.get(f"/api/v1/queries/{run_id}/results", headers=auth_headers)
    assert results.status_code == 409
    assert results.json()["detail"]["error_code"] == "RUN_FAILED"


def test_legacy_alias_is_protected(client: TestClient) -> None:
    response = client.post("/api/connect", json={})
    assert response.status_code == 401


def test_legacy_analyze_alias_validates_sql(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/analyze",
        json={**ANALYZE_BODY, "sql_query": "UPDATE users SET email = 'x'"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "INVALID_SQL"


def test_cors_allows_only_the_web_origin(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"

    blocked = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in blocked.headers
