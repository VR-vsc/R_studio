"""Компилятор RDL → живое устройство (наследник `core.Device` из эмуляторов Ujin).

Устройство из RDL совместимо со всей обвязкой хакатона: публикует сигналы через
`UjinClient`, принимает `{"recv":[...]}`, работает в `CommandServer`, отдаёт
`declaration()`. Сверху добавлено: правила физики, переменные, отложенные
действия (after/hold) и события для сценариев.
"""
from __future__ import annotations

import random
import re
from typing import Any, Callable, Dict, List, Optional

from core import Device, Signal  # vendored emulators/core.py

from .expr import Expr, ExprError, compile_expr
from .models import DeviceSpec, SignalSpec
from .validate import analyze


class RDLError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        first = next((i for i in issues if i["severity"] == "error"), issues[0] if issues else {})
        super().__init__(f"{first.get('path', '')}: {first.get('message', 'ошибка RDL')}")


def control_for(s: SignalSpec) -> str:
    """Тип контрола Ujin по типу/группе сигнала."""
    acc = s.effective_access
    if s.type == "button":
        return "push_time"
    if s.type == "text":
        return "text"
    if s.type == "enum":
        return "list"
    if s.type == "bool":
        return "switch" if acc in ("rw", "w") else "list"
    if s.monotonic:
        return "counter"
    if acc == "r":
        return "graph"
    if s.min is not None and s.max is not None and s.group == "capability":
        return "range"
    return "counter"


def layout_for(s: SignalSpec) -> Optional[dict]:
    if s.options:
        return {int(k): v for k, v in s.options.items()}
    if s.type == "bool":
        return {0: "выкл", 1: "вкл"}
    return None


KIND = {"property": "property", "capability": "capability",
        "setting": "setting", "environment": "environment"}


class _Rule:
    __slots__ = ("id", "title", "on", "when", "actions")

    def __init__(self, id, title, on, when, actions):
        self.id, self.title, self.on, self.when, self.actions = id, title, on, when, actions


class _Action:
    __slots__ = ("set", "to", "after", "hold", "then", "log")

    def __init__(self, set=None, to=None, after=None, hold=None, then=None, log=None):
        self.set, self.to, self.after, self.hold, self.then, self.log = set, to, after, hold, then, log


