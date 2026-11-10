"""Export/import match history (JSON round-trips; CSV is for spreadsheets)."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from ..core.models import ManualOutcome, MatchResult, Role, SurvivorOutcome, Verdict
from .db import Database

FIELDS = ("ts", "role", "killer", "realm", "map", "survivors", "my_index", "hatch_used",
          "manual_outcome", "source", "ignored", "verdict", "counted", "notes")


def _row(m: MatchResult) -> dict:
    return {
        "ts": m.ts.isoformat(), "role": m.role.value, "killer": m.killer, "realm": m.realm, "map": m.map,
        "survivors": [s.value for s in m.survivors], "my_index": m.my_index, "hatch_used": m.hatch_used,
        "manual_outcome": m.manual_outcome.value if m.manual_outcome else None, "source": m.source,
        "ignored": m.ignored, "verdict": m.verdict.value, "counted": m.counted, "notes": m.notes,
    }


def export(db: Database, path: Path) -> int:
    rows = [_row(m) for m in db.matches()]
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({**r, "survivors": " ".join(r["survivors"])})
    else:
        path.write_text(json.dumps(rows, indent=2) + "\n")
    return len(rows)


def import_json(db: Database, path: Path) -> tuple[int, int]:
    """Add matches from an export. Skips ones already present (same time + role). Returns (added, skipped)."""
    existing = {(m.ts.isoformat(), m.role.value) for m in db.matches()}
    added = skipped = 0
    for r in json.loads(path.read_text()):
        if (r["ts"], r["role"]) in existing:
            skipped += 1
            continue
        db.add_match(MatchResult(
            role=Role(r["role"]), killer=r.get("killer"), realm=r.get("realm"), map=r.get("map"),
            survivors=tuple(SurvivorOutcome(s) for s in r.get("survivors", [])), my_index=r.get("my_index"),
            hatch_used=r.get("hatch_used"),
            manual_outcome=ManualOutcome(r["manual_outcome"]) if r.get("manual_outcome") else None,
            source=r.get("source", "manual"), ignored=bool(r.get("ignored")),
            verdict=Verdict(r.get("verdict", "unknown")), counted=bool(r.get("counted", True)),
            notes=r.get("notes", ""),
            ts=datetime.fromisoformat(r["ts"]),
        ))
        added += 1
    return added, skipped
