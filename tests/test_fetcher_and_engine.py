import threading
import time
from dataclasses import replace

import requests

from conftest import GOOD_ID, ScriptedTransport, html_response
from lwc_tracker.engine import Status, Verifier
from lwc_tracker.fetcher import ProfileFetcher, RawResponse, ResponseTooLarge, TokenBucket, parse_retry_after
from lwc_tracker.roster import load_roster

OTHER_ID = "11111111-2222-4333-8444-555555555555"


def fetch(settings, transport, pid=GOOD_ID):
    return ProfileFetcher(settings.http, transport=transport).fetch(pid, threading.Event())


def test_success(settings, transport):
    r = fetch(settings, transport)
    assert r.ok and r.attempts == 1


def test_redirect_means_not_found_and_is_not_retried(settings):
    t = ScriptedTransport(default=RawResponse(302, {"Location": "https://www.skills.google/"}, b""))
    r = fetch(settings, t)
    assert r.error_kind == "not_found" and r.attempts == 1


def test_transient_errors_are_retried_then_succeed(settings, profile_html):
    t = ScriptedTransport()
    t.queue(GOOD_ID, RawResponse(503, {}, b""), requests.Timeout(), html_response(profile_html))
    r = fetch(settings, t)
    assert r.ok and r.attempts == 3


def test_retries_are_bounded(settings):
    t = ScriptedTransport(default=requests.ConnectionError())
    r = fetch(settings, t)
    assert not r.ok and r.error_kind == "network"
    assert r.attempts == settings.http.max_retries + 1


def test_429_honours_retry_after_and_pauses_everyone(settings, profile_html):
    t = ScriptedTransport()
    t.queue(GOOD_ID, RawResponse(429, {"retry-after": "0.3"}, b""), html_response(profile_html))
    f = ProfileFetcher(replace(settings.http, backoff_cap=1.0), transport=t)  # Retry-After is capped at 2x this
    start = time.monotonic()
    r = f.fetch(GOOD_ID, threading.Event())
    assert r.ok and r.attempts == 2
    assert time.monotonic() - start >= 0.25
    assert f.stats["rate_limited"] == 1


def test_403_is_not_retried(settings):
    t = ScriptedTransport(default=RawResponse(403, {}, b""))
    r = fetch(settings, t)
    assert r.error_kind == "blocked" and r.attempts == 1


def test_oversized_and_non_html_responses_are_refused(settings):
    def too_big():
        raise ResponseTooLarge()

    assert fetch(settings, ScriptedTransport(default=too_big)).error_kind == "too_large"
    json_resp = RawResponse(200, {"Content-Type": "application/json"}, b"{}")
    assert fetch(settings, ScriptedTransport(default=json_resp)).error_kind == "http"


def test_circuit_breaker_stops_a_failing_run(settings):
    t = ScriptedTransport(default=RawResponse(500, {}, b""))
    f = ProfileFetcher(settings.http, transport=t)
    cancel = threading.Event()
    results = [f.fetch(GOOD_ID, cancel) for _ in range(4)]
    assert results[-1].error_kind == "circuit_open"
    assert len(t.calls) <= settings.http.circuit_breaker_threshold


def test_cancel_stops_waiting():
    bucket = TokenBucket(rate=0.01, burst=1)
    cancel = threading.Event()
    assert bucket.acquire(cancel)
    cancel.set()
    assert bucket.acquire(cancel) is False


def test_token_bucket_paces_requests():
    bucket = TokenBucket(rate=20, burst=1)
    cancel = threading.Event()
    start = time.monotonic()
    for _ in range(5):
        bucket.acquire(cancel)
    assert time.monotonic() - start >= 0.18


def test_parse_retry_after():
    assert parse_retry_after("5", 60) == 5
    assert parse_retry_after("9999", 60) == 60
    assert parse_retry_after("soon", 60) is None
    assert parse_retry_after(None, 60) is None


def test_engine_end_to_end_with_shared_profiles_and_bad_rows(settings, profile_html):
    csv_text = (
        "Name,Email,Profile\n"
        f"Test Learner,t@example.com,https://www.skills.google/public_profiles/{GOOD_ID}\n"
        f"Someone Else,s@example.com,https://www.cloudskillsboost.google/public_profiles/{GOOD_ID}\n"
        f"Gone,g@example.com,https://www.skills.google/public_profiles/{OTHER_ID}\n"
        "Bad,b@example.com,https://example.com/x\n"
    )
    roster = load_roster(csv_text.encode(), 100_000, 100)
    t = ScriptedTransport(default=html_response(profile_html))
    t.queue(OTHER_ID, RawResponse(302, {}, b""))
    v = Verifier(settings, fetcher=ProfileFetcher(settings.http, transport=t))
    out = []
    v.run(roster, out.append, threading.Event())
    by_row = {r.row: r for r in out}
    assert len(out) == 4
    assert t.calls.count(GOOD_ID) == 1  # shared profile fetched once
    assert by_row[2].status == Status.IN_PROGRESS and by_row[2].badge_count == 3
    assert "shared_profile" in by_row[2].flags and "shared_profile" in by_row[3].flags
    assert "name_mismatch" in by_row[3].flags and "name_mismatch" not in by_row[2].flags
    assert by_row[4].status == Status.NOT_FOUND
    assert by_row[5].status == Status.INVALID_URL


def test_engine_survives_a_hostile_page(settings):
    t = ScriptedTransport(default=html_response("<main><h1>x</h1>" + "<div class='profile-badge'>" * 5000 + "</main>"))
    roster = load_roster(f"Profile\nhttps://www.skills.google/public_profiles/{GOOD_ID}\n".encode(), 10_000, 10)
    out = []
    Verifier(settings, fetcher=ProfileFetcher(settings.http, transport=t)).run(roster, out.append, threading.Event())
    assert len(out) == 1 and out[0].status in (Status.NOT_STARTED, Status.PARSE_ERROR)
