"""Find the user's image for a map: assets/maps/<realm>/<map>.<png|webp|jpg>.

Users name files loosely ('Temple of Purgation', 'Azarov’s', 'Abbatoir'), so
matching ignores case, apostrophes, accents and a leading 'The', then falls
back to fuzzy matching within the realm folder to absorb typos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from ...core.catalog import MapCatalog
from ...core.models import Map
from ...detection.text import norm

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".webp", ".jpg", ".jpeg"}
FUZZY_MIN = 90


def key(name: str) -> str:
    k = norm(name).replace("'", "")
    return k.removeprefix("THE ")


@dataclass(frozen=True)
class _Entry:
    realm_key: str
    map_key: str
    path: Path


class MapImages:
    def __init__(self, root: Path, catalog: MapCatalog) -> None:
        self.root, self.catalog = root, catalog
        self.entries: list[_Entry] = []
        self.rescan()

    def rescan(self) -> None:
        maps_dir = self.root / "maps"
        self.entries = [
            _Entry(key(f.parent.name), key(f.stem), f)
            for f in sorted(maps_dir.glob("*/*"))
            if f.suffix.lower() in IMAGE_EXTS and f.is_file()
        ] if maps_dir.is_dir() else []

    def find(self, m: Map) -> Path | None:
        rk, mk = key(m.realm), key(m.name)
        # Prefer files in the right realm folder; fall back to any folder.
        in_realm = [e for e in self.entries if fuzz.ratio(e.realm_key, rk) >= FUZZY_MIN]
        for pool in (in_realm, self.entries):
            exact = next((e for e in pool if e.map_key == mk), None)
            if exact:
                return exact.path
        best = max(in_realm, key=lambda e: fuzz.ratio(e.map_key, mk), default=None)
        if best and fuzz.ratio(best.map_key, mk) >= FUZZY_MIN and self._closest_map(best) == m:
            return best.path
        return None

    def _closest_map(self, e: _Entry) -> Map | None:
        """Which catalog map a file's name is nearest to. A typo'd file must be
        nearest to the map asking for it: 'East Wing.webp' is ~95% similar to
        'West Wing' but 100% to 'East Wing', so West must not take it."""
        return max(self.catalog.maps, key=lambda m: fuzz.ratio(e.map_key, key(m.name)), default=None)

    def report(self) -> tuple[list[Map], list[Path]]:
        """(maps without an image, image files no map uses)."""
        used, missing = set(), []
        for m in self.catalog.maps:
            p = self.find(m)
            if p is None:
                missing.append(m)
            else:
                used.add(p)
        return missing, [e.path for e in self.entries if e.path not in used]
