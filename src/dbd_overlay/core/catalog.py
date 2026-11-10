"""Known realms/maps, loaded from the packaged data/maps.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

from .models import Killer, Map


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


def _data(name: str) -> dict:
    return json.loads(resources.files("dbd_overlay.data").joinpath(name).read_text(encoding="utf-8"))


@cache
def load_maps() -> MapCatalog:
    return MapCatalog.from_dict(_data("maps.json"))


@cache
def load_killers() -> tuple[Killer, ...]:
    return tuple(Killer(k["name"], tuple(k.get("aliases", ()))) for k in _data("killers.json")["killers"])


def find_killer(name: str) -> Killer | None:
    return next((k for k in load_killers() if k.name == name), None)
