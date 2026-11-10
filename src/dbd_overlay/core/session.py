"""What we currently believe about the player and match: role, killer, map.

Role and your killer are remembered across restarts, so the HUD shows the
right streak right away.

'my_killer' is the killer YOU play (for per-killer streaks). It's updated by
the scoreboard only when you were the killer, or by a manual pick, and
remembered across restarts ("last used killer").
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .events import EventBus, KillerDetected, MapDetected, MatchStarted, RoleDetected, ScoreboardRead
from .models import SURVIVOR_CATEGORY, Role, killer_category

log = logging.getLogger(__name__)


class Session:
    def __init__(self, bus: EventBus, state_file: Path) -> None:
        self.state_file = state_file
        self._lock = threading.Lock()
        self.role: Role | None = None
        self.map: str | None = None
        self.realm: str | None = None
        self.my_killer: str | None = None
        self.last_board: ScoreboardRead | None = None
        self._load()
        bus.subscribe(MatchStarted, self._on_match_started)
        bus.subscribe(MapDetected, self._on_map)
        bus.subscribe(RoleDetected, self._on_role)
        bus.subscribe(KillerDetected, self._on_killer)
        bus.subscribe(ScoreboardRead, self._on_board)

    @property
    def category(self) -> str | None:
        """The streak you're currently on: survivor, or the killer you play."""
        with self._lock:
            if self.role is Role.SURVIVOR:
                return SURVIVOR_CATEGORY
            if self.role is Role.KILLER and self.my_killer:
                return killer_category(self.my_killer)
            return None

    def _on_match_started(self, _: MatchStarted) -> None:
        with self._lock:
            self.map = self.realm = None
            self.last_board = None

    def _on_map(self, e: MapDetected) -> None:
        if e.map:
            with self._lock:
                self.map, self.realm = e.map, e.realm

    def _on_role(self, e: RoleDetected) -> None:
        with self._lock:
            changed = e.role is not self.role
            self.role = e.role
        if changed:
            self._save()

    def _on_killer(self, e: KillerDetected) -> None:
        # Scoreboard KillerDetected may be the OPPONENT's killer; _on_board
        # decides for those. Manual picks are always yours.
        if e.source == "manual":
            self._set_my_killer(e.killer)

    def _on_board(self, e: ScoreboardRead) -> None:
        with self._lock:
            self.last_board = e
        if e.role is Role.KILLER and e.killer:
            self._set_my_killer(e.killer)

    def _set_my_killer(self, killer: str) -> None:
        with self._lock:
            changed = killer != self.my_killer
            self.my_killer = killer
        if changed:
            self._save()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self.state_file.read_text())
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as e:
            log.warning("ignoring unreadable %s: %s", self.state_file, e)
            return
        self.my_killer = data.get("my_killer")
        role = data.get("role")
        self.role = Role(role) if role in ("killer", "survivor") else None

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        data = {"my_killer": self.my_killer, "role": self.role.value if self.role else None}
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.state_file)
