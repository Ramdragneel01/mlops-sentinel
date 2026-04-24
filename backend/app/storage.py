
"""SQLite-backed persistence layer for inference log events."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
from typing import Any

from .models import InferenceLog


class LogStorage:
    """Stores and queries inference logs in SQLite for summary and export endpoints."""

    def __init__(self, db_path: str) -> None:
        """Initialize storage and ensure schema exists before serving requests."""

        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @property
    def db_path(self) -> str:
        """Expose configured database path for diagnostics."""

        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        """Create a SQLite connection configured for row-based access."""

        connection = sqlite3.connect(self._db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        """Create tables and indexes required by log ingestion and queries."""

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inference_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    prediction TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_inference_logs_model_ts
                ON inference_logs (model_name, timestamp DESC)
                """
            )
            connection.commit()

    def insert_log(self, payload: InferenceLog) -> int:
        """Persist one inference record and return generated primary key."""

        metadata_json = json.dumps(payload.metadata or {}, ensure_ascii=True)
        timestamp = payload.timestamp.astimezone(timezone.utc).isoformat()

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO inference_logs (
                    model_name,
                    latency_ms,
                    prediction,
                    confidence,
                    timestamp,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.model_name,
                    payload.latency_ms,
                    payload.prediction,
                    payload.confidence,
                    timestamp,
                    metadata_json,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def get_logs(self, limit: int, model_name: str | None = None) -> list[InferenceLog]:
        """Fetch most recent logs optionally filtered by model name."""

        if model_name:
            query = (
                "SELECT model_name, latency_ms, prediction, confidence, timestamp, metadata_json "
                "FROM inference_logs WHERE model_name = ? ORDER BY timestamp DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (model_name, limit)
        else:
            query = (
                "SELECT model_name, latency_ms, prediction, confidence, timestamp, metadata_json "
                "FROM inference_logs ORDER BY timestamp DESC LIMIT ?"
            )
            params = (limit,)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        items = [self._row_to_inference_log(row) for row in rows]
        items.reverse()
        return items

    def count_logs(self, model_name: str | None = None) -> int:
        """Return total count of logs optionally filtered by model name."""

        with self._connect() as connection:
            if model_name:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM inference_logs WHERE model_name = ?",
                    (model_name,),
                ).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) AS count FROM inference_logs").fetchone()

        return int(row["count"] if row else 0)

    def is_available(self) -> bool:
        """Return True when SQLite backend can be queried successfully."""

        try:
            with self._connect() as connection:
                connection.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    @staticmethod
    def _row_to_inference_log(row: sqlite3.Row) -> InferenceLog:
        """Convert one SQLite row into InferenceLog domain model."""

        metadata = json.loads(row["metadata_json"] or "{}")
        timestamp = datetime.fromisoformat(row["timestamp"])
        return InferenceLog(
            model_name=row["model_name"],
            latency_ms=row["latency_ms"],
            prediction=row["prediction"],
            confidence=row["confidence"],
            timestamp=timestamp,
            metadata=metadata,
        )
