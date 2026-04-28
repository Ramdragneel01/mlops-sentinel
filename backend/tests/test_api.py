
"""Integration tests for mlops-sentinel FastAPI endpoints."""

import json
from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from app import main as main_module
from app.main import app, rate_limiter, storage

client = TestClient(app)


def _override_settings(monkeypatch, **changes):
    """Apply temporary runtime setting overrides for endpoint security tests."""

    monkeypatch.setattr(main_module, "settings", replace(main_module.settings, **changes))


@pytest.fixture(autouse=True)
def reset_storage(monkeypatch):
    """Clear persisted logs between tests for deterministic assertions."""

    rate_limiter.clear()
    _override_settings(monkeypatch, api_key="", rate_limit_per_minute=600)

    with storage._connect() as connection:  # pylint: disable=protected-access
        connection.execute("DELETE FROM inference_logs")
        connection.commit()

    yield

    with storage._connect() as connection:  # pylint: disable=protected-access
        connection.execute("DELETE FROM inference_logs")
        connection.commit()

    rate_limiter.clear()


def test_health_endpoint_reports_backend_status():
    """Health endpoint should return uptime-safe diagnostics."""

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert "db_available" in payload
    assert "total_logs" in payload


def test_readiness_endpoint_reports_dependency_state():
    """Readiness endpoint should expose dependency status for orchestrator probes."""

    response = client.get("/ready")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["db_available"] is True


def test_log_ingest_and_summary_flow():
    """Posting a log should reflect in summary output and aggregates."""

    timestamp = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/log",
        json={
            "model_name": "risk-model-v1",
            "latency_ms": 123.4,
            "prediction": "approved",
            "confidence": 0.82,
            "timestamp": timestamp,
            "metadata": {"tenant": "demo"},
        },
    )

    assert response.status_code == 200
    ingest_payload = response.json()
    assert ingest_payload["status"] == "accepted"
    assert ingest_payload["log_id"] > 0

    summary_response = client.get("/summary?limit=10")
    assert summary_response.status_code == 200

    summary_payload = summary_response.json()
    assert summary_payload["total_items"] == 1
    assert len(summary_payload["items"]) == 1
    assert summary_payload["prediction_distribution"]["approved"] == 1


def test_export_csv_returns_expected_content_type():
    """CSV export endpoint should return attachment metadata and CSV body."""

    timestamp = datetime.now(timezone.utc).isoformat()
    client.post(
        "/log",
        json={
            "model_name": "risk-model-v1",
            "latency_ms": 44.2,
            "prediction": "review",
            "confidence": 0.45,
            "timestamp": timestamp,
        },
    )

    response = client.get("/export?format=csv&limit=10")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "model_name,latency_ms,prediction,confidence,timestamp" in response.text


def test_pipeline_handshake_ingest_summary_metrics_and_export_json():
    """Pipeline should expose consistent state across ingestion, summary, metrics, and export APIs."""

    model_name = "risk-model-handshake"

    for confidence in [0.41, 0.44, 0.49]:
        response = client.post(
            "/log",
            json={
                "model_name": model_name,
                "latency_ms": 980.0,
                "prediction": "review",
                "confidence": confidence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"scenario": "pipeline-handshake"},
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    summary_response = client.get(f"/summary?limit=10&model_name={model_name}")
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["total_items"] == 3
    assert summary_payload["drift_flag"] is True
    assert summary_payload["prediction_distribution"]["review"] == 3

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert "inference_latency_ms" in metrics_response.text
    assert "inference_drift_flag" in metrics_response.text

    export_response = client.get(f"/export?format=json&limit=10&model_name={model_name}")
    assert export_response.status_code == 200
    export_payload = json.loads(export_response.text)
    assert len(export_payload["items"]) == 3
    assert export_payload["items"][0]["model_name"] == model_name


def test_log_requires_api_key_when_configured(monkeypatch):
    """Log endpoint should enforce API key when runtime key is configured."""

    _override_settings(monkeypatch, api_key="secret-key")

    unauthorized = client.post(
        "/log",
        json={
            "model_name": "risk-model-v1",
            "latency_ms": 11.0,
            "prediction": "approved",
            "confidence": 0.91,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/log",
        headers={"X-API-Key": "secret-key"},
        json={
            "model_name": "risk-model-v1",
            "latency_ms": 11.0,
            "prediction": "approved",
            "confidence": 0.91,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert authorized.status_code == 200


def test_health_is_public_when_api_key_enabled(monkeypatch):
    """Health endpoint should remain public for readiness probes."""

    _override_settings(monkeypatch, api_key="secret-key")

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}


def test_log_rate_limit_returns_429(monkeypatch):
    """Log endpoint should return 429 once per-client quota is exceeded."""

    _override_settings(monkeypatch, rate_limit_per_minute=1)

    first = client.post(
        "/log",
        json={
            "model_name": "risk-model-v1",
            "latency_ms": 13.0,
            "prediction": "approved",
            "confidence": 0.88,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/log",
        json={
            "model_name": "risk-model-v1",
            "latency_ms": 14.0,
            "prediction": "approved",
            "confidence": 0.87,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert second.status_code == 429
