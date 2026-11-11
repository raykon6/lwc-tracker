import time

import requests

from conftest import GOOD_ID
from lwc_tracker.engine import Verifier
from lwc_tracker.fetcher import ProfileFetcher
from lwc_tracker.web.app import create_app

H = {"X-Verity-Request": "1"}
CSV = (f"Name,Email,Profile\n=HYPERLINK(\"http://x\"),a@x.edu,https://www.skills.google/public_profiles/{GOOD_ID}\n"
       "Bad,b@x.edu,https://evil.example/x\n").encode()


def make(settings, transport, live_server, **kw):
    v = Verifier(settings, fetcher=ProfileFetcher(settings.http, transport=transport))
    return live_server(create_app(settings, verifier=v, **kw))


def upload(base, data=CSV, name="r.csv", headers=H):
    return requests.post(f"{base}/api/roster", files={"file": (name, data, "text/csv")}, headers=headers, timeout=5)


def test_security_headers_on_pages_and_api(settings, transport, live_server):
    base = make(settings, transport, live_server)
    for path in ("/", "/api/config"):
        r = requests.get(base + path, timeout=5)
        assert r.status_code == 200
        assert "script-src 'self'" in r.headers["Content-Security-Policy"]
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert requests.get(base + "/api/config", timeout=5).headers["Cache-Control"] == "no-store"
    assert requests.get(base + "/docs", timeout=5).status_code == 404


def test_csrf_and_host_protections(settings, transport, live_server):
    base = make(settings, transport, live_server)
    assert upload(base, headers={}).status_code == 403
    assert upload(base, headers={**H, "Origin": "https://evil.example"}).status_code == 403
    r = requests.get(base + "/api/config", headers={"Host": "attacker.example"}, timeout=5)
    assert r.status_code == 400
    r = requests.get(base + "/", headers={"Host": "attacker.example:8000"}, timeout=5)
    assert r.status_code == 400
    # The platform health check is the only route that ignores the Host header.
    assert requests.get(base + "/healthz", headers={"Host": "10.0.0.7:10000"}, timeout=5).json() == {"ok": True}


def test_upload_validation(settings, transport, live_server):
    base = make(settings, transport, live_server)
    assert upload(base, name="r.exe").status_code == 415
    assert upload(base, data=b"x" * (settings.limits.max_upload_bytes + 100_000)).status_code == 413
    r = upload(base, data=b"name\nno links here\n")
    assert r.status_code == 400 and "No column" in r.json()["detail"]


def test_access_token(settings, transport, live_server):
    base = make(settings, transport, live_server, access_token="s3cret-token-value")
    assert requests.get(base + "/api/config", timeout=5).status_code == 401
    assert requests.get(base + "/healthz", timeout=5).status_code == 200
    ok = requests.get(base + "/api/config", headers={"Authorization": "Bearer s3cret-token-value"}, timeout=5)
    assert ok.status_code == 200 and ok.json()["auth_required"] is True


def test_inbound_rate_limit(settings, transport, live_server):
    base = make(settings, transport, live_server)
    codes = [upload(base).status_code for _ in range(22)]
    assert codes[0] == 200 and 429 in codes


def test_full_run_and_safe_export(settings, transport, live_server):
    base = make(settings, transport, live_server)
    rid = upload(base).json()["roster_id"]
    job = requests.post(f"{base}/api/jobs", json={"roster_id": rid}, headers=H, timeout=5).json()
    for _ in range(100):
        snap = requests.get(f"{base}/api/jobs/{job['job_id']}", timeout=5).json()
        if snap["state"] == "done":
            break
        time.sleep(0.05)
    assert snap["done"] == 2
    statuses = sorted(r["status"] for r in snap["results"])
    assert statuses == ["in_progress", "invalid_url"]

    csv_text = requests.get(f"{base}/api/jobs/{job['job_id']}/export?format=csv", timeout=5).text
    assert "'=HYPERLINK" in csv_text  # formula neutralised
    assert requests.get(f"{base}/api/jobs/{job['job_id']}/export?format=xml", timeout=5).status_code == 400
    assert requests.get(f"{base}/api/jobs/not-a-valid-id/export", timeout=5).status_code == 404

    again = requests.post(f"{base}/api/jobs", json={"roster_id": rid, "retry_of": job["job_id"]}, headers=H, timeout=5)
    assert again.status_code == 409  # nothing left to retry
