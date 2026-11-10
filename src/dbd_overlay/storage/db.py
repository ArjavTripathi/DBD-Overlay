"""SQLite storage with versioned migrations.

Schema version lives in SQLite's built-in `PRAGMA user_version` (an integer in
the file header), so no extra bookkeeping table is needed. To change the
schema, APPEND a new script to MIGRATIONS; never edit an old one, because
existing databases have already run it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from ..core.models import ManualOutcome, MatchResult, Role, SurvivorOutcome, Verdict

log = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE matches (
        id             INTEGER PRIMARY KEY,
        ts             TEXT    NOT NULL,              -- ISO-8601 UTC
        role           TEXT    NOT NULL CHECK (role IN ('survivor', 'killer')),
        killer         TEXT,
        realm          TEXT,
        map            TEXT,
        survivors      TEXT    NOT NULL DEFAULT '[]', -- JSON list of SurvivorOutcome
        my_index       INTEGER,
        hatch_used     INTEGER,                       -- NULL = unknown
        manual_outcome TEXT    CHECK (manual_outcome IN ('win', 'loss')),
        source         TEXT    NOT NULL CHECK (source IN ('auto', 'manual')),
        ignored        INTEGER NOT NULL DEFAULT 0,
        notes          TEXT    NOT NULL DEFAULT '',
        category       TEXT    NOT NULL               -- 'survivor' | 'killer:<name>'
    );
    CREATE INDEX matches_category_ts ON matches (category, ts);

    -- Manual "reset this streak": attempts count from the latest reset.
    CREATE TABLE streak_resets (
        id       INTEGER PRIMARY KEY,
        ts       TEXT NOT NULL,
        category TEXT NOT NULL
    );
    """,
    # v2: cache each match's verdict under the rules active when recorded.
    """
    ALTER TABLE matches ADD COLUMN verdict TEXT NOT NULL DEFAULT 'unknown'
        CHECK (verdict IN ('win', 'loss', 'unknown'));
    """,
    # v3: streaks can be switched on/off; each match remembers whether its
    # streak was on when it was played. Streaks that already have matches
    # start ON (they were being tracked); new ones default to OFF.
    """
    ALTER TABLE matches ADD COLUMN counted INTEGER NOT NULL DEFAULT 1;
    CREATE TABLE streaks (
        category TEXT PRIMARY KEY,
        active   INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO streaks (category, active) SELECT DISTINCT category, 1 FROM matches;
    """,
]


class Database:
    def __init__(self, path: Path | str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.migrate()

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        current = self.version
        if current > len(MIGRATIONS):
            raise RuntimeError(f"database is v{current}, this app only knows v{len(MIGRATIONS)}; upgrade the app")
        for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
            log.info("migrating database to v%d", version)
            try:
                # executescript() runs outside Python's implicit transactions, so
                # wrap it ourselves: a failed migration must leave nothing behind.
                self.conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
            except sqlite3.Error:
                self.conn.rollback()
                raise

    def close(self) -> None:
        self.conn.close()

    # -- matches -----------------------------------------------------------

    def add_match(self, m: MatchResult) -> int:
        with self.conn:  # commits on success, rolls back on exception
            cur = self.conn.execute(
                """INSERT INTO matches (ts, role, killer, realm, map, survivors, my_index,
                       hatch_used, manual_outcome, source, ignored, notes, category, verdict, counted)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    m.ts.isoformat(), m.role.value, m.killer, m.realm, m.map,
                    json.dumps([s.value for s in m.survivors]), m.my_index,
                    None if m.hatch_used is None else int(m.hatch_used),
                    m.manual_outcome.value if m.manual_outcome else None,
                    m.source, int(m.ignored), m.notes, m.category, m.verdict.value, int(m.counted),
                ),
            )
        m.id = cur.lastrowid
        return m.id  # type: ignore[return-value]

    def get_match(self, match_id: int) -> MatchResult | None:
        row = self.conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return _row_to_match(row) if row else None

    def matches(self, category: str | None = None, since: datetime | None = None) -> list[MatchResult]:
        """Matches in chronological order (ignored ones included; callers decide)."""
        sql, args = "SELECT * FROM matches WHERE 1=1", []
        if category is not None:
            sql += " AND category = ?"
            args.append(category)
        if since is not None:
            sql += " AND ts > ?"
            args.append(since.isoformat())
        rows = self.conn.execute(sql + " ORDER BY ts, id", args).fetchall()
        return [_row_to_match(r) for r in rows]

    def last_match(self) -> MatchResult | None:
        row = self.conn.execute("SELECT * FROM matches ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        return _row_to_match(row) if row else None

    def set_ignored(self, match_id: int, ignored: bool = True) -> None:
        with self.conn:
            self.conn.execute("UPDATE matches SET ignored = ? WHERE id = ?", (int(ignored), match_id))

    def set_counted(self, match_id: int, counted: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE matches SET counted = ? WHERE id = ?", (int(counted), match_id))

    # -- streak on/off ------------------------------------------------------

    def streak_active(self, category: str) -> bool:
        row = self.conn.execute("SELECT active FROM streaks WHERE category = ?", (category,)).fetchone()
        return bool(row["active"]) if row else False  # never switched on = off

    def set_streak_active(self, category: str, active: bool) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO streaks (category, active) VALUES (?, ?) "
                "ON CONFLICT (category) DO UPDATE SET active = excluded.active",
                (category, int(active)),
            )

    def streak_states(self) -> dict[str, bool]:
        """Every known streak (switched on/off before, or with matches) -> on?"""
        states = {r["category"]: False for r in self.conn.execute("SELECT DISTINCT category FROM matches")}
        states.update({r["category"]: bool(r["active"]) for r in self.conn.execute("SELECT * FROM streaks")})
        return states

    def set_verdict(self, match_id: int, verdict: Verdict, manual: ManualOutcome | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE matches SET verdict = ?, manual_outcome = ? WHERE id = ?",
                (verdict.value, manual.value if manual else None, match_id),
            )

    def delete_match(self, match_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))

    # -- resets ------------------------------------------------------------

    def add_reset(self, category: str, ts: datetime) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO streak_resets (ts, category) VALUES (?, ?)", (ts.isoformat(), category))

    def delete_last_reset(self, category: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM streak_resets WHERE id = (SELECT id FROM streak_resets WHERE category = ? "
                "ORDER BY ts DESC, id DESC LIMIT 1)", (category,))

    def last_reset(self, category: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT ts FROM streak_resets WHERE category = ? ORDER BY ts DESC LIMIT 1", (category,)
        ).fetchone()
        return datetime.fromisoformat(row["ts"]) if row else None


def _row_to_match(r: sqlite3.Row) -> MatchResult:
    return MatchResult(
        id=r["id"],
        ts=datetime.fromisoformat(r["ts"]),
        role=Role(r["role"]),
        killer=r["killer"],
        realm=r["realm"],
        map=r["map"],
        survivors=tuple(SurvivorOutcome(s) for s in json.loads(r["survivors"])),
        my_index=r["my_index"],
        hatch_used=None if r["hatch_used"] is None else bool(r["hatch_used"]),
        manual_outcome=ManualOutcome(r["manual_outcome"]) if r["manual_outcome"] else None,
        source=r["source"],
        ignored=bool(r["ignored"]),
        notes=r["notes"],
        verdict=Verdict(r["verdict"]),
        counted=bool(r["counted"]),
    )
