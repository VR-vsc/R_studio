"""Блок 2 — эмуляция в реальном времени.

Хаб держит «квартиру»: набор экземпляров устройств (RDL → RDLDevice), крутит такты
в фоне (asyncio), принимает команды и изменения окружения, собирает события
и рассылает всё подписчикам (WebSocket-клиентам UI и движку сценариев).

Время модельное: 1 такт = 1 секунда модели; скорость ×N ускоряет такты.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import zlib
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from . import storage
from .rdl import RDLDevice, analyze
from .rdl.expr import ExprError

SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_apartment.json")
SPEEDS = (0.5, 1, 2, 5, 10, 20, 60)
DAY_START = 8 * 3600  # модель стартует в 08:00 — расписания «каждый день в ЧЧ:ММ» считаются от этого


class EmulationError(ValueError):
    pass


class Instance:
    """Экземпляр устройства в квартире: конфиг + живой RDLDevice."""

    def __init__(self, cfg: Dict[str, Any], hub: "Hub"):
        self.cfg = cfg
        self.hub = hub
        self.device: Optional[RDLDevice] = None
        self.error = ""
        self.build()

    @property
    def id(self) -> str:
        return self.cfg["id"]

    def build(self) -> None:
        """(Пере)собрать устройство из текущего RDL библиотеки."""
        lib = storage.devices()
        did = self.cfg["device_id"]
        self.error = ""
        self.device = None
        if not lib.exists(did):
            self.error = f"нет описания устройства «{did}» в библиотеке"
            return
        spec, issues = analyze(lib.get(did))
        if spec is None:
            first = next(i for i in issues if i["severity"] == "error")
            self.error = f"описание с ошибкой: {first['path']}: {first['message']}"
            return
        seed = zlib.crc32(self.id.encode()) or 1
        ujin = self.cfg.get("ujin") or {}
        dev = RDLDevice(spec, serial=ujin.get("ext") or self.id,
                        logger=lambda m: self.hub.log(self.id, m), seed=seed)
        dev.on_event = lambda rec: self.hub.on_device_event(self, rec)
        for name, value in (self.cfg.get("settings") or {}).items():
            s = dev.specs.get(name)
            if s is not None and s.group == "setting":
                dev.assign(name, value)
        dev._prev = dev.snapshot()
        self.device = dev

    def describe(self) -> Dict[str, Any]:
        d = self.device
        out = {
            "id": self.id,
            "device_id": self.cfg["device_id"],
            "title": self.cfg.get("title") or (d.spec.title if d else self.cfg["device_id"]),
            "room": self.cfg.get("room") or "Без комнаты",
            "ujin": self.cfg.get("ujin") or {},
            "error": self.error,
        }
        if d is not None:
            out.update({
                "model": d.model,
                "category": d.spec.category,
                "device_title": d.spec.title,
                "signals": [s.model_dump(exclude_none=True) for s in d.spec.signals],
                "events": [{"name": e.name, "title": e.title, "severity": e.severity}
                           for e in d.spec.events],
                "values": d.snapshot(),
                "active": [k for k, v in d._event_state.items() if v],
            })
        return out


class Hub:
    def __init__(self, persist: bool = True) -> None:
        self.persist = persist  # песочница проверки сценариев не трогает файлы квартиры
        self.day_start = DAY_START
        self.instances: Dict[str, Instance] = {}
        self.t = 0
        self.running = True
        self.speed: float = 1
        self.events: Deque[dict] = deque(maxlen=400)
        self.logs: Deque[dict] = deque(maxlen=400)
        self._seq = 0
        self._queues: List[asyncio.Queue] = []
        self._hooks: List[Callable[[str, dict], None]] = []
        self._task: Optional[asyncio.Task] = None
        self._lib_file = os.path.join(storage.DATA, "apartment.json")
        self.load()

    # ------------------------------------------------------------ конфиг квартиры
    def load(self) -> None:
        path = self._lib_file if os.path.exists(self._lib_file) else SEED_FILE
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.instances = {}
        for item in cfg.get("instances", []):
            self.instances[item["id"]] = Instance(item, self)
        if path == SEED_FILE and self.persist:
            self.save()

    def save(self) -> None:
        if not self.persist:
            return
        os.makedirs(os.path.dirname(self._lib_file), exist_ok=True)
        tmp = self._lib_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"instances": [i.cfg for i in self.instances.values()]}, fh,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, self._lib_file)

    def reset_to_seed(self) -> None:
        if os.path.exists(self._lib_file):
            os.remove(self._lib_file)
        self.load()
        self.t = 0
        self.events.clear()
        self.logs.clear()
        self.broadcast("snapshot", self.snapshot())

    # ------------------------------------------------------------ подписки
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)

    def add_hook(self, fn: Callable[[str, dict], None]) -> None:
        """Синхронный слушатель (движок сценариев): fn(kind, payload)."""
        self._hooks.append(fn)

    def broadcast(self, kind: str, payload: dict) -> None:
        for fn in list(self._hooks):
            try:
                fn(kind, payload)
            except Exception as exc:  # слушатель не должен ронять эмуляцию
                self.log("hub", f"слушатель упал: {exc}")
        msg = {"type": kind, **payload}
        for q in list(self._queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # медленный клиент — пропустит промежуточные кадры

    # ------------------------------------------------------------ журнал/события
    def log(self, iid: str, text: str) -> None:
        rec = {"t": self.t, "instance": iid, "text": text}
        self.logs.append(rec)
        self.broadcast("log", rec)

    def on_device_event(self, inst: Instance, rec: dict) -> None:
        self._seq += 1
        ev = {
            "id": self._seq, "t": self.t, "wall": time.time(),
            "instance": inst.id, "instance_title": inst.describe()["title"],
            "room": inst.cfg.get("room", ""), "device_id": inst.cfg["device_id"],
            "event": rec["event"], "title": rec["title"], "severity": rec["severity"],
        }
        self.events.append(ev)
        self.broadcast("event", ev)

    # ------------------------------------------------------------ состояние
    def snapshot(self) -> dict:
        return {"t": self.t, "day_start": self.day_start, "running": self.running, "speed": self.speed,
                "instances": [i.describe() for i in self.instances.values()],
                "events": list(self.events)[-60:]}

    def get(self, iid: str) -> Instance:
        inst = self.instances.get(iid)
        if inst is None:
            raise EmulationError(f"нет устройства «{iid}» в квартире")
        return inst

    def _diff_and_send(self, before: Dict[str, Dict[str, Any]], source: str = "tick") -> None:
        changes: Dict[str, Dict[str, Any]] = {}
        active: Dict[str, List[str]] = {}
        for iid, inst in self.instances.items():
            d = inst.device
            if d is None:
                continue
            now = d.snapshot()
            old = before.get(iid, {})
            diff = {k: v for k, v in now.items() if old.get(k) != v}
            if diff:
                changes[iid] = diff
            active[iid] = [k for k, v in d._event_state.items() if v]
        self.broadcast("values", {"t": self.t, "source": source, "changes": changes,
                                  "active": active})

    def _before(self) -> Dict[str, Dict[str, Any]]:
        return {iid: i.device.snapshot() for iid, i in self.instances.items() if i.device}

    # ------------------------------------------------------------ такты
    def step(self, n: int = 1) -> None:
        for _ in range(max(1, n)):
            before = self._before()
            self.t += 1
            for inst in self.instances.values():
                if inst.device is not None:
                    inst.device.step(1)
            self._diff_and_send(before)
            self.broadcast("tick", {"t": self.t})

    async def run(self) -> None:
        while True:
            if self.running:
                self.step()
            await asyncio.sleep(1 / self.speed)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def set_clock(self, running: Optional[bool] = None, speed: Optional[float] = None) -> None:
        if running is not None:
            self.running = bool(running)
        if speed is not None:
            if speed not in SPEEDS:
                raise EmulationError("скорость: " + ", ".join(f"×{s:g}" for s in SPEEDS))
            self.speed = speed
        self.broadcast("clock", {"t": self.t, "running": self.running, "speed": self.speed})

    # ------------------------------------------------------------ воздействия
    def act(self, iid: str, signal: str, value: Any, source: str = "user") -> dict:
        """Команда (возможность/настройка) или изменение окружения — как с пульта."""
        inst = self.get(iid)
        dev = inst.device
        if dev is None:
            raise EmulationError(inst.error or "устройство не собрано")
        s = dev.specs.get(signal)
        if s is None:
            raise EmulationError(f"у «{inst.describe()['title']}» нет сигнала «{signal}»")
        before = self._before()
        try:
            if s.group == "environment":
                dev.set_environment(signal, value)
                kind = "окружение"
            else:
                dev.apply_command(signal, value)
                kind = "команда"
        except ExprError as exc:
            raise EmulationError(str(exc)) from None
        if s.group == "setting":  # настройки переживают перезапуск
            inst.cfg.setdefault("settings", {})[signal] = dev.signals[signal].value
            self.save()
        dev.flush()
        self.log(iid, f"{kind} ({source}): {s.title} = {value}")
        self._diff_and_send(before, source)
        return {"ok": True, "value": dev.signals[signal].value}

    def time_of_day(self) -> int:
        return int(self.day_start + self.t) % 86400

    def force(self, iid: str, signal: str, value: Any, source: str = "проверка") -> None:
        """Песочница: выставить любое значение (даже показание) — чтобы вызвать триггер."""
        inst = self.get(iid)
        if inst.device is None or signal not in inst.device.specs:
            raise EmulationError(f"нет сигнала «{signal}»")
        before = self._before()
        inst.device.assign(signal, value)
        inst.device._prev = inst.device.snapshot()
        self.log(iid, f"{source}: {inst.device.specs[signal].title} = {value}")
        self._diff_and_send(before, source)

    def recv(self, iid: str, payload: dict) -> dict:
        """Приём команды в формате сервера опроса Ujin: {"recv":[{"command":"management",...}]}."""
        inst = self.get(iid)
        if inst.device is None:
            raise EmulationError(inst.error)
        before = self._before()
        inst.device.handle_recv(payload)
        self._diff_and_send(before, "ujin")
        return {"error": 0}

    # ------------------------------------------------------------ состав квартиры
    def add(self, cfg: Dict[str, Any]) -> Instance:
        iid = cfg.get("id") or ""
        if not iid or iid in self.instances:
            raise EmulationError(f"имя «{iid}» пустое или уже занято")
        if not storage.devices().exists(cfg.get("device_id", "")):
            raise EmulationError(f"нет устройства «{cfg.get('device_id')}» в библиотеке")
        inst = Instance(cfg, self)
        self.instances[iid] = inst
        self.save()
        self.broadcast("snapshot", self.snapshot())
        return inst

    def update(self, iid: str, patch: Dict[str, Any]) -> Instance:
        inst = self.get(iid)
        for k in ("title", "room", "ujin"):
            if k in patch:
                inst.cfg[k] = patch[k]
        if "ujin" in patch:
            inst.build()
        self.save()
        self.broadcast("snapshot", self.snapshot())
        return inst

    def remove(self, iid: str) -> None:
        self.get(iid)
        del self.instances[iid]
        self.save()
        self.broadcast("snapshot", self.snapshot())

    def restart(self, iid: Optional[str] = None) -> None:
        """Пересобрать экземпляр(ы) из RDL: начальное состояние, без сброса часов."""
        for inst in self.instances.values():
            if iid is None or inst.id == iid:
                inst.build()
        self.broadcast("snapshot", self.snapshot())

    def reload_device(self, device_id: str) -> None:
        """Описание устройства изменили в конструкторе — пересобираем его экземпляры."""
        hit = False
        for inst in self.instances.values():
            if inst.cfg["device_id"] == device_id:
                inst.build()
                hit = True
        if hit:
            self.broadcast("snapshot", self.snapshot())


_hub: Optional[Hub] = None


def hub() -> Hub:
    global _hub
    if _hub is None:
        _hub = Hub()
    return _hub
