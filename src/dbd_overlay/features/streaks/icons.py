"""User-supplied icons: assets/icons/killers/<killer>.<ext>, assets/icons/survivor.<ext>.

Loose names like the maps: 'Trapper.webp' works for 'The Trapper'.
"""

from __future__ import annotations

from pathlib import Path

from rapidfuzz import fuzz

from ..map_overlay.assets import IMAGE_EXTS, key

FUZZY_MIN = 90


class Icons:
    def __init__(self, assets_root: Path) -> None:
        self.dir = assets_root / "icons"

    def _files(self, folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        return sorted(f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS and f.is_file())

    def survivor(self) -> Path | None:
        return next((f for f in self._files(self.dir) if key(f.stem) == "SURVIVOR"), None)

    def killer(self, name: str) -> Path | None:
        files = self._files(self.dir / "killers")  # rescanned each time: new files show up live
        k = key(name)
        exact = next((f for f in files if key(f.stem) == k), None)
        if exact:
            return exact
        best = max(files, key=lambda f: fuzz.ratio(key(f.stem), k), default=None)
        return best if best and fuzz.ratio(key(best.stem), k) >= FUZZY_MIN else None
