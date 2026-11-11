"""FastAPI web app: upload a roster, run verification, watch progress, export results."""
from __future__ import annotations

import hmac
import logging
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import Settings
from ..engine import Verifier
from ..export import to_csv, to_json
from ..jobs import JobLimitError, JobManager
from ..roster import RosterError, load_roster, roster_from_lines

log = logging.getLogger("lwc_tracker.web")
STATIC = Path(__file__).resolve().parent / "static"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,40}$")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SlidingWindowLimiter:
    """Per-client inbound limiter: at most `limit` requests per `window` seconds per bucket."""

    def __init__(self) -> None:
        self.hits: dict[tuple[str, str], deque[float]] = {}
        self.lock = threading.Lock()

    def allow(self, client: str, bucket: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            q = self.hits.setdefault((client, bucket), deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(window - (now - q[0])) + 1)
            q.append(now)
            if len(self.hits) > 10_000:  # bound memory under a flood of distinct clients
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < window}
            return True, 0


LIMITS = {"upload": 20, "start": 10, "poll": 300, "export": 30, "default": 120}


class TextRoster(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)


class StartJob(BaseModel):
    roster_id: str = Field(min_length=20, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    force_refresh: bool = False
    retry_of: str | None = Field(default=None, min_length=20, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")


def _bucket(method: str, path: str) -> str:
    if path.startswith("/api/roster"):
        return "upload"
    if path == "/api/jobs" and method == "POST":
        return "start"
    if path.endswith("/export"):
        return "export"
    if path.startswith("/api/jobs/"):
        return "poll"
    return "default"


def _check_id(value: str) -> str:
    if not _ID_RE.match(value):
        raise HTTPException(status_code=404, detail="Not found")
    return value


def create_app(settings: Settings, access_token: str | None = None, allowed_hosts: list[str] | None = None,
               verifier: Verifier | None = None, demo: bool = False) -> FastAPI:
    app = FastAPI(title="Verity", docs_url=None, redoc_url=None, openapi_url=None)
    verifier = verifier or Verifier(settings)
    jobs = JobManager(verifier, settings.limits.max_active_jobs, settings.limits.job_ttl_seconds)
    limiter = SlidingWindowLimiter()
    max_body = settings.limits.max_upload_bytes + 64 * 1024
    app.state.jobs = jobs

    # Requests whose Host header is not ours are refused (blocks DNS-rebinding attacks).
    # /healthz is exempt so a hosting platform can probe the container by its internal address.
    trusted_hosts = {h.lower() for h in (allowed_hosts or ["127.0.0.1", "localhost", "[::1]", "testserver"])}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        headers = dict(SECURITY_HEADERS)
        if path != "/healthz":
            host = request.headers.get("host", "").lower()
            hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            if hostname not in trusted_hosts:
                return JSONResponse({"detail": "Invalid host header."}, status_code=400, headers=headers)
        if request.url.scheme == "https":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if path.startswith("/api/"):
            headers["Cache-Control"] = "no-store"
            client = request.client.host if request.client else "unknown"
            ok, retry = limiter.allow(client, _bucket(request.method, path), LIMITS[_bucket(request.method, path)])
            if not ok:
                return JSONResponse({"detail": "Too many requests. Slow down and try again."}, status_code=429,
                                    headers={**headers, "Retry-After": str(retry)})

            if access_token:
                supplied = request.headers.get("authorization", "")
                expected = f"Bearer {access_token}"
                if not hmac.compare_digest(supplied.encode(), expected.encode()):
                    return JSONResponse({"detail": "Access token required."}, status_code=401, headers=headers)

            if request.method not in ("GET", "HEAD", "OPTIONS"):
                # CSRF defence: a custom header cannot be sent cross-site without a CORS preflight,
                # and this app never grants CORS. Also reject a foreign Origin outright.
                if request.headers.get("x-verity-request") != "1":
                    return JSONResponse({"detail": "Missing request header."}, status_code=403, headers=headers)
                origin = request.headers.get("origin")
                if origin and origin.split("://", 1)[-1] != request.headers.get("host", ""):
                    return JSONResponse({"detail": "Cross-origin request refused."}, status_code=403, headers=headers)
                length = request.headers.get("content-length")
                if length is None or not length.isdigit():
                    return JSONResponse({"detail": "Content-Length is required."}, status_code=411, headers=headers)
                if int(length) > max_body:
                    return JSONResponse({"detail": "Request body is too large."}, status_code=413, headers=headers)

        response = await call_next(request)
        for k, v in headers.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, __: RequestValidationError):
        return JSONResponse({"detail": "The request was not valid."}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        ref = uuid.uuid4().hex[:8]
        log.error("unhandled error ref=%s: %s", ref, type(exc).__name__, exc_info=exc)
        return JSONResponse({"detail": f"Something went wrong (ref {ref})."}, status_code=500)

    # ---- pages ---------------------------------------------------------------------------
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ---- API -----------------------------------------------------------------------------
    @app.get("/api/config")
    async def config():
        c, h = settings.campaign, settings.http
        return {
            "campaign": {
                "name": c.name,
                "required_count": c.required_count,
                "required_badges": list(c.required_badges),
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
            },
            "http": {
                "requests_per_second": h.requests_per_second,
                "concurrency": h.concurrency,
                "max_retries": h.max_retries,
                "cache_ttl_seconds": h.cache_ttl_seconds,
            },
            "limits": {"max_upload_bytes": settings.limits.max_upload_bytes, "max_rows": settings.limits.max_rows},
            "auth_required": bool(access_token),
            "demo": demo,
        }

    def _roster_response(roster) -> dict:
        rid = jobs.add_roster(roster)
        issues = [r.to_dict() for r in roster.rows if r.error or r.duplicate_of is not None][:200]
        return {"roster_id": rid, "summary": roster.summary(), "issues": issues}

    @app.post("/api/roster")
    async def upload_roster(file: UploadFile = File(...)):
        name = (file.filename or "").lower()
        if not name.endswith((".csv", ".txt")):
            raise HTTPException(status_code=415, detail="Upload a .csv file.")
        data = await file.read(settings.limits.max_upload_bytes + 1)
        await file.close()
        try:
            roster = load_roster(data, settings.limits.max_upload_bytes, settings.limits.max_rows)
            return _roster_response(roster)
        except RosterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except JobLimitError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None

    @app.post("/api/roster/text")
    async def paste_roster(body: TextRoster):
        try:
            roster = roster_from_lines(body.text, settings.limits.max_upload_bytes, settings.limits.max_rows)
            return _roster_response(roster)
        except RosterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except JobLimitError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None

    if demo:
        @app.post("/api/roster/demo")
        async def demo_roster():
            from ..demo import demo_roster_csv

            data = demo_roster_csv().encode("utf-8")
            return _roster_response(load_roster(data, settings.limits.max_upload_bytes, settings.limits.max_rows))

    @app.post("/api/jobs")
    async def start_job(body: StartJob):
        try:
            job = jobs.start(body.roster_id, force_refresh=body.force_refresh, retry_of=body.retry_of)
        except KeyError:
            raise HTTPException(status_code=404, detail="That roster or run has expired. Upload it again.") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except JobLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        return {"job_id": job.id, "total": job.total}

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str, since: int = 0):
        job = jobs.get(_check_id(job_id))
        if job is None:
            raise HTTPException(status_code=404, detail="Run not found or expired.")
        return job.snapshot(since=min(max(since, 0), 1_000_000))

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        if not jobs.cancel(_check_id(job_id)):
            raise HTTPException(status_code=404, detail="Run not found or expired.")
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/export")
    async def export(job_id: str, format: str = "csv"):
        job = jobs.get(_check_id(job_id))
        if job is None:
            raise HTTPException(status_code=404, detail="Run not found or expired.")
        snap = job.snapshot()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if format == "json":
            meta = {"campaign": settings.campaign.name, "state": snap["state"], "total": snap["total"],
                    "counts": snap["counts"], "exported_at": stamp}
            body, media, ext = to_json(snap["results"], meta), "application/json", "json"
        elif format == "csv":
            body, media, ext = to_csv(snap["results"]), "text/csv; charset=utf-8", "csv"
        else:
            raise HTTPException(status_code=400, detail="Format must be csv or json.")
        return Response(body, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="lwc-progress-{stamp}.{ext}"'})

    return app