class RDLDevice(Device):
    """Устройство, собранное из RDL-описания."""

    def __init__(self, spec: DeviceSpec, serial: str = "0", client=None,
                 logger: Callable[[str], None] = print, seed: int = 1):
        self.spec = spec
        self.model = spec.effective_model
        self.title = spec.title
        super().__init__(serial=serial, client=client, logger=logger)
        self.rng = random.Random(seed)
        self.t = 0.0
        self.vars: Dict[str, Any] = dict(spec.vars)
        self.specs: Dict[str, SignalSpec] = {}
        self.event_log: List[dict] = []
        self.on_event: Optional[Callable[[dict], None]] = None
        self._scheduled: List[tuple] = []  # (due_t, seq, name, Expr|value, reason)
        self._seq = 0
        self._started = False
        self._errors: Dict[str, int] = {}
        self.raw: Dict[str, float] = {}  # точные значения физики (без округления до precision)

        for s in spec.signals:
            self.specs[s.name] = s
            default = s.default if s.type == "text" else self._coerce(s, s.default)
            sig = Signal(s.name, s.title, control_for(s), s.effective_access,
                         KIND[s.group], default, s.unit, s.min, s.max, layout_for(s),
                         zero_safe=(s.type == "text"))
            self.add_signal(sig)

        known = set(self.specs) | set(self.vars)
        self.rules: List[_Rule] = []
        for i, r in enumerate(spec.behavior):
            when = compile_expr(r.when, known) if r.when not in (None, "") else None
            acts = []
            for a in r.do:
                acts.append(_Action(
                    set=a.set,
                    to=compile_expr(a.to, known) if a.set is not None else None,
                    after=a.after, hold=a.hold,
                    then=compile_expr(a.then, known) if a.then is not None else None,
                    log=a.log))
            self.rules.append(_Rule(r.id or f"r{i + 1}", r.title, r.on, when, acts))
        self.events = [(e, compile_expr(e.when, known)) for e in spec.events]
        self._event_state = {e.name: False for e, _ in self.events}
        self._prev = self.snapshot()

    # ------------------------------------------------------------------ values
    @staticmethod
    def _coerce(s: SignalSpec, v: Any) -> Any:
        if s.type == "text":
            return str(v)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        if s.type in ("bool", "button"):
            return 1 if v else 0
        if s.type == "enum":
            v = int(round(v))
        if s.min is not None and v < s.min:
            v = s.min
        if s.max is not None and v > s.max:
            v = s.max
        if s.type == "enum":
            return int(v)
        v = round(v, s.precision)
        return int(v) if s.precision == 0 else v

    @staticmethod
    def _clip(s: SignalSpec, v: Any) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        if s.min is not None and v < s.min:
            v = s.min
        if s.max is not None and v > s.max:
            v = s.max
        return v

    def env(self, **extra) -> Dict[str, Any]:
        e = {n: self.raw.get(n, sig.value) for n, sig in self.signals.items() if n in self.specs}
        e.update(self.vars)
        e["t"] = self.t
        e.update(extra)
        return e

    def snapshot(self) -> Dict[str, Any]:
        return {n: self.signals[n].value for n in self.specs}

    def assign(self, name: str, value: Any, reason: str = "") -> None:
        """Присвоить сигналу/переменной с приведением типа, диапазоном и монотонностью."""
        if name in self.specs:
            s = self.specs[name]
            if s.type == "number":
                exact = self._clip(s, value)
                if s.monotonic:
                    exact = max(exact, self.raw.get(name, self.signals[name].value))
                self.raw[name] = exact
                self.set_value(name, self._coerce(s, exact))
                return
            self.raw.pop(name, None)
            self.set_value(name, self._coerce(s, value))
        elif name in self.vars:
            self.vars[name] = value
        else:
            raise ExprError(f"нет сигнала/переменной '{name}'")

    def _eval(self, expr: Expr, where: str, **extra):
        try:
            return expr(self.env(**extra), self.rng.random)
        except Exception as exc:  # физика не должна ронять устройство
            n = self._errors.get(where, 0) + 1
            self._errors[where] = n
            if n <= 3:
                self.log(f"[{self.model}] ошибка в {where}: {exc}")
            return None

    # ------------------------------------------------------------------ rules
    def _run(self, rule: _Rule, dt: float, cmd: Optional[tuple] = None, **extra) -> bool:
        if rule.when is not None and not self._eval(rule.when, f"{rule.id}.when", dt=dt, **extra):
            return False
        for a in rule.actions:
            if a.log is not None:
                env = self.env(dt=dt, **extra)
                self.log(f"[{self.model}] " + _fmt(a.log, env))
                continue
            val = self._eval(a.to, f"{rule.id}.{a.set}", dt=dt, **extra)
            if val is None:
                continue
            if a.after:
                self._schedule(self.t + a.after, a.set, val, f"{rule.id} after")
                continue
            if cmd is not None and cmd[0] == a.set:
                before = cmd[1]  # hold после команды возвращает значение «до команды»
            else:
                before = self.vars.get(a.set) if a.set in self.vars else self.signals[a.set].value
            self.assign(a.set, val, rule.id)
            if a.hold:
                back = (self._eval(a.then, f"{rule.id}.then", dt=dt, **extra)
                        if a.then is not None else before)
                self._schedule(self.t + a.hold, a.set, back, f"{rule.id} hold")
        return True

    def _schedule(self, due: float, name: str, value: Any, reason: str) -> None:
        self._seq += 1
        self._scheduled.append((due, self._seq, name, value, reason))
        self._scheduled.sort()

    def on_command(self, name: str, value: Any) -> None:
        s = self.specs.get(name)
        if s is None:
            return
        old = self._prev.get(name, s.default)
        self.raw.pop(name, None)
        if s.type == "number":
            self.raw[name] = self._clip(s, value)
        v = self._coerce(s, value)
        self.signals[name].value = v
        for r in self.rules:
            if r.on in ("command", f"command:{name}"):
                self._run(r, 0, cmd=(name, old), value=v)

    def apply_command(self, name: str, value: Any) -> None:
        """Команда «как с платформы», без печати JOURNAL (для песочницы/движка)."""
        s = self.specs.get(name)
        if s is None:
            raise ExprError(f"нет сигнала '{name}'")
        if s.effective_access == "r":
            raise ExprError(f"сигнал '{name}' только читается")
        sig = self.signals[name]
        sig.value = self._coerce(s, value)
        if sig.management == "rw":
            self._dirty.add(name)
        self.on_command(name, value)

    def set_environment(self, name: str, value: Any) -> None:
        s = self.specs.get(name)
        if s is None or s.group != "environment":
            raise ExprError(f"'{name}' — не сигнал окружения")
        self.assign(name, value, "environment")

    def tick(self, dt: int) -> None:
        self.t += dt
        if not self._started:
            self._started = True
            for r in self.rules:
                if r.on == "start":
                    self._run(r, 0)
        while self._scheduled and self._scheduled[0][0] <= self.t + 1e-9:
            _, _, name, val, _reason = self._scheduled.pop(0)
            self.assign(name, val, _reason)
        for r in self.rules:
            if r.on == "tick":
                self._run(r, dt)
        now = self.snapshot()
        changed = [n for n in now if now[n] != self._prev.get(n)]
        if changed:
            for r in self.rules:
                if r.on.startswith("change:") and r.on[7:] in changed:
                    self._run(r, dt, old=self._prev.get(r.on[7:], 0))
        self._check_events()
        for n, s in self.specs.items():  # кнопка — импульс: после такта отпускается
            if s.type == "button" and self.signals[n].value:
                self.signals[n].value = 0
        self._prev = self.snapshot()

    def _check_events(self) -> None:
        prime = not getattr(self, "_events_primed", False)
        self._events_primed = True
        for e, cond in self.events:
            on = bool(self._eval(cond, f"event.{e.name}"))
            # первая проверка только запоминает исходное состояние: событие — это ПЕРЕХОД
            if on and not self._event_state[e.name] and not prime:
                rec = {"t": self.t, "device": self.serial, "event": e.name,
                       "title": e.title, "severity": e.severity}
                self.event_log.append(rec)
                del self.event_log[:-500]
                self.log(f"[{self.model}] событие: {e.title}")
                if self.on_event:
                    self.on_event(rec)
            self._event_state[e.name] = on

    # ------------------------------------------------------------------ export
    def state(self) -> dict:
        return {"t": self.t, "values": self.snapshot(), "vars": dict(self.vars),
                "events_active": [k for k, v in self._event_state.items() if v]}


