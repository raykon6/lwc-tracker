"""Polite, bounded HTTP fetching of public profiles.

Controls in this module:
  * Global token bucket (requests per second + burst), shared by every worker and job.
  * Bounded concurrency is enforced by the caller's worker pool.
  * Retries only for transient failures (timeouts, connection errors, 429, 5xx), with
    exponential backoff, full jitter and Retry-After support.
  * Circuit breaker: stop hammering an upstream that keeps failing.
  * Redirects are never followed. A profile that redirects is reported as not found.
  * Responses are streamed and capped in size. Only text/html is accepted.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping

import requests
from requests.structures import CaseInsensitiveDict

from .config import HttpSettings
from .security import canonical_profile_url, short_id

log = logging.getLogger("lwc_tracker.fetcher")

Transport = Callable[[str], "RawResponse"]


@dataclass
class RawResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class ResponseTooLarge(Exception):
    pass


@dataclass
class FetchResult:
    ok: bool
    html: str | None = None
    status_code: int | None = None
    error_kind: str | None = None  # not_found | blocked | http | timeout | network | too_large | rate_limited | circuit_open | cancelled
    message: str = ""
    attempts: int = 0
    elapsed_ms: int = 0


class TokenBucket:
    """Thread-safe token bucket. `pause()` lets a 429 slow down every worker at once."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.paused_until = 0.0
        self.lock = threading.Lock()

    def acquire(self, cancel: threading.Event) -> bool:
        while not cancel.is_set():
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if now >= self.paused_until and self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = max(self.paused_until - now, (1 - self.tokens) / self.rate)
            cancel.wait(min(max(wait, 0.01), 0.5))
        return False

    def pause(self, seconds: float) -> None:
        with self.lock:
            self.paused_until = max(self.paused_until, time.monotonic() + seconds)
            self.tokens = 0.0


class CircuitBreaker:
    def __init__(self, threshold: int):
        self.threshold = threshold
        self.failures = 0
        self.lock = threading.Lock()

    def success(self) -> None:
        with self.lock:
            self.failures = 0

    def failure(self) -> None:
        with self.lock:
            self.failures += 1

    @property
    def open(self) -> bool:
        with self.lock:
            return self.failures >= self.threshold

    def reset(self) -> None:
        self.success()


def parse_retry_after(value: str | None, cap: float) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    return min(max(seconds, 0.0), cap)


class ProfileFetcher:
    def __init__(self, http: HttpSettings, transport: Transport | None = None):
        self.http = http
        self.bucket = TokenBucket(http.requests_per_second, http.burst)
        self.breaker = CircuitBreaker(http.circuit_breaker_threshold)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": http.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9",
            "Accept-Language": "en-US,en;q=0.8",
        })
        self._session.trust_env = False  # ignore ambient proxy and .netrc settings
        self._transport = transport or self._default_transport
        self.stats_lock = threading.Lock()
        self.stats = {"requests": 0, "retries": 0, "rate_limited": 0}

    def _default_transport(self, url: str) -> RawResponse:
        resp = self._session.get(
            url,
            timeout=(self.http.connect_timeout, self.http.read_timeout),
            allow_redirects=False,
            stream=True,
        )
        try:
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > self.http.max_response_bytes:
                raise ResponseTooLarge()
            chunks, size = [], 0
            for chunk in resp.iter_content(chunk_size=16_384):
                size += len(chunk)
                if size > self.http.max_response_bytes:
                    raise ResponseTooLarge()
                chunks.append(chunk)
            return RawResponse(resp.status_code, CaseInsensitiveDict(resp.headers), b"".join(chunks))
        finally:
            resp.close()

    def _backoff(self, attempt: int) -> float:
        ceiling = min(self.http.backoff_cap, self.http.backoff_base * (2 ** (attempt - 1)))
        return random.uniform(ceiling / 2, ceiling)  # jitter only; not security-relevant

    def _count(self, key: str) -> None:
        with self.stats_lock:
            self.stats[key] += 1

    def fetch(self, profile_id: str, cancel: threading.Event) -> FetchResult:
        url = canonical_profile_url(profile_id)  # raises if the ID was not validated
        started = time.monotonic()
        attempts = 0
        last = FetchResult(ok=False, error_kind="network", message="No attempt made")

        def done(result: FetchResult) -> FetchResult:
            result.attempts = attempts
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            return result

        while attempts <= self.http.max_retries:
            if cancel.is_set():
                return done(FetchResult(False, error_kind="cancelled", message="Run cancelled"))
            if self.breaker.open:
                return done(FetchResult(False, error_kind="circuit_open",
                                        message="Stopped: the profile site kept failing. Try again later."))
            if not self.bucket.acquire(cancel):
                return done(FetchResult(False, error_kind="cancelled", message="Run cancelled"))

            attempts += 1
            self._count("requests")
            retry_delay: float | None = None
            try:
                raw = self._transport(url)
            except ResponseTooLarge:
                return done(FetchResult(False, error_kind="too_large", message="Profile page exceeded the size limit"))
            except requests.Timeout:
                self.breaker.failure()
                last = FetchResult(False, error_kind="timeout", message="The profile site did not respond in time")
                retry_delay = self._backoff(attempts)
            except requests.RequestException as exc:
                self.breaker.failure()
                last = FetchResult(False, error_kind="network", message=f"Network error ({type(exc).__name__})")
                retry_delay = self._backoff(attempts)
            else:
                status = raw.status
                headers = CaseInsensitiveDict(raw.headers or {})
                if status == 200:
                    ctype = str(headers.get("Content-Type", "")).lower()
                    if "text/html" not in ctype:
                        return done(FetchResult(False, status_code=status, error_kind="http",
                                                message="Unexpected content type from the profile site"))
                    self.breaker.success()
                    return done(FetchResult(True, html=raw.body.decode("utf-8", errors="replace"), status_code=200))
                if 300 <= status < 400 or status in (404, 410):
                    self.breaker.success()
                    return done(FetchResult(False, status_code=status, error_kind="not_found",
                                            message="Profile not found or not public"))
                if status == 429:
                    self._count("rate_limited")
                    wait = parse_retry_after(headers.get("Retry-After"), self.http.backoff_cap * 2)
                    retry_delay = wait if wait is not None else self._backoff(attempts)
                    self.bucket.pause(retry_delay)
                    last = FetchResult(False, status_code=429, error_kind="rate_limited",
                                       message="The profile site asked us to slow down")
                elif status >= 500:
                    self.breaker.failure()
                    last = FetchResult(False, status_code=status, error_kind="http",
                                       message=f"The profile site returned an error ({status})")
                    retry_delay = self._backoff(attempts)
                elif status == 403:
                    self.breaker.failure()
                    return done(FetchResult(False, status_code=403, error_kind="blocked",
                                            message="Access was refused by the profile site (403)"))
                else:
                    return done(FetchResult(False, status_code=status, error_kind="http",
                                            message=f"Unexpected response ({status})"))

            if attempts > self.http.max_retries:
                break
            self._count("retries")
            log.info("retrying %s after %s (%.1fs)", short_id(profile_id), last.error_kind, retry_delay or 0)
            if cancel.wait(retry_delay or 0):
                return done(FetchResult(False, error_kind="cancelled", message="Run cancelled"))

        return done(last)
