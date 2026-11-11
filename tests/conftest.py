import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lwc_tracker.config import load_settings  # noqa: E402
from lwc_tracker.fetcher import RawResponse  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
GOOD_ID = "be556f7b-ab4b-4be7-82fb-9be45202ddd7"


@pytest.fixture
def settings():
    s = load_settings(ROOT / "campaign.toml")
    fast_http = replace(s.http, requests_per_second=200.0, burst=20, backoff_base=0.01, backoff_cap=0.05,
                        max_retries=3, cache_ttl_seconds=0)
    return replace(s, http=fast_http)


@pytest.fixture
def profile_html():
    return (FIXTURES / "profile.html").read_text(encoding="utf-8")


class ScriptedTransport:
    """Returns queued responses per URL; falls back to `default`."""

    def __init__(self, default=None):
        self.queues: dict[str, list] = {}
        self.default = default
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def queue(self, profile_id: str, *responses):
        self.queues.setdefault(profile_id, []).extend(responses)

    def __call__(self, url: str):
        pid = url.rsplit("/", 1)[-1]
        with self.lock:
            self.calls.append(pid)
            q = self.queues.get(pid)
            item = q.pop(0) if q else self.default
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item()
        return item


def html_response(body: str) -> RawResponse:
    return RawResponse(200, {"Content-Type": "text/html; charset=utf-8"}, body.encode())


@pytest.fixture
def transport(profile_html):
    return ScriptedTransport(default=html_response(profile_html))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server():
    """Start an app on a free port in a background thread; yields a function(app) -> base URL."""
    import uvicorn

    servers = []

    def start(app):
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        servers.append(server)
        return f"http://127.0.0.1:{port}"

    yield start
    for s in servers:
        s.should_exit = True