def _fmt(text: str, env: Dict[str, Any]) -> str:
    return re.sub(r"\{([a-z_][a-z0-9_]*)\}", lambda m: str(env.get(m.group(1), m.group(0))), text)


def build_device(raw: Any, serial: str = "0", client=None,
                 logger: Callable[[str], None] = lambda _m: None, seed: int = 1) -> RDLDevice:
    spec, issues = (raw, []) if isinstance(raw, DeviceSpec) else analyze(raw)
    if spec is None:
        raise RDLError(issues)
    return RDLDevice(spec, serial=serial, client=client, logger=logger, seed=seed)


def ujin_declaration(spec: DeviceSpec, cls: str = "integrations_devices") -> dict:
    """Декларация модели для Ujin (ЛК разработчика / сид signal_dict)."""
    dev = RDLDevice(spec)
    signals = []
    for d in dev.declaration():
        if d["name"] == "fw" or d["kind"] == "environment":
            continue
        s = spec.signal(d["name"])
        d["full_name"] = f"{cls}_{d['name']}"
        d["default"] = s.default
        if s.monotonic:
            d["monotonic"] = True
        signals.append(d)
    return {
        "model": spec.effective_model,
        "class": cls,
        "title": spec.title,
        "signals": signals,
        "events": [{"name": e.name, "title": e.title, "severity": e.severity,
                    "condition": e.when} for e in spec.events],
        "publish_example": {
            "url": "POST /api/import_device/group-update-device-signal/?device-token=<dev|ust>",
            "body": {"data": [{"sn": "<ext_guid>", "s": signals[0]["full_name"] if signals else "",
                               "v": 1, "c": cls}]},
        },
        "notes": [
            "Новые сигналы публикуются в две фазы: короткое имя, затем полное (мина №2).",
            "Значение 0 уходит как 0.001 (мина №1).",
            "Поле c = класс модели, иначе значения теряются молча (мина №3).",
        ],
    }


def simulate(spec: DeviceSpec, seconds: int = 60, dt: int = 1,
             commands: Optional[List[dict]] = None, seed: int = 1) -> dict:
    """Прогон без сети: команды/окружение по таймлайну → ряды значений, события, журнал."""
    seconds = max(1, min(int(seconds), 3600))
    dt = max(1, int(dt))
    log: List[str] = []
    dev = RDLDevice(spec, serial=spec.id, logger=lambda m: log.append(m), seed=seed)
    plan = sorted(commands or [], key=lambda c: float(c.get("at", 0)))
    series: Dict[str, List[Any]] = {n: [] for n in dev.specs}
    times: List[float] = []
    errors: List[str] = []
    ci = 0
    steps = seconds // dt
    for _ in range(steps + 1):
        while ci < len(plan) and float(plan[ci].get("at", 0)) <= dev.t:
            c = plan[ci]
            ci += 1
            try:
                name = c["signal"]
                s = dev.specs.get(name)
                if s is not None and s.group == "environment":
                    dev.set_environment(name, c.get("value"))
                    log.append(f"[t={dev.t:g}] окружение: {name}={c.get('value')}")
                else:
                    dev.apply_command(name, c.get("value"))
                    log.append(f"[t={dev.t:g}] команда: {name}={c.get('value')}")
            except (KeyError, ExprError) as exc:
                errors.append(f"t={dev.t:g}: {exc}")
        times.append(dev.t)
        for n in series:
            series[n].append(dev.signals[n].value)
        if dev.t >= seconds:
            break
        dev.step(dt)
    return {"t": times, "series": series, "events": dev.event_log, "log": log[-300:],
            "errors": errors, "final": dev.state()}
