"""Known realms/maps, loaded from the packaged data/maps.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

from .models import Map


@dataclass(frozen=True)
class Realm:
    name: str
    maps: tuple[Map, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapCatalog:
    realms: tuple[Realm, ...]

    @property
    def maps(self) -> tuple[Map, ...]:
        return tuple(m for r in self.realms for m in r.maps)

    def realm(self, name: str) -> Realm | None:
        return next((r for r in self.realms if r.name == name), None)

    def find_map(self, name: str) -> Map | None:
        return next((m for m in self.maps if m.name == name), None)

    @staticmethod
    def from_dict(data: dict) -> MapCatalog:
        realms = []
        for r in data["realms"]:
            maps = []
            for m in r["maps"]:
                if isinstance(m, str):
                    maps.append(Map(realm=r["name"], name=m))
                else:
                    maps.append(Map(realm=r["name"], name=m["name"], aliases=tuple(m.get("aliases", ()))))
            realms.append(Realm(r["name"], tuple(maps), tuple(r.get("aliases", ()))))
        return MapCatalog(tuple(realms))


@cache
def load_maps() -> MapCatalog:
    text = resources.files("dbd_overlay.data").joinpath("maps.json").read_text(encoding="utf-8")
    return MapCatalog.from_dict(json.loads(text))
