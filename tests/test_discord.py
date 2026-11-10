"""Discord status: what it says (pure state), the IPC framing, the rate-limited pusher."""

import json
import socket
import struct
import threading
import time

import pytest

from dbd_overlay.core import config as config_mod
from dbd_overlay.core.events import (Event, EventBus, GameWindowChanged, KillerDetected, LobbyChanged, MapDetected,
                                     MatchEnded, MatchStarted, RoleDetected, ScoreboardRead)
from dbd_overlay.core.models import Role
from dbd_overlay.core.session import Session
from dbd_overlay.features.discord_presence import Pusher
from dbd_overlay.features.discord_presence import ipc as ipc_mod
from dbd_overlay.features.discord_presence.ipc import DiscordError, DiscordIpc
from dbd_overlay.features.discord_presence.state import PresenceState


@pytest.fixture
def world(tmp_path):
    """Bus + session + presence state wired in app order (session first)."""
    bus = EventBus()
    session = Session(bus, tmp_path / "state.json")
    now = [1000.0]
    state = PresenceState(session, clock=lambda: now[0])
    state.now = now  # tests move the clock
    bus.subscribe(Event, state.update)
    return bus, state


def lines(state):
    a = state.activity()
    return None if a is None else (a["details"], a.get("state"))


def test_full_killer_evening(world):
    bus, s = world
    assert s.activity() is None                                    # game not seen yet
    bus.publish(GameWindowChanged(True))
    assert lines(s) == ("In the menus", None)
    bus.publish(KillerDetected("The Hillbilly", 1.0, source="lobby"))
    bus.publish(RoleDetected(Role.KILLER, source="lobby"))
    bus.publish(LobbyChanged(True, "READY"))
    assert lines(s) == ("In the lobby", "Killer · The Hillbilly")
    bus.publish(LobbyChanged(True, "CANCEL"))
    assert lines(s) == ("Searching for a match", "Killer · The Hillbilly")
    bus.publish(LobbyChanged(False, "CANCEL"))                      # loading screen
    assert lines(s) == ("In a match as The Hillbilly", None)
    assert s.activity()["timestamps"] == {"start": 1000}
    s.now[0] = 1040.0
    bus.publish(MatchStarted())                                     # title card: real start + map
    bus.publish(MapDetected("Backwater Swamp", "The Pale Rose", 1.0))
    assert lines(s) == ("In a match as The Hillbilly", "The Pale Rose")
    assert s.activity()["timestamps"] == {"start": 1040}
    bus.publish(MatchEnded())
    bus.publish(ScoreboardRead("The Hillbilly", Role.KILLER, 0, 0, "me", (), result="BRUTAL KILLER"))
    assert lines(s) == ("Match over", "Brutal Killer")
    bus.publish(LobbyChanged(True, "READY"))
    assert lines(s)[0] == "In the lobby"
    bus.publish(GameWindowChanged(False, running=False))
    assert s.activity() is None                                    # game closed: clear status


def test_survivor_postgame_names_the_killer(world):
    bus, s = world
    bus.publish(GameWindowChanged(True))
    bus.publish(RoleDetected(Role.SURVIVOR, source="lobby"))
    bus.publish(MatchStarted())
    assert lines(s) == ("In a match as Survivor", None)            # map not read yet
    bus.publish(ScoreboardRead("The Pig", Role.SURVIVOR, 1, 0, "me", (), result="ESCAPED"))
    assert lines(s) == ("Match over", "Escaped · vs The Pig")


def test_lobby_after_play_is_menus_and_hidden_window_keeps_state(world):
    bus, s = world
    bus.publish(GameWindowChanged(True))
    bus.publish(LobbyChanged(True, "PLAY"))
    bus.publish(LobbyChanged(False, "PLAY"))
    assert lines(s)[0] == "In the menus"
    bus.publish(MatchStarted())
    bus.publish(GameWindowChanged(False))                          # other workspace, game still running
    assert lines(s)[0].startswith("In a match")


def test_lobby_ending_a_match_without_end_screens(world):
    """The detector publishes LobbyChanged before the MatchEnded it causes."""
    bus, s = world
    bus.publish(GameWindowChanged(True))
    bus.publish(MatchStarted())
    bus.publish(LobbyChanged(True, "PLAY"))
    bus.publish(MatchEnded())
    assert lines(s)[0] == "In the lobby"


def test_options_and_limits(world):
    bus, s = world
    s.large_image, s.show_map = "dbd", False
    bus.publish(GameWindowChanged(True))
    bus.publish(MatchStarted())
    bus.publish(MapDetected("Backwater Swamp", "The Pale Rose", 1.0))
    a = s.activity()
    assert "state" not in a and a["assets"]["large_image"] == "dbd"
    bus.publish(KillerDetected("X" * 200, 1.0, source="manual"))
    bus.publish(RoleDetected(Role.KILLER, source="manual"))
    assert len(s.activity()["details"]) == 128


# -- IPC ---------------------------------------------------------------------

def frame(op, payload):
    data = json.dumps(payload).encode()
    return struct.pack("<II", op, len(data)) + data


def read_frame(conn):
    op, n = struct.unpack("<II", conn.recv(8, socket.MSG_WAITALL))
    return op, json.loads(conn.recv(n, socket.MSG_WAITALL))


