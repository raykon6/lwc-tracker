"""Load and validate campaign.toml. Values outside safe bounds are clamped, never trusted."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "campaign.toml"


class ConfigError(ValueError):
    """Raised when the configuration file cannot be used."""


@dataclass(frozen=True)
class HttpSettings:
    requests_per_second: float = 1.0
    burst: int = 2
    concurrency: int = 3
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    max_retries: int = 3
    backoff_base: float = 1.5
    backoff_cap: float = 30.0
    max_response_bytes: int = 2_000_000
    cache_ttl_seconds: int = 900
    circuit_breaker_threshold: int = 8
    user_agent: str = "Verity-LWC-Tracker/1.0 (+campaign skill badge verifier)"


@dataclass(frozen=True)
class CampaignSettings:
    name: str = "Learn With Communities"
    required_count: int = 10
    required_badges: tuple[str, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    start_date: date | None = None
    end_date: date | None = None


@dataclass(frozen=True)
class LimitSettings:
    max_upload_bytes: int = 1_048_576
    max_rows: int = 5000
    max_active_jobs: int = 2
    job_ttl_seconds: int = 3600


@dataclass(frozen=True)
class Settings:
    campaign: CampaignSettings
    http: HttpSettings
    limits: LimitSettings


def _clamp(value: Any, lo: float, hi: float, kind: type, key: str) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"'{key}' must be a number")
    return kind(min(max(value, lo), hi))


def _text(value: Any, key: str, max_len: int = 200) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"'{key}' must be a string")
    value = value.strip()
    if len(value) > max_len or any(ord(c) < 0x20 for c in value):
        raise ConfigError(f"'{key}' is too long or contains control characters")
    return value


def _date(value: Any, key: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value, key, 10))
    except ValueError as exc:
        raise ConfigError(f"'{key}' must be YYYY-MM-DD") from exc


def load_settings(path: Path | str | None = None) -> Settings:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.is_file():
        return Settings(CampaignSettings(), HttpSettings(), LimitSettings())
    try:
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read {cfg_path.name}: {exc}") from exc

    c = raw.get("campaign", {})
    h = raw.get("http", {})
    lim = raw.get("limits", {})

    badges_raw = c.get("required_badges", [])
    if not isinstance(badges_raw, list) or len(badges_raw) > 200:
        raise ConfigError("'required_badges' must be a list of at most 200 titles")
    badges = tuple(_text(b, "required_badges[]") for b in badges_raw if str(b).strip())

    aliases_raw = c.get("aliases", {})
    if not isinstance(aliases_raw, dict):
        raise ConfigError("'campaign.aliases' must be a table")
    aliases = {_text(k, "alias"): _text(v, "alias target") for k, v in aliases_raw.items()}

    required_default = len(badges) if badges else 10
    campaign = CampaignSettings(
        name=_text(c.get("name", "Learn With Communities"), "campaign.name", 80),
        required_count=_clamp(c.get("required_count", required_default), 1, 200, int, "required_count"),
        required_badges=badges,
        aliases=aliases,
        start_date=_date(c.get("start_date"), "start_date"),
        end_date=_date(c.get("end_date"), "end_date"),
    )
    if campaign.start_date and campaign.end_date and campaign.start_date > campaign.end_date:
        raise ConfigError("start_date is after end_date")

    d = HttpSettings()
    http = HttpSettings(
        requests_per_second=_clamp(h.get("requests_per_second", d.requests_per_second), 0.1, 5.0, float, "requests_per_second"),
        burst=_clamp(h.get("burst", d.burst), 1, 10, int, "burst"),
        concurrency=_clamp(h.get("concurrency", d.concurrency), 1, 8, int, "concurrency"),
        connect_timeout=_clamp(h.get("connect_timeout", d.connect_timeout), 1, 30, float, "connect_timeout"),
        read_timeout=_clamp(h.get("read_timeout", d.read_timeout), 1, 60, float, "read_timeout"),
        max_retries=_clamp(h.get("max_retries", d.max_retries), 0, 6, int, "max_retries"),
        backoff_base=_clamp(h.get("backoff_base", d.backoff_base), 0.1, 10, float, "backoff_base"),
        backoff_cap=_clamp(h.get("backoff_cap", d.backoff_cap), 1, 120, float, "backoff_cap"),
        max_response_bytes=_clamp(h.get("max_response_bytes", d.max_response_bytes), 50_000, 10_000_000, int, "max_response_bytes"),
        cache_ttl_seconds=_clamp(h.get("cache_ttl_seconds", d.cache_ttl_seconds), 0, 86_400, int, "cache_ttl_seconds"),
        circuit_breaker_threshold=_clamp(h.get("circuit_breaker_threshold", d.circuit_breaker_threshold), 2, 50, int, "circuit_breaker_threshold"),
        user_agent=_text(h.get("user_agent", d.user_agent), "user_agent", 150),
    )

    dl = LimitSettings()
    limits = LimitSettings(
        max_upload_bytes=_clamp(lim.get("max_upload_bytes", dl.max_upload_bytes), 1024, 10 * 1024 * 1024, int, "max_upload_bytes"),
        max_rows=_clamp(lim.get("max_rows", dl.max_rows), 1, 50_000, int, "max_rows"),
        max_active_jobs=_clamp(lim.get("max_active_jobs", dl.max_active_jobs), 1, 10, int, "max_active_jobs"),
        job_ttl_seconds=_clamp(lim.get("job_ttl_seconds", dl.job_ttl_seconds), 60, 86_400, int, "job_ttl_seconds"),
    )
    return Settings(campaign, http, limits)
