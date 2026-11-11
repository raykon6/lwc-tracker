"""Match a profile's badges against the campaign rules."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .config import CampaignSettings
from .parser import Badge, ProfileData


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title).lower()
    t = re.sub(r"[‐-―]", "-", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


@dataclass
class Evaluation:
    counted: int
    matched: list[Badge]
    missing: list[str]
    extra: list[Badge]
    outside_window: list[Badge]


class CampaignRules:
    def __init__(self, settings: CampaignSettings):
        self.settings = settings
        self.required = list(settings.required_badges)
        self._lookup = {normalize_title(t): t for t in self.required}
        for alias, target in settings.aliases.items():
            key = normalize_title(target)
            if key in self._lookup:
                self._lookup[normalize_title(alias)] = self._lookup[key]

    @property
    def required_count(self) -> int:
        return self.settings.required_count

    def _in_window(self, badge: Badge) -> bool:
        s, e = self.settings.start_date, self.settings.end_date
        if badge.earned is None:
            return True
        if s and badge.earned < s:
            return False
        if e and badge.earned > e:
            return False
        return True

    def evaluate(self, profile: ProfileData) -> Evaluation:
        matched: dict[str, Badge] = {}
        extra: list[Badge] = []
        outside: list[Badge] = []
        for badge in profile.badges:
            if not self._in_window(badge):
                outside.append(badge)
                continue
            if not self.required:
                matched.setdefault(normalize_title(badge.title), badge)
                continue
            canonical = self._lookup.get(normalize_title(badge.title))
            if canonical:
                matched.setdefault(canonical, badge)
            else:
                extra.append(badge)

        if self.required:
            missing = [t for t in self.required if t not in matched]
        else:
            missing = []
        return Evaluation(
            counted=len(matched),
            matched=list(matched.values()),
            missing=missing,
            extra=extra,
            outside_window=outside,
        )
