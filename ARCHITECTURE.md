# mlops-sentinel Architecture

This document is the canonical high-level architecture overview for the repository.
Detailed supporting notes are also available in docs/architecture.md.

## System Overview

mlops-sentinel is an inference observability platform that captures model-serving telemetry,
stores it durably, and provides both real-time and export-oriented monitoring interfaces.

## Runtime Components

1. Backend API (backend/app/main.py)
- Exposes ingestion, summary, export, health, and metrics endpoints.
- Applies validation, rate limiting, and security middleware.

2. Persistence Layer (backend/app/storage.py)
- Stores inference telemetry in SQLite.
- Supports deterministic aggregation and bounded export queries.

3. Frontend Dashboard (frontend/src/App.jsx)
- Polls summary APIs for KPI and trend rendering.
- Provides model filtering and operational visibility states.

4. Metrics Pipeline (prometheus.yml)
- Scrapes backend metrics endpoint for Prometheus-compatible monitoring.

5. Local Stack Orchestration (docker-compose.yml)
- Boots backend, frontend, and Prometheus for production-like local validation.

## Data Flow

1. A client or serving service sends telemetry to POST /log.
2. The backend validates and persists the event.
3. Metrics are updated for observability systems.
4. The frontend dashboard polls GET /summary for live operational views.
5. Prometheus scrapes GET /metrics at configured intervals.
6. Operators can export historical slices through GET /export.

## API Boundaries

1. POST /log: write-only ingestion path.
2. GET /summary: bounded aggregate read model for dashboards.
3. GET /export: bounded historical export path.
4. GET /health: runtime and storage diagnostics.
5. GET /metrics: scrape endpoint for monitoring backends.

## Security and Reliability Considerations

1. Request IDs and security headers are applied in backend middleware.
2. CORS is configured through an allowlist.
3. Ingestion throttling reduces abuse and protects backend stability.
4. CI validates core backend and frontend quality gates before merge.
