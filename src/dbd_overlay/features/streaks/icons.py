"""Streak icons.

Two sources, first wins:
  1. picked in Settings > Icons (config [icons], full paths);
  2. files dropped in assets/icons/: survivor.<ext>, killers/<killer>.<ext>.
     Loose names like the maps: 'Trapper.webp' works for 'The Trapper'.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from rapidfuzz import fuzz

from ...core.config import IconsConfig
from ..map_overlay.assets import IMAGE_EXTS, key

FUZZY_MIN = 90


class Icons:
    def __init__(self, assets_root: Path, overrides: IconsConfig | None = None) -> None:
        self.root = assets_root
        self.dir = assets_root / "icons"
        self.overrides = overrides or IconsConfig()

    def with_overrides(self, overrides: IconsConfig) -> Icons:
        return Icons(self.root, dataclasses.replace(overrides, killers=dict(overrides.killers)))

    # -- lookups ---------------------------------------------------------------

    def survivor(self) -> Path | None:
        return self.source("survivor")[0]

    def killer(self, name: str) -> Path | None:
        return self.source(f"killer:{name}")[0]

    def source(self, category: str) -> tuple[Path | None, str]:
        """(icon, where it came from: 'custom' | 'assets' | '')."""
        if category == "survivor":
            picked = self.overrides.survivor
        else:
            picked = self.overrides.killers.get(category.removeprefix("killer:"), "")
        if picked and Path(picked).expanduser().is_file():
            return Path(picked).expanduser(), "custom"
        found = self._folder_survivor() if category == "survivor" else self._folder_killer(category.removeprefix("killer:"))
        return (found, "assets") if found else (None, "")

    def set(self, category: str, path: str) -> None:
        """Pick an icon ('' = back to the assets folder)."""
        if category == "survivor":
            self.overrides.survivor = path
        elif path:
            self.overrides.killers[category.removeprefix("killer:")] = path
        else:
            self.overrides.killers.pop(category.removeprefix("killer:"), None)

    # -- assets folder -----------------------------------------------------------

    def _files(self, folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        return sorted(f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS and f.is_file())

    def _folder_survivor(self) -> Path | None:
        return next((f for f in self._files(self.dir) if key(f.stem) == "SURVIVOR"), None)

    def _folder_killer(self, name: str) -> Path | None:
        files = self._files(self.dir / "killers")  # rescanned each time: new files show up live
        k = key(name)
        exact = next((f for f in files if key(f.stem) == k), None)
        if exact:
            return exact
        best = max(files, key=lambda f: fuzz.ratio(key(f.stem), k), default=None)
        return best if best and fuzz.ratio(key(best.stem), k) >= FUZZY_MIN else None
