"""Input validation and output encoding helpers.

The central rule: the tracker never requests a URL that a user typed. It extracts a profile
UUID from the input, checks it against a strict pattern, and builds the request URL itself.
That removes server-side request forgery (SSRF) as a class of bug.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({
    "www.skills.google",
    "skills.google",
    "www.cloudskillsboost.google",
    "cloudskillsboost.google",
})
CANONICAL_PROFILE_URL = "https://www.skills.google/public_profiles/{}"

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PATH_RE = re.compile(r"^/public_profiles/([0-9A-Fa-f-]{36})/?$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "|", "%")
MAX_URL_LENGTH = 300


class InvalidProfileURL(ValueError):
    """The input is not a Google Skills public profile link."""


def parse_profile_url(raw: object) -> str:
    """Return the lower-case profile UUID from a public profile URL, or raise InvalidProfileURL."""
    if not isinstance(raw, str):
        raise InvalidProfileURL("Profile link is missing")
    value = raw.strip()
    if not value:
        raise InvalidProfileURL("Profile link is empty")
    if len(value) > MAX_URL_LENGTH:
        raise InvalidProfileURL("Profile link is too long")
    if _CONTROL_RE.search(value) or " " in value or "\\" in value:
        raise InvalidProfileURL("Profile link contains spaces or hidden characters")
    if "://" not in value:
        value = "https://" + value

    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise InvalidProfileURL("Profile link is not a valid URL") from exc

    if parts.scheme.lower() not in ("https", "http"):
        raise InvalidProfileURL("Profile link must use https")
    if parts.username is not None or parts.password is not None:
        raise InvalidProfileURL("Profile link must not contain credentials")
    if port not in (None, 80, 443):
        raise InvalidProfileURL("Profile link uses an unexpected port")
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_HOSTS:
        raise InvalidProfileURL("Profile link is not on skills.google")

    match = _PATH_RE.match(parts.path)
    if not match:
        raise InvalidProfileURL("Link is not a public profile (expected /public_profiles/<id>)")
    profile_id = match.group(1).lower()
    if not _UUID_RE.match(profile_id):
        raise InvalidProfileURL("Profile ID is malformed")
    return profile_id


def canonical_profile_url(profile_id: str) -> str:
    """Build the only URL shape the fetcher is allowed to request."""
    if not isinstance(profile_id, str) or not _UUID_RE.match(profile_id):
        raise InvalidProfileURL("Refusing to build a URL from an unvalidated profile ID")
    return CANONICAL_PROFILE_URL.format(profile_id)


def clean_text(value: object, max_len: int = 200) -> str:
    """Normalise untrusted text: Unicode NFKC, no control or bidi-override characters, bounded length."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = _CONTROL_RE.sub(" ", text)
    text = " ".join(text.split())
    return text[:max_len]


def safe_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection (CSV injection) in exported cells."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def mask_email(email: str) -> str:
    """Mask an e-mail address for logs: a***@example.com."""
    if not email or "@" not in email:
        return "-"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def short_id(profile_id: str | None) -> str:
    return f"{profile_id[:8]}…" if profile_id else "-"
