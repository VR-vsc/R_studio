"""Хранилище: библиотека устройств (RDL-документы) в папке data/ — обычные JSON-файлы."""
from __future__ import annotations

import json
import os
import shutil
import threading
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "app", "rdl", "templates")
DATA = os.environ.get("RSTUDIO_DATA", os.path.join(ROOT, "data"))

_lock = threading.Lock()


class Library:
    """Каталог JSON-документов одного вида (devices, scenarios, …)."""

    def __init__(self, kind: str, seed_dir: Optional[str] = None):
        self.dir = os.path.join(DATA, kind)
        self.seed_dir = seed_dir
        os.makedirs(self.dir, exist_ok=True)
        if seed_dir and not os.listdir(self.dir):
            for f in os.listdir(seed_dir):
                if f.endswith(".json"):
                    shutil.copy(os.path.join(seed_dir, f), os.path.join(self.dir, f))

    def _path(self, item_id: str) -> str:
        if not item_id or "/" in item_id or "\\" in item_id or item_id.startswith("."):
            raise KeyError(item_id)
        return os.path.join(self.dir, f"{item_id}.json")

    def ids(self) -> List[str]:
        return sorted(f[:-5] for f in os.listdir(self.dir) if f.endswith(".json"))

    def all(self) -> List[Dict]:
        out = []
        for i in self.ids():
            try:
                out.append(self.get(i))
            except (OSError, ValueError):
                continue
        return out

    def get(self, item_id: str) -> Dict:
        with open(self._path(item_id), encoding="utf-8") as fh:
            return json.load(fh)

    def exists(self, item_id: str) -> bool:
        try:
            return os.path.exists(self._path(item_id))
        except KeyError:
            return False

    def put(self, item_id: str, doc: Dict) -> None:
        path = self._path(item_id)
        tmp = path + ".tmp"
        with _lock:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)

    def delete(self, item_id: str) -> bool:
        path = self._path(item_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def is_builtin(self, item_id: str) -> bool:
        return bool(self.seed_dir) and os.path.exists(os.path.join(self.seed_dir, f"{item_id}.json"))

    def template(self, item_id: str) -> Dict:
        with open(os.path.join(self.seed_dir, f"{item_id}.json"), encoding="utf-8") as fh:
            return json.load(fh)


_devices: Optional[Library] = None


def devices() -> Library:
    global _devices
    if _devices is None:
        _devices = Library("devices", TEMPLATES)
    return _devices


SCENARIOS_SEED = os.path.join(ROOT, "app", "scenarios_seed")
_scenarios: Optional[Library] = None


def scenarios() -> Library:
    global _scenarios
    if _scenarios is None:
        _scenarios = Library("scenarios", SCENARIOS_SEED)
    return _scenarios
