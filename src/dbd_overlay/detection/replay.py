"""Offline replay: run detection on saved screenshots instead of the live game.

    dbd-overlay replay ~/dbd-samples                 # what does it see?
    dbd-overlay replay tests/fixtures/screens --manifest tests/fixtures/screens/manifest.json

Frames are processed in filename order through the same MatchDetector the
live app uses (assuming `interval` seconds between frames), so the printed
events are exactly what the app would have published.

Manifest: per-file expectations; only the keys present are checked.
    {"225202.png": {"map": {"realm": "Backwater Swamp", "map": "The Pale Rose"}},
     "233047.png": {"map": null},                         <- no map detected
     "230226.png": {"end": {"kind": "scoreboard", "killer": "The Slasher", "role": "killer"}},
     "225210.png": {"end": null, "lobby": false, "egc": false},
     "230226.png": {"statuses": "EKEK"}}          <- E/K/F(lag)/A(live)/D/? per survivor
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import cv2

from ..core.catalog import load_killers, load_maps
from ..core.models import SurvivorOutcome
from .detector import MatchDetector, TickResult
from .end_screen import EndReading
from .map_detector import CardReading

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".ppm"}

# One letter per survivor status, for compact output and manifests ("EKEK").
STATUS_CODES = {SurvivorOutcome.ESCAPED: "E", SurvivorOutcome.KILLED: "K", SurvivorOutcome.SURRENDERED: "F",
                SurvivorOutcome.DISCONNECTED: "D", SurvivorOutcome.ALIVE: "A", SurvivorOutcome.UNKNOWN: "?"}


def expand(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS))
        else:
            files.append(p)
    return files


def check_map(r: CardReading, expected: dict | None) -> bool:
    m = r.match
    if expected is None:
        return m is None or (m.map is None and m.realm is None)
    return m is not None and m.realm == expected.get("realm") and m.map == expected.get("map")


def check_end(r: EndReading | None, expected: dict | None) -> bool:
    if expected is None:
        return r is None or r.kind is None
    if r is None or r.kind is None or r.kind.value != expected.get("kind"):
        return False
    b = r.scoreboard
    for key in ("killer", "role"):
        if key in expected:
            got = getattr(b, key, None) if b else None
            if (got.value if hasattr(got, "value") else got) != expected[key]:
                return False
    return True


def check(t: TickResult, expected: dict) -> list[str]:
    """Names of failed checks."""
    failed = []
    if "map" in expected and not check_map(t.card, expected["map"]):
        failed.append("map")
    if "end" in expected and not check_end(t.end, expected["end"]):
        failed.append("end")
    if "lobby" in expected and bool(t.lobby) != expected["lobby"]:
        failed.append("lobby")
    if "egc" in expected and bool(t.egc) != expected["egc"]:
        failed.append("egc")
    if "statuses" in expected:
        b = t.end.scoreboard if t.end else None
        got = "".join(STATUS_CODES[st] for st in b.statuses) if b else ""
        if got != expected["statuses"]:
            failed.append("statuses")
    return failed


def describe(t: TickResult) -> str:
    parts = []
    r = t.card
    if r.present:
        m = r.match
        result = f"{m.map or '?'} / {m.realm or '?'} ({m.confidence:.2f})" if m else "no match"
        parts.append(f"card@{r.separator_y} {'teal' if r.teal else 'grey'} map={r.map_text!r} realm={r.realm_text!r} -> {result}")
    if t.end is not None and t.end.kind is not None:
        s = f"end:{t.end.kind} {t.end.title!r}"
        if b := t.end.scoreboard:
            s += f" killer={b.killer} role={b.role} you={b.own_name!r}@row{b.my_row}"
            s += f" survivors={''.join(STATUS_CODES[st] for st in b.statuses)}"
        parts.append(s)
    if t.lobby:
        parts.append("lobby")
    if t.egc:
        parts.append("EGC")
    return "  |  ".join(parts) or "nothing"


def run(paths: list[Path], manifest: Path | None = None, verbose: bool = False, interval: float = 1.0) -> int:
    files = expand(paths)
    if not files:
        print("no images found")
        return 1
    expected: dict[str, dict] = json.loads(manifest.read_text()) if manifest else {}
    det = MatchDetector(load_maps(), load_killers(), exhaustive=True)
    failures = 0

    for i, f in enumerate(files):
        frame = cv2.imread(str(f), cv2.IMREAD_COLOR)
        if frame is None:
            print(f"{f.name}: unreadable image")
            failures += 1
            continue
        t = det.process(frame, i * interval)  # full frame: every reader runs
        verdict = ""
        if f.name in expected:
            failed = check(t, expected[f.name])
            failures += bool(failed)
            verdict = f"FAIL({','.join(failed)}) " if failed else "PASS "
        text = describe(t)
        if verbose or text != "nothing" or verdict.startswith("FAIL"):
            print(f"{verdict}{f.name}: {text}")
            if verdict.startswith("FAIL"):
                print(f"      expected {expected[f.name]}")
        for event in t.events:
            print(f"      -> {event}")

    print(f"\n{len(files)} frames", end="")
    if expected:
        checked = sum(f.name in expected for f in files)
        print(f", {checked} checked against manifest, {failures} failed")
    else:
        print()
    return 1 if failures else 0
