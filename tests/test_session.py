from dbd_overlay.core.events import EventBus, KillerDetected, ScoreboardRead
from dbd_overlay.core.models import Role
from dbd_overlay.core.session import Session


def board(killer, role):
    return ScoreboardRead(killer, role, 0, 4, "ME", ())


def test_only_your_killer_is_remembered(tmp_path):
    bus, f = EventBus(), tmp_path / "state.json"
    s = Session(bus, f)
    bus.publish(board("The Nurse", Role.SURVIVOR))      # opponent: not yours
    assert s.my_killer is None
    bus.publish(board("The Trapper", Role.KILLER))
    assert s.my_killer == "The Trapper"
    bus.publish(KillerDetected("The Wraith", 1.0, source="scoreboard"))  # raw scoreboard event: ignored
    assert s.my_killer == "The Trapper"
    bus.publish(KillerDetected("The Hag", 1.0, source="manual"))
    assert s.my_killer == "The Hag"
    assert Session(EventBus(), f).my_killer == "The Hag"   # survives restart


def test_corrupt_state_file_is_ignored(tmp_path):
    f = tmp_path / "state.json"
    f.write_text("{nope")
    assert Session(EventBus(), f).my_killer is None


def test_category_and_role_persist(tmp_path):
    from dbd_overlay.core.events import RoleDetected

    bus, f = EventBus(), tmp_path / "state.json"
    s = Session(bus, f)
    assert s.category is None
    bus.publish(RoleDetected(Role.SURVIVOR))
    assert s.category == "survivor"
    bus.publish(KillerDetected("The Hag", 1.0, source="manual"))
    bus.publish(RoleDetected(Role.KILLER, source="manual"))
    assert s.category == "killer:The Hag"
    assert Session(EventBus(), f).category == "killer:The Hag"
