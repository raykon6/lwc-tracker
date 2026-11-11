"""CSV / JSON export with spreadsheet formula-injection protection."""
from __future__ import annotations

import csv
import io
import json
from typing import Iterable

from .security import safe_cell

COLUMNS = [
    ("row", "Row"),
    ("name", "Name"),
    ("email", "Email"),
    ("display_name", "Profile name"),
    ("profile_url", "Profile URL"),
    ("status", "Status"),
    ("badge_count", "Qualifying badges"),
    ("required", "Required"),
    ("total_badges", "All badges on profile"),
    ("last_earned", "Last earned"),
    ("missing", "Missing badges"),
    ("flags", "Flags"),
    ("error", "Error"),
    ("checked_at", "Checked at (UTC)"),
]


def to_csv(results: Iterable[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([label for _, label in COLUMNS])
    for r in sorted(results, key=lambda x: x.get("row", 0)):
        values = []
        for key, _ in COLUMNS:
            v = r.get(key)
            if isinstance(v, list):
                v = "; ".join(str(x) for x in v)
            values.append(safe_cell("" if v is None else v))
        writer.writerow(values)
    return "﻿" + out.getvalue()  # BOM so Excel opens UTF-8 names correctly


def to_json(results: Iterable[dict], meta: dict) -> str:
    return json.dumps({"meta": meta, "results": sorted(results, key=lambda x: x.get("row", 0))},
                      ensure_ascii=False, indent=2)