def fake_discord(path, script):
    """A one-connection Discord: answers each received frame with script(op, payload)."""
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen(1)
    got = []

    def serve():
        conn, _ = srv.accept()
        with conn, srv:
            while True:
                try:
                    op, payload = read_frame(conn)
                except (struct.error, OSError):
                    return
                got.append((op, payload))
                conn.sendall(script(op, payload))

    threading.Thread(target=serve, daemon=True).start()
    return got


def test_ipc_handshake_and_activity(tmp_path, monkeypatch):
    sock = tmp_path / "discord-ipc-0"
    monkeypatch.setattr(ipc_mod, "socket_candidates", lambda: [str(tmp_path / "missing"), str(sock)])

    def script(op, payload):
        if op == ipc_mod.OP_HANDSHAKE:
            return frame(1, {"evt": "READY", "data": {"user": {"username": "aj"}}})
        return frame(1, {"cmd": "SET_ACTIVITY", "evt": None, "nonce": payload["nonce"]})

    got = fake_discord(sock, script)
    c = DiscordIpc("123")
    c.connect()
    c.set_activity({"details": "In the lobby"})
    c.close()
    assert got[0] == (0, {"v": 1, "client_id": "123"})
    assert got[1][1]["cmd"] == "SET_ACTIVITY" and got[1][1]["args"]["activity"] == {"details": "In the lobby"}


def test_ipc_bad_client_id(tmp_path, monkeypatch):
    sock = tmp_path / "discord-ipc-0"
    monkeypatch.setattr(ipc_mod, "socket_candidates", lambda: [str(sock)])
    fake_discord(sock, lambda op, p: frame(2, {"code": 4000, "message": "Invalid Client ID"}))
    with pytest.raises(DiscordError, match="Invalid Client ID"):
        DiscordIpc("1").connect()


def test_ipc_no_discord(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc_mod, "socket_candidates", lambda: [str(tmp_path / "nope")])
    with pytest.raises(DiscordError, match="isn't running"):
        DiscordIpc("1").connect()


# -- pusher --------------------------------------------------------------------

class FakeIpc:
    def __init__(self):
        self.sent, self.connected = [], True

    def set_activity(self, a):
        self.sent.append(a)

    def close(self):
        self.connected = False


def wait_until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


def test_pusher_rate_limits_but_keeps_the_newest(monkeypatch):
    import dbd_overlay.features.discord_presence as feat
    monkeypatch.setattr(feat, "MIN_GAP", 0.3)
    fake = FakeIpc()
    p = Pusher(lambda: fake)
    p.submit({"details": "a"})
    assert wait_until(lambda: fake.sent == [{"details": "a"}])
    p.submit({"details": "b"})
    p.submit({"details": "c"})                     # within the gap: replaces b
    assert wait_until(lambda: len(fake.sent) == 2)
    assert fake.sent[1] == {"details": "c"}
    p.submit({"details": "c"})                     # unchanged: not resent
    time.sleep(0.4)
    p.stop()
    assert fake.sent == [{"details": "a"}, {"details": "c"}, None]   # stop clears the status


def test_pusher_retries_when_discord_is_missing(monkeypatch):
    import dbd_overlay.features.discord_presence as feat
    monkeypatch.setattr(feat, "MIN_GAP", 0.01)
    monkeypatch.setattr(feat, "RETRY_SECONDS", 0.1)
    fake, tries = FakeIpc(), []

    def connect():
        tries.append(1)
        if len(tries) < 3:
            raise DiscordError("not running")
        return fake

    p = Pusher(connect)
    p.submit({"details": "a"})
    assert wait_until(lambda: fake.sent == [{"details": "a"}])
    p.stop()
    assert len(tries) == 3


# -- config ------------------------------------------------------------------

def test_config_round_trip_and_validation(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config_mod.Config()
    cfg.discord.enabled, cfg.discord.client_id = True, "1234567890"
    config_mod.save(cfg, path)
    assert config_mod.load(path).discord == cfg.discord
    with pytest.raises(config_mod.ConfigError, match="client_id"):
        config_mod.from_dict({"discord": {"client_id": "Dead by Daylight"}})


def test_missed_title_card_still_shows_the_match(world):
    """The title card was up while the game's workspace was hidden."""
    bus, s = world
    bus.publish(GameWindowChanged(True))
    bus.publish(MatchStarted())
    bus.publish(MapDetected("Backwater Swamp", "The Pale Rose", 1.0))
    bus.publish(ScoreboardRead("The Pig", Role.SURVIVOR, 1, 0, "me", (), result="ESCAPED"))
    bus.publish(LobbyChanged(True, "READY"))
    bus.publish(LobbyChanged(False, "READY"))                       # next match loading...
    bus.publish(GameWindowChanged(False))                           # ...title card missed
    bus.publish(GameWindowChanged(True))
    a = s.activity()
    assert a["details"].startswith("In a match") and "state" not in a   # not last match's map
    bus.publish(MapDetected("Backwater Swamp", "Grim Pantry", 1.0, source="manual"))   # ctl set-map
    assert s.activity()["state"] == "Grim Pantry"


def test_map_outside_a_match_is_ignored(world):
    bus, s = world
    bus.publish(GameWindowChanged(True))
    bus.publish(LobbyChanged(True, "PLAY"))
    bus.publish(MapDetected("Backwater Swamp", "Grim Pantry", 1.0, source="manual"))
    assert lines(s) == ("In the lobby", None)
