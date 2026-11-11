"""Verify a roster: fetch each unique profile once, parse it, score it against the campaign."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable, Iterable

from .campaign import CampaignRules, normalize_title
from .config import Settings
from .fetcher import FetchResult, ProfileFetcher
from .parser import ProfileData, ProfileParseError, parse_profile
from .roster import Roster, RosterRow
from .security import canonical_profile_url, short_id

log = logging.getLogger("lwc_tracker.engine")


class Status(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    NOT_STARTED = "not_started"
    INVALID_URL = "invalid_url"
    NOT_FOUND = "not_found"
    FETCH_ERROR = "fetch_error"
    PARSE_ERROR = "parse_error"
    CANCELLED = "cancelled"


RETRYABLE = {Status.FETCH_ERROR, Status.PARSE_ERROR, Status.CANCELLED}


@dataclass
class StudentResult:
    row: int
    name: str
    email: str
    profile_url: str
    profile_id: str | None
    status: Status
    required: int
    badge_count: int = 0
    total_badges: int = 0
    display_name: str = ""
    matched: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: list[dict] = field(default_factory=list)
    last_earned: str | None = None
    flags: list[str] = field(default_factory=list)
    error: str | None = None
    checked_at: str = ""
    from_cache: bool = False

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["status"] = str(self.status)
        return d


class ProfileCache:
    """Small thread-safe TTL cache for successfully parsed profiles."""

    def __init__(self, ttl: int, max_items: int = 20_000):
        self.ttl, self.max_items = ttl, max_items
        self._data: OrderedDict[str, tuple[float, ProfileData]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> ProfileData | None:
        if self.ttl <= 0:
            return None
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            if time.monotonic() - item[0] > self.ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return item[1]

    def put(self, key: str, value: ProfileData) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)


def _tokens(name: str) -> set[str]:
    return {t for t in normalize_title(name).split() if len(t) > 1}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Verifier:
    def __init__(self, settings: Settings, fetcher: ProfileFetcher | None = None, cache: ProfileCache | None = None):
        self.settings = settings
        self.rules = CampaignRules(settings.campaign)
        self.fetcher = fetcher or ProfileFetcher(settings.http)
        self.cache = cache or ProfileCache(settings.http.cache_ttl_seconds)

    # ---- scoring -------------------------------------------------------------------------
    def _base(self, row: RosterRow) -> StudentResult:
        url = canonical_profile_url(row.profile_id) if row.profile_id else row.raw_url
        r = StudentResult(row=row.row, name=row.name, email=row.email, profile_url=url,
                          profile_id=row.profile_id, status=Status.FETCH_ERROR,
                          required=self.rules.required_count, checked_at=_now())
        if row.duplicate_of is not None:
            r.flags.append("shared_profile")
        return r

    def score(self, row: RosterRow, profile: ProfileData, from_cache: bool) -> StudentResult:
        r = self._base(row)
        ev = self.rules.evaluate(profile)
        r.display_name = profile.display_name
        r.total_badges = len(profile.badges)
        r.badge_count = ev.counted
        r.matched = [b.to_dict() for b in ev.matched]
        r.missing = ev.missing
        r.extra = [b.to_dict() for b in ev.extra]
        dates = [b.earned for b in ev.matched if b.earned]
        r.last_earned = max(dates).isoformat() if dates else None
        r.from_cache = from_cache
        if ev.counted >= self.rules.required_count:
            r.status = Status.COMPLETED
        elif ev.counted > 0:
            r.status = Status.IN_PROGRESS
        else:
            r.status = Status.NOT_STARTED
        if ev.outside_window:
            r.flags.append("badges_outside_window")
        if row.name and profile.display_name and not (_tokens(row.name) & _tokens(profile.display_name)):
            r.flags.append("name_mismatch")
        return r

    def failure(self, row: RosterRow, status: Status, message: str) -> StudentResult:
        r = self._base(row)
        r.status = status
        r.error = message
        return r

    # ---- orchestration -------------------------------------------------------------------
    def _check_profile(self, profile_id: str, cancel: threading.Event, force: bool) -> tuple[ProfileData | None, FetchResult | None, bool, str | None]:
        if not force:
            cached = self.cache.get(profile_id)
            if cached is not None:
                return cached, None, True, None
        res = self.fetcher.fetch(profile_id, cancel)
        if not res.ok:
            return None, res, False, None
        try:
            profile = parse_profile(res.html or "")
        except ProfileParseError as exc:
            return None, res, False, str(exc)
        except Exception:  # never let a hostile page crash a worker
            log.exception("parser failure for %s", short_id(profile_id))
            return None, res, False, "The profile page could not be read"
        self.cache.put(profile_id, profile)
        return profile, res, False, None

    def run(self, roster: Roster, on_result: Callable[[StudentResult], None], cancel: threading.Event,
            force_refresh: bool = False, only_rows: Iterable[int] | None = None) -> None:
        wanted = set(only_rows) if only_rows is not None else None
        rows = [r for r in roster.rows if wanted is None or r.row in wanted]

        by_profile: dict[str, list[RosterRow]] = {}
        for row in rows:
            if not row.profile_id:
                on_result(self.failure(row, Status.INVALID_URL, row.error or "Invalid profile link"))
            else:
                by_profile.setdefault(row.profile_id, []).append(row)

        # Shared profiles: flag every row that points at the same profile, not just the later ones.
        for group in by_profile.values():
            if len(group) > 1:
                for row in group:
                    if row.duplicate_of is None:
                        row.duplicate_of = row.row

        self.fetcher.breaker.reset()
        workers = max(1, self.settings.http.concurrency)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="verity") as pool:
            futures = {pool.submit(self._check_profile, pid, cancel, force_refresh): pid for pid in by_profile}
            for fut in as_completed(futures):
                pid = futures[fut]
                try:
                    profile, res, cached, parse_err = fut.result()
                except Exception:
                    log.exception("worker failure for %s", short_id(pid))
                    profile, res, cached, parse_err = None, None, False, "Internal error while checking"
                for row in by_profile[pid]:
                    if profile is not None:
                        on_result(self.score(row, profile, cached))
                    elif parse_err:
                        on_result(self.failure(row, Status.PARSE_ERROR, parse_err))
                    elif res is not None and res.error_kind == "not_found":
                        on_result(self.failure(row, Status.NOT_FOUND, res.message))
                    elif res is not None and res.error_kind == "cancelled":
                        on_result(self.failure(row, Status.CANCELLED, res.message))
                    else:
                        on_result(self.failure(row, Status.FETCH_ERROR, res.message if res else "Unknown error"))
