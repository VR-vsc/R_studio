"""Блок 3 — язык сценариев R Studio: «Когда → И если → То».

Сценарий связывает устройства квартиры через их RDL-описания: триггеры ссылаются
на события и сигналы, действия — на возможности. Поэтому проверка точная:
нельзя скомандовать то, что устройство не умеет, или ждать события, которого нет.

    {
      "id": "leak_protect", "title": "Защита от протечки", "enabled": true,
      "triggers":   [{"type": "event", "instance": "bath_leak", "event": "leak_detected"}],
      "conditions": [{"instance": "bath_valve", "signal": "valve", "op": "==", "value": 1}],
      "match": "all",
      "actions": [
        {"type": "command", "instance": "bath_valve", "signal": "valve", "value": 0},
        {"type": "command", "instance": "hall_siren", "signal": "siren", "value": 1, "hold": 60},
        {"type": "notify", "text": "Протечка в ванной — воду перекрыли", "severity": "critical", "to": "resident"}
      ],
      "cooldown": 30
    }
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .rdl.validate import _path, _PYDANTIC_RU

ID_PATTERN = r"^[a-z][a-z0-9_]{1,40}$"
Op = Literal["==", "!=", ">", ">=", "<", "<="]
Value = Union[int, float, str]

OP_TEXT = {"==": "равно", "!=": "не равно", ">": "больше", ">=": "не меньше",
           "<": "меньше", "<=": "не больше"}
SEVERITY_TEXT = {"info": "сообщение", "warning": "предупреждение", "critical": "тревога"}
TO_TEXT = {"resident": "жителя", "uk": "УК", "all": "жителя и УК"}
TRIG_OP = {"==": "становится", "!=": "перестаёт быть", ">": "превышает", ">=": "достигает",
           "<": "опускается ниже", "<=": "опускается до"}
COND_OP = {"==": "", "!=": "не ", ">": "больше ", ">=": "не меньше ", "<": "меньше ", "<=": "не больше "}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Trigger(_Strict):
    type: Literal["event", "value", "schedule", "manual"]
    instance: str = ""
    event: str = ""                       # type=event
    signal: str = ""                      # type=value
    op: Op = "=="
    value: Optional[Value] = None
    at: str = Field("", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")  # type=schedule: время модели ЧЧ:ММ
    every: Optional[int] = Field(None, ge=10, le=86400)            # type=schedule: каждые N секунд


class Condition(_Strict):
    instance: str
    signal: str
    op: Op = "=="
    value: Value


class Action(_Strict):
    type: Literal["command", "notify", "wait"]
    instance: str = ""
    signal: str = ""
    value: Optional[Value] = None
    delay: float = Field(0, ge=0, le=86400)          # отложить это действие (не блокирует остальные)
    hold: Optional[float] = Field(None, gt=0, le=86400)  # вернуть прежнее значение через N секунд
    text: str = Field("", max_length=300)            # notify
    severity: Literal["info", "warning", "critical"] = "info"
    to: Literal["resident", "uk", "all"] = "resident"
    seconds: float = Field(0, ge=0, le=86400)        # wait: пауза перед следующими действиями


class Scenario(_Strict):
    rsl: Literal["1.0"] = "1.0"
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    enabled: bool = True
    triggers: List[Trigger] = Field(min_length=1)
    conditions: List[Condition] = Field(default_factory=list)
    match: Literal["all", "any"] = "all"
    actions: List[Action] = Field(min_length=1)
    cooldown: float = Field(0, ge=0, le=86400, description="Не запускать повторно N секунд")


Issue = Dict[str, str]


def _issue(path: str, message: str, severity: str = "error") -> Issue:
    return {"path": path, "message": message, "severity": severity}


# ------------------------------------------------------------------ каталог квартиры
class Catalog:
    """Что есть в квартире: устройства, их сигналы и события (из живого хаба)."""

    def __init__(self, instances: List[dict]):
        self.inst = {i["id"]: i for i in instances}

    @classmethod
    def from_hub(cls) -> "Catalog":
        from .emulation import hub
        return cls([i.describe() for i in hub().instances.values()])

    def signal(self, iid: str, name: str) -> Optional[dict]:
        for s in self.inst.get(iid, {}).get("signals", []):
            if s["name"] == name:
                return s
        return None

    def event(self, iid: str, name: str) -> Optional[dict]:
        for e in self.inst.get(iid, {}).get("events", []):
            if e["name"] == name:
                return e
        return None

    def title(self, iid: str) -> str:
        i = self.inst.get(iid)
        return i["title"] if i else f"«{iid}»"

    def fmt(self, iid: str, name: str, value: Any) -> str:
        s = self.signal(iid, name)
        if s is None or value is None:
            return str(value)
        opts = s.get("options") or {}
        try:
            key = str(int(float(value)))
        except (TypeError, ValueError):
            key = str(value)
        if key in opts:
            return f"«{opts[key]}»"
        unit = s.get("unit") or ""
        return f"{value:g} {unit}".strip() if isinstance(value, (int, float)) else str(value)


# ------------------------------------------------------------------ проверка
def analyze(raw: Any, cat: Optional[Catalog] = None) -> Tuple[Optional[Scenario], List[Issue]]:
    issues: List[Issue] = []
    try:
        sc = Scenario.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = [p for p in err["loc"] if not (isinstance(p, str) and p in ("int", "float", "str"))]
            issues.append(_issue(_path(loc), _PYDANTIC_RU.get(err["type"], err["msg"])))
        return None, issues
    cat = cat or Catalog.from_hub()

    def need_instance(path: str, iid: str) -> bool:
        if not iid:
            issues.append(_issue(path, "выберите устройство"))
            return False
        if iid not in cat.inst:
            issues.append(_issue(path, f"в квартире нет устройства «{iid}»"))
            return False
        if cat.inst[iid].get("error"):
            issues.append(_issue(path, f"устройство «{cat.title(iid)}» сейчас не работает: {cat.inst[iid]['error']}"))
            return False
        return True

    def check_value(path: str, iid: str, name: str, value: Any, op: str = "==") -> None:
        s = cat.signal(iid, name)
        if s is None:
            return
        t = s.get("type", "number")
        if value is None or value == "":
            issues.append(_issue(path, "укажите значение"))
            return
        if t in ("number", "bool", "enum", "button"):
            try:
                v = float(value)
            except (TypeError, ValueError):
                issues.append(_issue(path, "нужно число"))
                return
            if t in ("bool", "enum") and op in ("==", "!=") and s.get("options") and str(int(v)) not in s["options"]:
                issues.append(_issue(path, "такого варианта нет: " + ", ".join(
                    f"{k} — {x}" for k, x in s["options"].items())))
            lo, hi = s.get("min"), s.get("max")
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                issues.append(_issue(path, f"значение вне диапазона {lo:g}…{hi:g}" if lo is not None and hi is not None
                                     else "значение вне допустимого диапазона", "warning"))

    def check_signal(path: str, iid: str, name: str, writable: bool = False) -> bool:
        s = cat.signal(iid, name)
        if not name:
            issues.append(_issue(path, "выберите сигнал"))
            return False
        if s is None:
            issues.append(_issue(path, f"у «{cat.title(iid)}» нет сигнала «{name}»"))
            return False
        if writable and s["group"] not in ("capability", "setting"):
            issues.append(_issue(path, f"«{s['title']}» нельзя задать командой — это "
                                 + ("показание датчика" if s["group"] == "property" else "окружение")))
            return False
        return True

    triggered_signals = set()
    for i, t in enumerate(sc.triggers):
        p = f"triggers[{i}]"
        if t.type == "event":
            if need_instance(f"{p}.instance", t.instance):
                if not t.event:
                    issues.append(_issue(f"{p}.event", "выберите событие"))
                elif cat.event(t.instance, t.event) is None:
                    issues.append(_issue(f"{p}.event", f"у «{cat.title(t.instance)}» нет события «{t.event}»"))
        elif t.type == "value":
            if need_instance(f"{p}.instance", t.instance) and check_signal(f"{p}.signal", t.instance, t.signal):
                check_value(f"{p}.value", t.instance, t.signal, t.value, t.op)
                triggered_signals.add((t.instance, t.signal))
        elif t.type == "schedule":
            if not t.at and not t.every:
                issues.append(_issue(p, "укажите время (ЧЧ:ММ) или период"))
    for i, c in enumerate(sc.conditions):
        p = f"conditions[{i}]"
        if need_instance(f"{p}.instance", c.instance) and check_signal(f"{p}.signal", c.instance, c.signal):
            check_value(f"{p}.value", c.instance, c.signal, c.value, c.op)
    for i, a in enumerate(sc.actions):
        p = f"actions[{i}]"
        if a.type == "command":
            if need_instance(f"{p}.instance", a.instance) and check_signal(f"{p}.signal", a.instance, a.signal, True):
                s = cat.signal(a.instance, a.signal)
                if s.get("type") == "button":
                    if a.hold:
                        issues.append(_issue(f"{p}.hold", "кнопку нельзя «удержать» — это импульс", "warning"))
                else:
                    check_value(f"{p}.value", a.instance, a.signal, a.value)
                if (a.instance, a.signal) in triggered_signals:
                    issues.append(_issue(p, "действие меняет сигнал, который запускает этот же сценарий — "
                                         "возможен цикл", "warning"))
        elif a.type == "notify" and not a.text.strip():
            issues.append(_issue(f"{p}.text", "напишите текст уведомления"))
        elif a.type == "wait" and a.seconds <= 0:
            issues.append(_issue(f"{p}.seconds", "пауза должна быть больше нуля"))
    if not any(a.type in ("command", "notify") for a in sc.actions):
        issues.append(_issue("actions", "сценарий ничего не делает — добавьте команду или уведомление"))
    has_err = any(i["severity"] == "error" for i in issues)
    return (None if has_err else sc), issues


# ------------------------------------------------------------------ человеческий текст
def describe(sc: Scenario, cat: Optional[Catalog] = None) -> Dict[str, Any]:
    """Сценарий одной фразой и по частям — для жителя, УК и жюри."""
    cat = cat or Catalog.from_hub()
    whens = [trigger_text(t, cat) for t in sc.triggers]
    ifs = [condition_text(c, cat) for c in sc.conditions]
    dos = [action_text(a, cat) for a in sc.actions]
    sentence = "Когда " + " или ".join(whens)
    if ifs:
        sentence += ", и если " + (" и " if sc.match == "all" else " или ").join(ifs)
    sentence += ", то " + "; ".join(dos) + "."
    return {"sentence": sentence, "when": whens, "if": ifs, "do": dos}


def _sig(cat: Catalog, iid: str, name: str) -> str:
    s = cat.signal(iid, name)
    if not s:
        return name
    t = s["title"]
    return t if len(t) > 1 and t[1].isupper() else t[0].lower() + t[1:]  # «CO₂» не трогаем


def trigger_text(t: Trigger, cat: Catalog) -> str:
    if t.type == "event":
        e = cat.event(t.instance, t.event)
        return f"«{cat.title(t.instance)}» сообщает «{e['title'] if e else t.event}»"
    if t.type == "value":
        return (f"у «{cat.title(t.instance)}» {_sig(cat, t.instance, t.signal)} {TRIG_OP[t.op]} "
                f"{cat.fmt(t.instance, t.signal, t.value)}")
    if t.type == "schedule":
        if t.at:
            return f"на часах {t.at}"
        return f"каждые {_dur(t.every or 0)}"
    return "житель нажимает кнопку сценария"


def condition_text(c: Condition, cat: Catalog) -> str:
    return (f"у «{cat.title(c.instance)}» {_sig(cat, c.instance, c.signal)} "
            f"{COND_OP[c.op]}{cat.fmt(c.instance, c.signal, c.value)}")


def action_text(a: Action, cat: Catalog) -> str:
    if a.type == "wait":
        return f"подождать {_dur(a.seconds)}"
    if a.type == "notify":
        txt = f"уведомить {TO_TEXT[a.to]} ({SEVERITY_TEXT[a.severity]}): «{a.text}»"
    else:
        s = cat.signal(a.instance, a.signal)
        if s and s.get("type") == "button":
            txt = f"«{cat.title(a.instance)}»: нажать «{s['title']}»"
        else:
            txt = f"«{cat.title(a.instance)}»: {_sig(cat, a.instance, a.signal)} → {cat.fmt(a.instance, a.signal, a.value)}"
            if a.hold:
                txt += f" на {_dur(a.hold)}, потом вернуть"
    if a.delay:
        txt = f"через {_dur(a.delay)} " + txt
    return txt


def _dur(sec: float) -> str:
    sec = int(sec)
    if sec % 3600 == 0 and sec >= 3600:
        return f"{sec // 3600} ч"
    if sec % 60 == 0 and sec >= 60:
        return f"{sec // 60} мин"
    return f"{sec} с"


# ------------------------------------------------------------------ конфликты между сценариями
def conflicts(items: List[Scenario], cat: Optional[Catalog] = None) -> List[dict]:
    """Два включённых сценария командуют одному сигналу разные значения от одного триггера."""
    cat = cat or Catalog.from_hub()
    out = []

    def key(t: Trigger):
        if t.type == "event":
            return ("event", t.instance, t.event)
        if t.type == "value":
            return ("value", t.instance, t.signal, t.op, str(t.value))
        return (t.type, t.at, t.every)

    on = [s for s in items if s.enabled]
    for i, a in enumerate(on):
        for b in on[i + 1:]:
            same_trigger = {key(t) for t in a.triggers} & {key(t) for t in b.triggers}
            if not same_trigger:
                continue
            ca = {(x.instance, x.signal): x.value for x in a.actions if x.type == "command"}
            for x in b.actions:
                k = (x.instance, x.signal)
                if x.type == "command" and k in ca and str(ca[k]) != str(x.value):
                    s = cat.signal(*k)
                    out.append({
                        "scenarios": [a.id, b.id],
                        "message": f"«{a.title}» и «{b.title}» срабатывают одновременно и ставят "
                                   f"«{s['title'] if s else k[1]}» у «{cat.title(k[0])}» в разные значения "
                                   f"({cat.fmt(*k, ca[k])} и {cat.fmt(*k, x.value)})",
                    })
    return out


# ------------------------------------------------------------------ экспорт в Ujin autoscripts
_SIMPLE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*==\s*(-?\d+(?:\.\d+)?)\s*$")


def to_ujin(sc: Scenario, cat: Optional[Catalog] = None, cls: str = "integrations_devices") -> Dict[str, Any]:
    """Перевод в autoscripts/edit (SCENARIOS.md §1): condition + set_signal по serialnumber стенда.

    Что платформа не умеет (уведомления, паузы, условия «И если», не привязанные к стенду
    устройства), честно перечисляется в `skipped` — это исполняет движок R Studio.
    """
    from .emulation import hub
    cat = cat or Catalog.from_hub()
    skipped: List[str] = []
    conds: List[str] = []

    def sn(iid: str) -> str:
        return str((cat.inst.get(iid, {}).get("ujin") or {}).get("sn") or "")

    for t in sc.triggers:
        if t.type == "value" and t.op == "==":
            if sn(t.instance):
                conds.append(f"when:device-{sn(t.instance)}:{cls}_{t.signal}={_num(t.value)}")
            else:
                skipped.append(f"триггер «{trigger_text(t, cat)}»: устройство не привязано к стенду")
        elif t.type == "event":
            inst = hub().instances.get(t.instance)
            ev = next((e for e in inst.device.spec.events if e.name == t.event), None) if inst and inst.device else None
            m = _SIMPLE.match(ev.when) if ev else None
            if m and sn(t.instance):
                conds.append(f"when:device-{sn(t.instance)}:{cls}_{m.group(1)}={_num(m.group(2))}")
            elif not sn(t.instance):
                skipped.append(f"триггер «{trigger_text(t, cat)}»: устройство не привязано к стенду")
            else:
                skipped.append(f"триггер «{trigger_text(t, cat)}»: условие события сложнее «сигнал = значение»")
        else:
            skipped.append(f"триггер «{trigger_text(t, cat)}»: на платформе только «сигнал = значение»")
    if sc.conditions:
        skipped.append("условия «И если» — проверяет движок R Studio")

    sets: List[str] = []
    for a in sc.actions:
        if a.type != "command":
            skipped.append(f"«{action_text(a, cat)}» — выполняет движок R Studio")
            continue
        if not sn(a.instance):
            skipped.append(f"«{action_text(a, cat)}»: устройство не привязано к стенду")
            continue
        s = cat.signal(a.instance, a.signal)
        val = 1 if s and s.get("type") == "button" else a.value
        item = f"device-{sn(a.instance)}:{cls}_{a.signal}:{_num(val)}"
        if a.hold:
            item += f":{int(a.hold)}"
        if a.delay:
            skipped.append(f"задержка {int(a.delay)} с у «{action_text(a, cat)}» — платформа выполнит сразу")
        sets.append(item)

    requests = [{"method": "POST", "url": "/api/autoscripts/edit/",
                 "params": {"token": "<ust резидента>", "id": 0, "scenario_type": "trigger",
                            "condition": c, "set_signal": s, "title": f"{sc.title}"[:60]}}
                for c in conds for s in sets]
    return {"exportable": bool(requests), "conditions": conds, "set_signals": sets,
            "requests": requests, "skipped": skipped}


def _num(v: Any) -> str:
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(v)
