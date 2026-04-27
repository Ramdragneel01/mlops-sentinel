
"""Runtime configuration for mlops-sentinel backend service."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    """Represents backend configuration loaded from environment variables."""

    app_name: str
    app_version: str
    db_path: str
    cors_origins: list[str]
    summary_size: int
    drift_confidence_threshold: float
    rate_limit_per_minute: int
    api_key: str
    allowed_hosts: list[str]
    gzip_minimum_size: int
    max_payload_bytes: int
    enable_hsts: bool


def _get_csv_env(name: str, default: str) -> list[str]:
    """Parse comma-delimited environment values into a trimmed list."""

    raw_value = os.getenv(name, default)
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    return values


def _get_int_env(name: str, default: int, minimum: int) -> int:
    """Read integer environment variable and enforce lower bound."""

    raw_value = os.getenv(name, str(default)).strip()
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc

    if parsed_value < minimum:
        raise ValueError(f"Environment variable {name} must be >= {minimum}")
    return parsed_value


def _get_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read floating point environment variable and enforce inclusive range."""

    raw_value = os.getenv(name, str(default)).strip()
    try:
        parsed_value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be numeric") from exc

    if parsed_value < minimum or parsed_value > maximum:
        raise ValueError(
            f"Environment variable {name} must be between {minimum} and {maximum}"
        )
    return parsed_value


def _get_bool_env(name: str, default: bool) -> bool:
    """Parse environment variable as boolean using common truthy/falsy values."""

    raw_value = os.getenv(name, "true" if default else "false").strip().lower()
    if raw_value in {"1", "true", "yes", "y", "on"}:
        return True
    if raw_value in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be boolean-like")


def _get_secret_env(name: str, default: str = "") -> str:
    """Load secret from direct env var or file path in corresponding *_FILE variable."""

    direct_value = os.getenv(name)
    if direct_value and direct_value.strip():
        return direct_value.strip()

    file_var_name = f"{name}_FILE"
    secret_file_path = os.getenv(file_var_name, "").strip()
    if not secret_file_path:
        return default

    try:
        with open(secret_file_path, encoding="utf-8") as secret_file:
            secret_value = secret_file.read().strip()
    except OSError as exc:
        raise ValueError(
            f"Environment variable {file_var_name} points to unreadable file: {secret_file_path}"
        ) from exc

    if not secret_value:
        raise ValueError(
            f"Environment variable {file_var_name} points to an empty secret file: {secret_file_path}"
        )
    return secret_value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from environment variables with safe defaults."""

    app_name = os.getenv("MLOPS_APP_NAME", "mlops-sentinel")
    app_version = os.getenv("MLOPS_APP_VERSION", "0.2.0")
    db_path = os.getenv("MLOPS_DB_PATH", "./data/sentinel.db")

    cors_origins = _get_csv_env(
        "MLOPS_CORS_ORIGINS",
        "http://127.0.0.1:4173,http://localhost:4173",
    )
    allowed_hosts = _get_csv_env("MLOPS_ALLOWED_HOSTS", "*")

    summary_size = _get_int_env("MLOPS_SUMMARY_SIZE", default=100, minimum=1)
    drift_confidence_threshold = _get_float_env(
        "MLOPS_DRIFT_THRESHOLD",
        default=0.55,
        minimum=0.0,
        maximum=1.0,
    )
    rate_limit_per_minute = _get_int_env("MLOPS_RATE_LIMIT_PER_MINUTE", default=600, minimum=1)
    gzip_minimum_size = _get_int_env("MLOPS_GZIP_MINIMUM_SIZE", default=1024, minimum=256)
    max_payload_bytes = _get_int_env("MLOPS_MAX_PAYLOAD_BYTES", default=65536, minimum=1024)
    enable_hsts = _get_bool_env("MLOPS_ENABLE_HSTS", default=False)
    api_key = _get_secret_env("MLOPS_API_KEY", default="")

    return Settings(
        app_name=app_name,
        app_version=app_version,
        db_path=db_path,
        cors_origins=cors_origins,
        summary_size=summary_size,
        drift_confidence_threshold=drift_confidence_threshold,
        rate_limit_per_minute=rate_limit_per_minute,
        api_key=api_key,
        allowed_hosts=allowed_hosts,
        gzip_minimum_size=gzip_minimum_size,
        max_payload_bytes=max_payload_bytes,
        enable_hsts=enable_hsts,
    )
