
"""Integration tests for mlops-sentinel FastAPI endpoints."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from app.main import app, storage

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_storage():
    """Clear persisted logs between tests for deterministic assertions."""

    with storage._connect() as connection:  # pylint: disable=protected-access
        connection.execute("DELETE FROM inference_logs")
        connection.commit()

    yield

    with storage._connect() as connection:  # pylint: disable=protected-access
        connection.execute("DELETE FROM inference_logs")
        connection.commit()


def test_health_endpoint_reports_backend_status():
    """Health endpoint should return uptime-safe diagnostics."""

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert "db_available" in payload
    assert "total_logs" in payload


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
