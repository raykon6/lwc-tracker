"""Parse the participant CSV defensively. No network access happens here."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from .security import InvalidProfileURL, clean_text, parse_profile_url

csv.field_size_limit(64 * 1024)

_NAME_KEYS = ("name", "fullname", "studentname", "participantname", "candidatename")
_EMAIL_KEYS = ("email", "emailaddress", "mail", "emailid")
_URL_HINTS = ("profile", "url", "link", "skills", "boost")


class RosterError(ValueError):
    """The uploaded file cannot be used as a roster."""


@dataclass
class RosterRow:
    row: int
    name: str
    email: str
    raw_url: str
    profile_id: str | None
    error: str | None = None
    duplicate_of: int | None = None

    def to_dict(self) -> dict:
        return {
            "row": self.row,
            "name": self.name,
            "email": self.email,
            "raw_url": self.raw_url,
            "profile_id": self.profile_id,
            "error": self.error,
            "duplicate_of": self.duplicate_of,
        }


@dataclass
class Roster:
    rows: list[RosterRow]
    columns: dict[str, str | None]
    warnings: list[str] = field(default_factory=list)

    @property
    def valid_rows(self) -> list[RosterRow]:
        return [r for r in self.rows if r.profile_id]

    def summary(self) -> dict:
        return {
            "total": len(self.rows),
            "valid": len(self.valid_rows),
            "invalid": sum(1 for r in self.rows if r.error),
            "duplicates": sum(1 for r in self.rows if r.duplicate_of is not None),
            "unique_profiles": len({r.profile_id for r in self.rows if r.profile_id}),
            "columns": self.columns,
            "warnings": self.warnings,
        }


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def _decode(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise RosterError("The file looks binary. Upload a plain CSV export (UTF-8).")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise RosterError("The file is not valid UTF-8 text.")


def _looks_like_profile(cell: str) -> bool:
    return "public_profiles/" in cell.lower()


def _pick_column(headers: list[str], rows: list[list[str]]) -> dict[str, int | None]:
    normed = [_norm_header(h) for h in headers]

    # URL column: the one whose values most often look like profile links.
    scores = []
    for i in range(len(headers)):
        hits = sum(1 for r in rows[:200] if i < len(r) and _looks_like_profile(r[i]))
        scores.append(hits)
    url_idx: int | None = max(range(len(headers)), key=lambda i: scores[i]) if headers else None
    if url_idx is not None and scores[url_idx] == 0:
        url_idx = next((i for i, h in enumerate(normed) if any(k in h for k in _URL_HINTS)), None)

    email_idx = next((i for i, h in enumerate(normed) if h in _EMAIL_KEYS), None)
    if email_idx is None:
        email_idx = next((i for i, h in enumerate(normed) if "email" in h or "mail" in h), None)

    name_idx = next((i for i, h in enumerate(normed) if h in _NAME_KEYS), None)
    if name_idx is None:
        name_idx = next(
            (i for i, h in enumerate(normed) if "name" in h and i not in (email_idx, url_idx) and "user" not in h),
            None,
        )
    return {"url": url_idx, "name": name_idx, "email": email_idx}


def load_roster(data: bytes, max_bytes: int, max_rows: int) -> Roster:
    if not data or not data.strip():
        raise RosterError("The file is empty.")
    if len(data) > max_bytes:
        raise RosterError(f"The file is larger than {max_bytes // 1024} KB.")

    text = _decode(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    try:
        all_rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    except csv.Error as exc:
        raise RosterError(f"The CSV could not be parsed: {exc}") from exc
    if not all_rows:
        raise RosterError("The file has no rows.")

    warnings: list[str] = []
    first = all_rows[0]
    has_header = not any(_looks_like_profile(c) for c in first)
    if has_header:
        headers = [clean_text(h, 60) or f"Column {i + 1}" for i, h in enumerate(first)]
        body = all_rows[1:]
    else:
        headers = [f"Column {i + 1}" for i in range(len(first))]
        body = all_rows
        warnings.append("No header row found. Columns were detected from their values.")

    if len(body) > max_rows:
        raise RosterError(f"The file has {len(body)} rows. The limit is {max_rows}.")
    if not body:
        raise RosterError("The file has a header but no participant rows.")

    idx = _pick_column(headers, body)
    if idx["url"] is None:
        raise RosterError("No column with Google Skills public profile links was found.")
    if idx["name"] is None:
        warnings.append("No name column was found. Rows are identified by their line number.")

    def cell(r: list[str], key: str, max_len: int) -> str:
        i = idx[key]
        return clean_text(r[i], max_len) if i is not None and i < len(r) else ""

    rows: list[RosterRow] = []
    seen: dict[str, int] = {}
    start_line = 2 if has_header else 1
    for n, r in enumerate(body):
        line = start_line + n
        raw_url = cell(r, "url", 300)
        rr = RosterRow(row=line, name=cell(r, "name", 120), email=cell(r, "email", 160).lower(), raw_url=raw_url, profile_id=None)
        try:
            # Validate the untouched cell so hidden characters are caught, not silently stripped.
            raw_cell = r[idx["url"]] if idx["url"] < len(r) else ""
            rr.profile_id = parse_profile_url(raw_cell)
        except InvalidProfileURL as exc:
            rr.error = str(exc)
        if rr.profile_id:
            if rr.profile_id in seen:
                rr.duplicate_of = seen[rr.profile_id]
            else:
                seen[rr.profile_id] = line
        rows.append(rr)

    columns = {k: (headers[v] if v is not None else None) for k, v in idx.items()}
    return Roster(rows=rows, columns=columns, warnings=warnings)


def roster_from_lines(text: str, max_bytes: int, max_rows: int) -> Roster:
    """Build a roster from pasted text: one profile link per line, optionally 'name, link'."""
    data = text.encode("utf-8")
    if len(data) > max_bytes:
        raise RosterError(f"The pasted text is larger than {max_bytes // 1024} KB.")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise RosterError("Paste at least one profile link.")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Profile URL"])
    for ln in lines:
        parts = [p.strip() for p in re.split(r"[,\t;]", ln) if p.strip()]
        url = next((p for p in parts if _looks_like_profile(p)), parts[-1] if parts else "")
        name = next((p for p in parts if p != url), "")
        w.writerow([name, url])
    return load_roster(out.getvalue().encode("utf-8"), max_bytes * 2, max_rows)
