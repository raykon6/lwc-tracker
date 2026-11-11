"""Offline demo upstream: synthetic profiles so the app can be shown without network access.

It also injects a few 429 and 503 responses so the retry and backoff paths are visible.
Enabled only with `serve --demo`; the UI shows a banner while it is on.
"""
from __future__ import annotations

import hashlib
import html
import random
import threading
import time
import uuid
from datetime import date, timedelta

from .config import Settings
from .fetcher import RawResponse

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vihaan", "Isha", "Arjun", "Saanvi",
         "Reyansh", "Tara", "Kiran", "Nisha", "Dev", "Pooja", "Aditya", "Riya", "Farhan", "Zoya"]
LAST = ["Sharma", "Iyer", "Khan", "Reddy", "Patel", "Singh", "Das", "Menon", "Joshi", "Nair"]


def demo_name(i: int) -> str:
    return f"{FIRST[i % len(FIRST)]} {LAST[(i * 7 + i // len(FIRST)) % len(LAST)]}"


def demo_roster_csv(n: int = 48) -> str:
    rows = ["Name,Email,Profile URL"]
    for i in range(n):
        pid = uuid.UUID(bytes=hashlib.sha256(f"verity-demo-{i}".encode()).digest()[:16], version=4)
        name = demo_name(i)
        email = name.lower().replace(" ", ".") + "@example.edu"
        url = f"https://www.skills.google/public_profiles/{pid}"
        if i == 7:
            url = "https://www.skills.google/public_profile/typo"
        if i == 19:
            url = "https://example.com/public_profiles/" + str(pid)
        if i == 23:  # same profile submitted twice
            prev = uuid.UUID(bytes=hashlib.sha256(b"verity-demo-3").digest()[:16], version=4)
            url = f"https://www.skills.google/public_profiles/{prev}"
        rows.append(f"{name},{email},{url}")
    return "\n".join(rows) + "\n"


class DemoTransport:
    def __init__(self, settings: Settings):
        self.badges = list(settings.campaign.required_badges) or [f"Skill Badge {i + 1}" for i in range(10)]
        self.seen: set[str] = set()
        self.lock = threading.Lock()
        self.names = {}
        for i in range(200):
            pid = str(uuid.UUID(bytes=hashlib.sha256(f"verity-demo-{i}".encode()).digest()[:16], version=4))
            self.names[pid] = demo_name(i)

    def __call__(self, url: str) -> RawResponse:
        pid = url.rstrip("/").rsplit("/", 1)[-1]
        rnd = random.Random(pid)
        time.sleep(rnd.uniform(0.08, 0.35))
        with self.lock:
            first = pid not in self.seen
            self.seen.add(pid)
        roll = rnd.random()
        if roll < 0.06:
            return RawResponse(302, {"Location": "https://www.skills.google/"}, b"")
        if first and roll < 0.10:
            return RawResponse(503, {}, b"unavailable")
        if first and roll < 0.13:
            return RawResponse(429, {"Retry-After": "2"}, b"slow down")

        weights = [0.10, 0.04, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.09, 0.28]
        k = rnd.choices(range(len(weights)), weights=weights)[0]
        k = min(k, len(self.badges))
        chosen = rnd.sample(self.badges, k)
        name = self.names.get(pid, "Demo Learner")
        start = date(2026, 10, 6)
        cards = []
        for i, title in enumerate(chosen):
            d = start + timedelta(days=rnd.randint(0, 35))
            cards.append(
                "<div class='profile-badge'><a class='badge-image' href='#'></a>"
                f"<span class='ql-title-medium l-mts'>{html.escape(title)}</span>"
                f"<span class='ql-body-medium l-mbs'>Earned {d.strftime('%b')} {d.day:2d}, {d.year} EST</span>"
                f"<ql-button ariaLabel='Learn more about {html.escape(title)}'></ql-button></div>"
            )
        if rnd.random() < 0.15:
            cards.append("<div class='profile-badge'><span class='ql-title-medium'>Level 1: Core Infrastructure</span>"
                         "<span class='ql-body-medium'>Earned Sep 30, 2026 EST</span></div>")
        page = (f"<html><body><main><h1 class='ql-display-small'>{html.escape(name)}</h1>"
                f"<div class='profile-badges'>{''.join(cards)}</div></main></body></html>")
        return RawResponse(200, {"Content-Type": "text/html; charset=utf-8"}, page.encode())
