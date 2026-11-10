import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from dbd_overlay.core.models import ManualOutcome, MatchResult, Role, SurvivorOutcome as S, Verdict
from dbd_overlay.storage import db as db_mod
from dbd_overlay.storage.db import Database

T0 = datetime(2026, 11, 9, 20, 0, tzinfo=UTC)


def killer_match(killer="The Trapper", minutes=0, **kw):
    return MatchResult(
        role=Role.KILLER, killer=killer, realm="Backwater Swamp", map="The Pale Rose",
        survivors=(S.KILLED, S.KILLED, S.ESCAPED, S.DISCONNECTED), hatch_used=True,
        ts=T0 + timedelta(minutes=minutes), **kw,
    )


def test_fresh_db_is_latest_version():
    d = Database(":memory:")
    assert d.version == len(db_mod.MIGRATIONS)


def test_roundtrip_preserves_all_fields():
    d = Database(":memory:")
    m = killer_match(notes="close one")
    mid = d.add_match(m)
    assert d.get_match(mid) == m  # m.id was filled in by add_match


def test_survivor_and_manual_rows():
    d = Database(":memory:")
    m = MatchResult(role=Role.SURVIVOR, manual_outcome=ManualOutcome.WIN, source="manual", ts=T0)
    got = d.get_match(d.add_match(m))
    assert got.category == "survivor" and got.manual_outcome is ManualOutcome.WIN and got.survivors == ()


def test_filter_order_ignore_delete():
    d = Database(":memory:")
    a = d.add_match(killer_match(minutes=2))
    b = d.add_match(killer_match(minutes=1))
    d.add_match(killer_match(killer="The Wraith", minutes=3))
    trapper = d.matches("killer:The Trapper")
    assert [m.id for m in trapper] == [b, a]  # chronological, not insertion order
    assert d.last_match().killer == "The Wraith"
    d.set_ignored(a)
    assert d.get_match(a).ignored
    d.delete_match(b)
    assert [m.id for m in d.matches("killer:The Trapper")] == [a]
    assert [m.id for m in d.matches(since=T0 + timedelta(minutes=2))] == [d.last_match().id]


def test_resets():
    d = Database(":memory:")
    assert d.last_reset("survivor") is None
    d.add_reset("survivor", T0)
    d.add_reset("survivor", T0 + timedelta(hours=1))
    assert d.last_reset("survivor") == T0 + timedelta(hours=1)


def test_migrations_upgrade_and_persist(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    Database(path).close()
    # Simulate a future release that appends a migration.
    monkeypatch.setattr(db_mod, "MIGRATIONS", [*db_mod.MIGRATIONS, "ALTER TABLE matches ADD COLUMN extra TEXT;"])
    d = Database(path)
    assert d.version == len(db_mod.MIGRATIONS)
    cols = [r[1] for r in d.conn.execute("PRAGMA table_info(matches)")]
    assert "extra" in cols


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    Database(path).close()
    monkeypatch.setattr(
        db_mod, "MIGRATIONS",
        [*db_mod.MIGRATIONS, "CREATE TABLE half (x INT); THIS IS NOT SQL;"],
    )
    with pytest.raises(sqlite3.Error):
        Database(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db_mod.MIGRATIONS) - 1
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='half'").fetchone() is None


def test_refuses_newer_database(tmp_path):
    path = tmp_path / "m.db"
    sqlite3.connect(path).execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="upgrade the app"):
        Database(path)


def test_v1_database_upgrades_keeping_rows(tmp_path, monkeypatch):
    """A database created by M2-M5 (v1) gains the verdict column; old rows default to unknown."""
    path = tmp_path / "m.db"
    monkeypatch.setattr(db_mod, "MIGRATIONS", db_mod.MIGRATIONS[:1])
    old = Database(path)
    old.conn.execute(
        "INSERT INTO matches (ts, role, killer, source, category) "
        "VALUES ('2026-11-01T00:00:00+00:00', 'killer', 'The Hag', 'manual', 'killer:The Hag')")
    old.conn.commit()
    old.close()
    monkeypatch.undo()
    d = Database(path)
    (m,) = d.matches()
    assert m.verdict is Verdict.UNKNOWN and m.category == "killer:The Hag"


def test_set_verdict_and_reset_undo():
    d = Database(":memory:")
    mid = d.add_match(killer_match())
    d.set_verdict(mid, Verdict.WIN, ManualOutcome.WIN)
    m = d.get_match(mid)
    assert m.verdict is Verdict.WIN and m.manual_outcome is ManualOutcome.WIN
    d.add_reset("survivor", T0)
    d.add_reset("survivor", T0 + timedelta(hours=1))
    d.delete_last_reset("survivor")
    assert d.last_reset("survivor") == T0


def test_export_import_roundtrip(tmp_path):
    from dbd_overlay.storage.export import export, import_json

    src = Database(":memory:")
    src.add_match(killer_match(notes="a"))
    src.add_match(MatchResult(role=Role.SURVIVOR, manual_outcome=ManualOutcome.WIN, source="manual",
                              verdict=Verdict.WIN, ts=T0 + timedelta(minutes=5)))
    assert export(src, tmp_path / "x.json") == 2
    assert export(src, tmp_path / "x.csv") == 2
    assert (tmp_path / "x.csv").read_text().count("\n") == 3
    dst = Database(":memory:")
    assert import_json(dst, tmp_path / "x.json") == (2, 0)
    assert import_json(dst, tmp_path / "x.json") == (0, 2)  # no duplicates
    a, b = src.matches(), dst.matches()
    assert [(m.category, m.verdict, m.survivors, m.notes) for m in a] == [(m.category, m.verdict, m.survivors, m.notes) for m in b]


def test_v3_upgrade_keeps_existing_streaks_on(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    monkeypatch.setattr(db_mod, "MIGRATIONS", db_mod.MIGRATIONS[:2])
    old = Database(path)
    old.conn.execute("INSERT INTO matches (ts, role, killer, source, category, verdict) VALUES "
                     "('2026-11-01T00:00:00+00:00', 'killer', 'The Trapper', 'manual', 'killer:The Trapper', 'win')")
    old.conn.commit()
    old.close()
    monkeypatch.undo()
    d = Database(path)
    assert d.streak_active("killer:The Trapper") and d.matches()[0].counted   # was tracked: stays on
    assert not d.streak_active("killer:The Nurse")                            # new: off
