
"""FastAPI service for model inference observability."""

from __future__ import annotations

from collections import Counter as PredictionCounter
from datetime import datetime, timezone
import json
from statistics import mean
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from .config import get_settings
from .models import InferenceLog, SummaryResponse
from .rate_limit import InMemoryRateLimiter
from .storage import LogStorage

settings = get_settings()
storage = LogStorage(settings.db_path)
rate_limiter = InMemoryRateLimiter(window_seconds=60)

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

REQUEST_COUNTER = Counter(
    "http_requests_total",
    "HTTP request count",
    labelnames=("method", "endpoint", "status"),
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=("method", "endpoint"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

LATENCY_HISTOGRAM = Histogram(
    "inference_latency_ms",
    "Observed model inference latency in milliseconds",
    labelnames=("model_name",),
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2000),
)
CLASS_COUNTER = Counter(
    "inference_prediction_total",
    "Prediction class distribution",
    labelnames=("model_name", "prediction"),
)
CONFIDENCE_HISTOGRAM = Histogram(
    "inference_confidence",
    "Model confidence distribution",
    labelnames=("model_name",),
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
DRIFT_GAUGE = Gauge(
    "inference_drift_flag",
    "Drift indicator derived from rolling confidence",
    labelnames=("model_name",),
)


def _require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Validate optional API key auth for protected telemetry endpoints."""

    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


AuthDep = Annotated[None, Depends(_require_api_key)]


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach request id, security headers, and HTTP-level metrics for each request."""

    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    start = perf_counter()
    response = None

    try:
        response = await call_next(request)
    except Exception:
        REQUEST_COUNTER.labels(
            method=request.method,
            endpoint=request.url.path,
            status="500",
        ).inc()
        raise
    finally:
        elapsed = perf_counter() - start
        REQUEST_LATENCY.labels(method=request.method, endpoint=request.url.path).observe(elapsed)

    REQUEST_COUNTER.labels(method=request.method, endpoint=request.url.path, status=str(response.status_code)).inc()

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/health")
def health() -> dict[str, object]:
    """Return backend health details for deployment and uptime checks."""

    db_available = storage.is_available()
    return {
        "status": "ok" if db_available else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db_path": storage.db_path,
        "db_available": db_available,
        "total_logs": storage.count_logs(),
    }


@app.post("/log")
def ingest_log(payload: InferenceLog, request: Request, _: AuthDep = None) -> dict[str, object]:
    """Ingest one inference log event and update metrics/detection state."""

    client_key = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_key, settings.rate_limit_per_minute):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    log_id = storage.insert_log(payload)

    LATENCY_HISTOGRAM.labels(model_name=payload.model_name).observe(payload.latency_ms)
    CLASS_COUNTER.labels(model_name=payload.model_name, prediction=payload.prediction).inc()
    CONFIDENCE_HISTOGRAM.labels(model_name=payload.model_name).observe(payload.confidence)

    model_logs = storage.get_logs(limit=settings.summary_size, model_name=payload.model_name)
    avg_conf = mean(item.confidence for item in model_logs) if model_logs else 1.0
    DRIFT_GAUGE.labels(model_name=payload.model_name).set(
        1.0 if avg_conf < settings.drift_confidence_threshold else 0.0
    )

    return {
        "status": "accepted",
        "log_id": log_id,
        "drift_flag": avg_conf < settings.drift_confidence_threshold,
    }


@app.get("/summary", response_model=SummaryResponse)
def summary(
    limit: int = Query(default=settings.summary_size, ge=1, le=500),
    model_name: str | None = Query(default=None),
    _: AuthDep = None,
) -> SummaryResponse:
    """Return recent log slice and drift signal for dashboard clients."""

    items = storage.get_logs(limit=limit, model_name=model_name)
    avg_conf = mean(item.confidence for item in items) if items else None
    drift_flag = bool(avg_conf is not None and avg_conf < settings.drift_confidence_threshold)

    distribution_counter = PredictionCounter(item.prediction for item in items)
    prediction_distribution = dict(distribution_counter)

    return SummaryResponse(
        items=items,
        drift_flag=drift_flag,
        avg_confidence=avg_conf,
        total_items=storage.count_logs(model_name=model_name),
        prediction_distribution=prediction_distribution,
        drift_threshold=settings.drift_confidence_threshold,
    )


@app.get("/export")
def export_logs(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    limit: int = Query(default=1000, ge=1, le=5000),
    model_name: str | None = Query(default=None),
    _: AuthDep = None,
) -> Response:
    """Export recent logs in JSON or CSV for offline analysis."""

    items = storage.get_logs(limit=limit, model_name=model_name)

    if format == "json":
        payload = {
            "items": [
                {
                    "model_name": item.model_name,
                    "latency_ms": item.latency_ms,
                    "prediction": item.prediction,
                    "confidence": item.confidence,
                    "timestamp": item.timestamp.isoformat(),
                    "metadata": item.metadata,
                }
                for item in items
            ]
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=True),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=mlops-sentinel-export.json"},
        )

    csv_lines = ["model_name,latency_ms,prediction,confidence,timestamp"]
    for item in items:
        csv_lines.append(
            f"{item.model_name},{item.latency_ms},{item.prediction},{item.confidence},{item.timestamp.isoformat()}"
        )

    return Response(
        content="\n".join(csv_lines),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mlops-sentinel-export.csv"},
    )


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    """Expose Prometheus metrics for scraping."""

    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
