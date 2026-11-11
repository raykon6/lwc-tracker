"""In-memory roster and job store for the web app. IDs are unguessable, entries expire."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field

from .engine import RETRYABLE, Status, StudentResult, Verifier
from .roster import Roster

log = logging.getLogger("lwc_tracker.jobs")


class JobLimitError(RuntimeError):
    pass


def new_id() -> str:
    return secrets.token_urlsafe(18)


@dataclass
class Job:
    id: str
    roster_id: str
    total: int
    created: float = field(default_factory=time.time)
    state: str = "queued"  # queued | running | done | cancelled | failed
    started: float | None = None
    finished: float | None = None
    error: str | None = None
    results: list[dict] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, result: StudentResult) -> None:
        with self.lock:
            d = result.to_dict()
            d["seq"] = len(self.results)
            self.results.append(d)

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            done = len(self.results)
            counts: dict[str, int] = {}
            for r in self.results:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            elapsed = ((self.finished or time.time()) - self.started) if self.started else 0.0
            rate = done / elapsed if elapsed > 0 else 0.0
            remaining = self.total - done
            eta = remaining / rate if rate > 0 and self.state == "running" else None
            return {
                "id": self.id,
                "roster_id": self.roster_id,
                "state": self.state,
                "total": self.total,
                "done": done,
                "counts": counts,
                "elapsed_s": round(elapsed, 1),
                "rate_per_s": round(rate, 2),
                "eta_s": round(eta) if eta is not None else None,
                "error": self.error,
                "cursor": done,
                "results": self.results[max(0, since):],
            }


class JobManager:
    def __init__(self, verifier: Verifier, max_active: int, ttl: int):
        self.verifier = verifier
        self.max_active = max_active
        self.ttl = ttl
        self.rosters: dict[str, tuple[float, Roster]] = {}
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def _purge(self) -> None:
        cutoff = time.time() - self.ttl
        for rid in [k for k, (t, _) in self.rosters.items() if t < cutoff]:
            self.rosters.pop(rid, None)
        for jid in [k for k, j in self.jobs.items() if j.created < cutoff and j.state != "running"]:
            self.jobs.pop(jid, None)

    def add_roster(self, roster: Roster) -> str:
        with self.lock:
            self._purge()
            if len(self.rosters) > 200:
                raise JobLimitError("Too many rosters are stored. Try again later.")
            rid = new_id()
            self.rosters[rid] = (time.time(), roster)
            return rid

    def get_roster(self, rid: str) -> Roster | None:
        with self.lock:
            item = self.rosters.get(rid)
            return item[1] if item else None

    def get(self, jid: str) -> Job | None:
        with self.lock:
            return self.jobs.get(jid)

    def start(self, rid: str, force_refresh: bool = False, retry_of: str | None = None) -> Job:
        roster = self.get_roster(rid)
        if roster is None:
            raise KeyError("roster")
        only_rows = None
        kept: list[dict] = []
        if retry_of:
            prev = self.get(retry_of)
            if prev is None or prev.roster_id != rid:
                raise KeyError("job")
            if prev.state in ("queued", "running"):
                raise ValueError("That run is still in progress.")
            with prev.lock:
                kept = [dict(r) for r in prev.results if Status(r["status"]) not in RETRYABLE]
            done_rows = {r["row"] for r in kept}
            only_rows = {r.row for r in roster.rows if r.row not in done_rows}
            if not only_rows:
                raise ValueError("Nothing to retry: every row finished.")
        with self.lock:
            self._purge()
            active = sum(1 for j in self.jobs.values() if j.state in ("queued", "running"))
            if active >= self.max_active:
                raise JobLimitError("Another verification run is in progress. Wait for it to finish.")
            job = Job(id=new_id(), roster_id=rid, total=len(roster.rows))
            # A retry run starts with the rows that already finished, so it is always a full picture.
            job.results = [dict(r, seq=i) for i, r in enumerate(kept)]
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, roster, force_refresh, only_rows),
                         name=f"job-{job.id[:6]}", daemon=True).start()
        return job

    def _run(self, job: Job, roster: Roster, force: bool, only_rows: set[int] | None) -> None:
        job.state, job.started = "running", time.time()
        try:
            self.verifier.run(roster, job.add, job.cancel, force_refresh=force, only_rows=only_rows)
            job.state = "cancelled" if job.cancel.is_set() else "done"
        except Exception:
            log.exception("job %s failed", job.id[:6])
            job.state, job.error = "failed", "The run stopped because of an internal error."
        finally:
            job.finished = time.time()

    def cancel(self, jid: str) -> bool:
        job = self.get(jid)
        if job is None:
            return False
        job.cancel.set()
        return True
