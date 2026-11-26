# SPDX-License-Identifier: GPL-3.0-only
"""The engine's module catalogue (`hello.catalogue`, lab ENGINE_PROTOCOL.md §7)."""
from __future__ import annotations

import json
import pathlib
from typing import Any

SNAPSHOT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "data" / "catalogue.json"


class Catalogue:
    def __init__(self, doc: dict):
        self.doc = {"modules": doc.get("modules", [])}
        self._mods = {m["id"]: m for m in self.doc["modules"]}
        self._params = {(m["id"], p["id"]): p for m in self.doc["modules"] for p in m.get("parameters", [])}

    @classmethod
    def load(cls, path: str | pathlib.Path = SNAPSHOT) -> "Catalogue":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def module(self, type_id: str) -> dict | None:
        return self._mods.get(type_id)

    def param(self, type_id: str, param_id: str) -> dict | None:
        return self._params.get((type_id, param_id))

    def port(self, type_id: str, port_id: str, direction: str) -> dict | None:
        m = self._mods.get(type_id)
        for p in (m or {}).get("ports", []):
            if p["id"] == port_id and p["direction"] == direction:
                return p
        return None

    def __contains__(self, type_id: Any) -> bool:
        return type_id in self._mods
