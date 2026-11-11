"""Runtime configuration, loaded from environment variables (12-factor style)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(raw))
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """All tunables for the service. Defaults are safe for a public demo."""

    # --- Model access -----------------------------------------------------------------
    # Vertex AI (default): authenticates with Application Default Credentials,
    # i.e. the Cloud Run service account in production. No API keys in code.
    google_cloud_project: str | None
    google_cloud_location: str
    # Optional alternative: a Gemini API key from Google AI Studio.
    gemini_api_key: str | None

    live_model: str
    voice_name: str
    temperature: float | None

    # --- Voice activity detection (unset = Live API defaults) --------------------------
    vad_start_sensitivity: str | None  # LOW | HIGH
    vad_end_sensitivity: str | None  # LOW | HIGH
    vad_silence_ms: int | None

    # --- Guard rails for a public demo -------------------------------------------------
    max_call_seconds: int
    max_concurrent_calls: int
    allowed_origins: tuple[str, ...]

    log_level: str

    @property
    def use_vertex_ai(self) -> bool:
        return not self.gemini_api_key


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return _env_int(name, 0, minimum=0) if raw else None


def _env_optional_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _env_choice(name: str, choices: tuple[str, ...]) -> str | None:
    raw = os.getenv(name, "").strip().upper()
    if not raw:
        return None
    if raw not in choices:
        raise ValueError(f"Environment variable {name} must be one of {choices}, got {raw!r}")
    return raw


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        live_model=os.getenv("LIVE_MODEL", "gemini-3.8-live"),
        voice_name=os.getenv("VOICE_NAME", "Kore"),
        temperature=_env_optional_float("TEMPERATURE"),
        vad_start_sensitivity=_env_choice("VAD_START_SENSITIVITY", ("LOW", "HIGH")),
        vad_end_sensitivity=_env_choice("VAD_END_SENSITIVITY", ("LOW", "HIGH")),
        vad_silence_ms=_env_optional_int("VAD_SILENCE_MS"),
        max_call_seconds=_env_int("MAX_CALL_SECONDS", 600, minimum=30),
        max_concurrent_calls=_env_int("MAX_CONCURRENT_CALLS", 4),
        allowed_origins=_env_list("ALLOWED_ORIGINS"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
