"""Extract badges from a public profile page. Pure parsing: no scripts run, no links followed."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup

from .security import clean_text

_EARNED_RE = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})")
_POINTS_RE = re.compile(r"([\d,]+)\s*points", re.I)
MAX_BADGES = 1000


class ProfileParseError(Exception):
    """The page did not look like a public profile (layout change or interstitial)."""


@dataclass(frozen=True)
class Badge:
    title: str
    earned: date | None
    earned_raw: str

    def to_dict(self) -> dict:
        return {"title": self.title, "earned": self.earned.isoformat() if self.earned else None}


@dataclass(frozen=True)
class ProfileData:
    display_name: str
    badges: tuple[Badge, ...]
    league: str | None = None
    points: int | None = None


def parse_earned(text: str) -> date | None:
    m = _EARNED_RE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {int(m.group(2))} {m.group(3)}", "%b %d %Y").date()
    except ValueError:
        return None


def parse_profile(html: str) -> ProfileData:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup
    heading = main.find("h1")
    badge_cards = main.select("div.profile-badge")
    if heading is None and not badge_cards:
        raise ProfileParseError("The page has no profile heading or badge list")

    display_name = clean_text(heading.get_text(" ") if heading else "", 120)

    badges: list[Badge] = []
    for card in badge_cards[:MAX_BADGES]:
        title_el = card.select_one(".ql-title-medium")
        title = clean_text(title_el.get_text(" ") if title_el else "", 200)
        if not title:
            # Fallback: the button's accessible label repeats the badge title.
            btn = card.find(attrs={"arialabel": True}) or card.find(attrs={"aria-label": True})
            label = (btn.get("arialabel") or btn.get("aria-label") or "") if btn else ""
            title = clean_text(re.sub(r"^Learn more about\s+", "", label), 200)
        if not title:
            continue
        earned_el = card.select_one(".ql-body-medium")
        earned_raw = clean_text(earned_el.get_text(" ") if earned_el else "", 60)
        badges.append(Badge(title=title, earned=parse_earned(earned_raw), earned_raw=earned_raw))

    league_el = main.select_one(".profile-league h2")
    points_el = main.select_one(".profile-league strong")
    points = None
    if points_el:
        m = _POINTS_RE.search(points_el.get_text(" "))
        if m:
            points = int(m.group(1).replace(",", ""))

    return ProfileData(
        display_name=display_name,
        badges=tuple(badges),
        league=clean_text(league_el.get_text(" "), 40) if league_el else None,
        points=points,
    )
