"""Offline replay: run detection on saved screenshots instead of the live game.

    dbd-overlay replay ~/dbd-samples                 # what does it see?
    dbd-overlay replay tests/fixtures/screens --manifest tests/fixtures/screens/manifest.json

Frames are processed in filename order and fed to the same tracker the live
app uses (assuming `interval` seconds between frames), so the printed events
are exactly what the app would have published.

Manifest format (per-frame expectations; files not listed aren't checked):
    {"225202.png": {"realm": "Backwater Swamp", "map": "The Pale Rose"},
     "233047.png": null}          <- null = no map must be detected
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import cv2

from ..core.catalog import load_maps
from .map_detector import CardReading, TitleCardReader, TitleCardTracker

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".ppm"}


def expand(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS))
        else:
            files.append(p)
    return files


def check(reading: CardReading, expected: dict | None) -> bool:
    if expected is None:
        return reading.match is None or reading.match.map is None and reading.match.realm is None
    m = reading.match
    return m is not None and m.realm == expected.get("realm") and m.map == expected.get("map")


def describe(r: CardReading) -> str:
    if not r.present:
        return "no card"
    m = r.match
    result = f"{m.map or '?'} / {m.realm or '?'} ({m.confidence:.2f})" if m else "no match"
    return (f"card@{r.separator_y} {'teal' if r.teal else 'grey'}  "
            f"map={r.map_text!r} realm={r.realm_text!r}  ->  {result}")


def run(paths: list[Path], manifest: Path | None = None, verbose: bool = False, interval: float = 1.0) -> int:
    files = expand(paths)
    if not files:
        print("no images found")
        return 1
    expected: dict[str, dict | None] = json.loads(manifest.read_text()) if manifest else {}
    reader, tracker = TitleCardReader(load_maps()), TitleCardTracker()
    failures = cards = 0

    for i, f in enumerate(files):
        frame = cv2.imread(str(f), cv2.IMREAD_COLOR)
        if frame is None:
            print(f"{f.name}: unreadable image")
            failures += 1
            continue
        r = reader.read(frame)
        cards += r.present
        verdict = ""
        if f.name in expected:
            ok = check(r, expected[f.name])
            failures += not ok
            verdict = "PASS " if ok else "FAIL "
        if verbose or r.present or verdict == "FAIL ":
            print(f"{verdict}{f.name}: {describe(r)}")
            if verdict == "FAIL ":
                print(f"      expected {expected[f.name]}")
        for event in tracker.update(r, i * interval):
            print(f"      -> event {event}")

    # Flush: pretend the card disappeared after the last frame.
    for event in tracker.update(CardReading(), len(files) * interval + 60):
        print(f"      -> event {event}")

    print(f"\n{len(files)} frames, {cards} with a title-card line", end="")
    if expected:
        checked = sum(f.name in expected for f in files)
        print(f", {checked} checked against manifest, {failures} failed")
    else:
        print()
    return 1 if failures else 0
