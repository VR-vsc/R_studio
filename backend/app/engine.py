"""Блок 4 — исполнение сценариев.

Движок слушает хаб эмуляции (события устройств, изменения значений, такты), запускает
подходящие сценарии, проверяет условия и выполняет действия во времени модели:
сразу, «через N с», «вернуть через N с», после паузы. Каждый запуск оставляет трассу —
что сработало, почему, что сделано и когда. Уведомления складываются в ленту.

Тот же движок работает в песочнице (`test_scenario`): копия квартиры, план воздействий,
прогон N секунд мгновенно — и вердикт «сработал / не сработал / что не так».
"""
from __future__ import annotations

import copy
import json
import os
import re
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from . import storage
from .emulation import EmulationError, Hub, hub
from .scenarios import (Catalog, Scenario, action_text, analyze, condition_text,
                        trigger_text)

MAX_RUNS_PER_SECOND = 20  # защита от зацикливания сценариев друг через друга
_OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}


def _num(v: Any) -> Any:
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def compare(actual: Any, op: str, expected: Any) -> bool:
    a, b = _num(actual), _num(expected)
    try:
        return bool(_OPS[op](a, b))
    except TypeError:
        return False


class Engine:
    def __init__(self, h: Hub, scenarios: Optional[List[Scenario]] = None, live: bool = True):
        self.hub = h
        self.live = live
        self.scenarios: Dict[str, Scenario] = {}
        self.runs: Deque[dict] = deque(maxlen=150)
        self.notifications: Deque[dict] = deque(maxlen=150)
        self._queue: List[Tuple[float, int, dict]] = []      # (due_t, seq, task)
        self._seq = 0
        self._run_seq = 0
        self._edge: Dict[Tuple[str, int], bool] = {}          # состояние value-триггеров
        self._last: Dict[str, float] = {}                     # cooldown
        self._burst: Tuple[int, int] = (-1, 0)                # (t, запусков в эту секунду)
        self._pending: Deque[Tuple[str, dict]] = deque()
        self._busy = False
        self.errors: List[str] = []
        h.add_hook(self._on_hub)
        if scenarios is not None:
            self.set_scenarios(scenarios)
        else:
            self.reload()

    # ------------------------------------------------------------------ сценарии
    def reload(self) -> None:
        """Перечитать включённые и корректные сценарии из библиотеки."""
        cat = self._catalog()
        items = []
        self.errors = []
        for doc in storage.scenarios().all():
            if not doc.get("enabled", True):
                continue
            sc, issues = analyze(doc, cat)
            if sc is None:
                self.errors.append(f"«{doc.get('title', doc.get('id'))}» не запущен: есть ошибки")
                continue
            items.append(sc)
        self.set_scenarios(items)

    def set_scenarios(self, items: List[Scenario]) -> None:
        self.scenarios = {s.id: s for s in items if s.enabled}
        self._edge = {}
        for sc in self.scenarios.values():  # исходное состояние — не запуск
            for i, t in enumerate(sc.triggers):
                if t.type == "value":
                    self._edge[(sc.id, i)] = self._value_true(t.instance, t.signal, t.op, t.value)

    def _catalog(self) -> Catalog:
        return Catalog([i.describe() for i in self.hub.instances.values()])

    # ------------------------------------------------------------------ вход от хаба
    def _on_hub(self, kind: str, payload: dict) -> None:
        if kind == "snapshot":  # квартиру пересобрали — пересчитать исходные состояния триггеров
            self.set_scenarios(list(self.scenarios.values()))
            return
        if kind not in ("event", "values", "tick"):
            return
        self._pending.append((kind, payload))
        if self._busy:
            return  # действие сценария вызвало новое событие — обработаем после текущего
        self._busy = True
        try:
            while self._pending:
                k, p = self._pending.popleft()
                if k == "event":
                    self._on_event(p)
                elif k == "values":
                    self._on_values(p)
                else:
                    self._on_tick()
        finally:
            self._busy = False

    def _on_event(self, ev: dict) -> None:
        for sc in list(self.scenarios.values()):
            for t in sc.triggers:
                if t.type == "event" and t.instance == ev["instance"] and t.event == ev["event"]:
                    self.start(sc, trigger_text(t, self._catalog()))
                    break

    def _on_values(self, p: dict) -> None:
        changed = set(p.get("changes", {}))
        fire = []
        # сначала фиксируем переходы по ОДНОМУ снимку значений, потом запускаем —
        # иначе действия первого сценария «съедят» переход для второго
        for sc in list(self.scenarios.values()):
            for i, t in enumerate(sc.triggers):
                if t.type != "value" or t.instance not in changed:
                    continue
                now = self._value_true(t.instance, t.signal, t.op, t.value)
                was = self._edge.get((sc.id, i), False)
                self._edge[(sc.id, i)] = now
                if now and not was:
                    fire.append((sc, t))
                    break
        for sc, t in fire:
            self.start(sc, trigger_text(t, self._catalog()))

    def _on_tick(self) -> None:
        t = self.hub.t
        while self._queue and self._queue[0][0] <= t:
            _, _, task = self._queue.pop(0)
            self._execute(task)
        tod = self.hub.time_of_day()
        for sc in list(self.scenarios.values()):
            for trg in sc.triggers:
                if trg.type != "schedule":
                    continue
                if trg.at:
                    hh, mm = map(int, trg.at.split(":"))
                    if tod == hh * 3600 + mm * 60:
                        self.start(sc, trigger_text(trg, self._catalog()))
                elif trg.every and t > 0 and t % trg.every == 0:
                    self.start(sc, trigger_text(trg, self._catalog()))

    # ------------------------------------------------------------------ значения
    def value(self, iid: str, signal: str) -> Any:
        inst = self.hub.instances.get(iid)
        if inst is None or inst.device is None or signal not in inst.device.signals:
            return None
        return inst.device.signals[signal].value

    def _value_true(self, iid: str, signal: str, op: str, expected: Any) -> bool:
        v = self.value(iid, signal)
        return v is not None and compare(v, op, expected)

    # ------------------------------------------------------------------ запуск
    def start(self, sc: Scenario, reason: str, force: bool = False) -> Optional[dict]:
        t = self.hub.t
        cat = self._catalog()
        run = {"id": 0, "scenario": sc.id, "title": sc.title, "t": t, "reason": reason,
               "conditions": [], "steps": [], "status": "running", "note": ""}
        # защита от «пинг-понга» сценариев
        bt, bn = self._burst
        bn = bn + 1 if bt == t else 1
        self._burst = (t, bn)
        if bn > MAX_RUNS_PER_SECOND:
            if bn == MAX_RUNS_PER_SECOND + 1:
                self.hub.log("engine", f"защита от зацикливания: больше {MAX_RUNS_PER_SECOND} запусков за секунду, "
                                       f"«{sc.title}» остановлен")
            return None
        if not force and sc.cooldown and sc.id in self._last and t - self._last[sc.id] < sc.cooldown:
            return None  # пауза между запусками — молча, чтобы не засорять ленту
        # условия
        results = []
        for c in sc.conditions:
            actual = self.value(c.instance, c.signal)
            ok = actual is not None and compare(actual, c.op, c.value)
            results.append({"text": condition_text(c, cat), "ok": ok,
                            "actual": cat.fmt(c.instance, c.signal, actual)})
        run["conditions"] = results
        passed = (all(r["ok"] for r in results) if sc.match == "all" else any(r["ok"] for r in results)) \
            if results else True
        self._run_seq += 1
        run["id"] = self._run_seq
        if not passed:
            run["status"] = "skipped"
            run["note"] = "условия не выполнены"
            self._publish(run)
            return run
        self._last[sc.id] = t
        offset = 0.0
        for i, a in enumerate(sc.actions):
            if a.type == "wait":
                run["steps"].append({"i": i, "t": t + offset, "text": action_text(a, cat), "status": "done"})
                offset += a.seconds
                continue
            due = t + offset + (a.delay or 0)
            step = {"i": i, "t": due, "text": action_text(a, cat), "status": "waiting"}
            run["steps"].append(step)
            task = {"run": run, "step": step, "action": a}
            if due <= t:
                self._execute(task, publish=False, finish=False)
            else:
                self._push(due, task)
        self._finish_if_done(run)
        self.runs.append(run)
        self._publish(run)
        return run

    def _push(self, due: float, task: dict) -> None:
        self._seq += 1
        self._queue.append((due, self._seq, task))
        self._queue.sort(key=lambda x: (x[0], x[1]))

    def _execute(self, task: dict, publish: bool = True, finish: bool = True) -> None:
        run, step, a = task["run"], task["step"], task.get("action")
        try:
            if task.get("revert"):
                self.hub.act(task["instance"], task["signal"], task["value"], f"сценарий «{run['title']}»")
                step["status"] = "done"
            elif a.type == "notify":
                note = {"id": len(self.notifications) + 1, "t": self.hub.t, "scenario": run["scenario"],
                        "title": run["title"], "text": a.text, "severity": a.severity, "to": a.to}
                self.notifications.append(note)
                self.hub.broadcast("notify", note)
                step["status"] = "done"
            elif a.type == "command":
                inst = self.hub.get(a.instance)
                spec = inst.device.specs[a.signal] if inst.device else None
                before = self.value(a.instance, a.signal)
                value = 1 if spec is not None and spec.type == "button" else a.value
                self.hub.act(a.instance, a.signal, value, f"сценарий «{run['title']}»")
                step["status"] = "done"
                if a.hold and spec is not None and spec.type != "button":
                    back = {"i": step["i"], "t": self.hub.t + a.hold, "status": "waiting",
                            "text": f"«{inst.describe()['title']}»: вернуть «{spec.title.lower()}» как было"}
                    run["steps"].append(back)
                    self._push(self.hub.t + a.hold, {"run": run, "step": back, "revert": True,
                                                     "instance": a.instance, "signal": a.signal, "value": before})
        except (EmulationError, KeyError) as exc:
            step["status"] = "failed"
            step["error"] = str(exc)
        if finish:
            self._finish_if_done(run)
        if publish:
            self._publish(run)

    @staticmethod
    def _finish_if_done(run: dict) -> None:
        if run["status"] == "running" and all(s["status"] != "waiting" for s in run["steps"]):
            run["status"] = "failed" if any(s["status"] == "failed" for s in run["steps"]) else "done"

    def _publish(self, run: dict) -> None:
        if run["status"] == "skipped" and run not in self.runs:
            self.runs.append(run)
        self.hub.broadcast("run", copy.deepcopy(run))

    def run_now(self, sid: str) -> dict:
        """Кнопка «Запустить сейчас»: условия проверяются, пауза между запусками — нет."""
        sc = self.scenarios.get(sid)
        if sc is None:
            doc = storage.scenarios().get(sid) if storage.scenarios().exists(sid) else None
            sc, _ = analyze(doc, self._catalog()) if doc else (None, [])
            if sc is None:
                raise EmulationError("сценарий не найден или в нём есть ошибки")
        run = self.start(sc, "запуск вручную", force=True)
        return run or {}

    def clear(self) -> None:
        """Сброс квартиры: отложенные действия и история запусков больше не актуальны."""
        self._queue.clear()
        self.runs.clear()
        self.notifications.clear()
        self._last.clear()
        self.set_scenarios(list(self.scenarios.values()))

    def state(self) -> dict:
        return {"scenarios": sorted(self.scenarios), "runs": list(self.runs)[-50:],
                "notifications": list(self.notifications)[-50:], "errors": self.errors,
                "queued": len(self._queue)}


# ====================================================================== песочница
_TPL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rdl", "templates")
_SIMPLE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*==\s*(-?\d+(?:\.\d+)?)\s*$")


def _stimulus(h: Hub, iid: str, event: str) -> List[dict]:
    """Как вызвать событие: stimulus из RDL → из встроенного шаблона → простое «сигнал == v»."""
    inst = h.instances.get(iid)
    if not inst or not inst.device:
        return []
    ev = next((e for e in inst.device.spec.events if e.name == event), None)
    if ev is None:
        return []
    if ev.stimulus:
        return [{"instance": iid, "signal": s.signal, "value": s.value} for s in ev.stimulus]
    tpl = os.path.join(_TPL_DIR, f"{inst.cfg['device_id']}.json")
    if os.path.exists(tpl):
        with open(tpl, encoding="utf-8") as fh:
            for e in json.load(fh).get("events", []):
                if e["name"] == event and e.get("stimulus"):
                    return [{"instance": iid, "signal": s["signal"], "value": s["value"]} for s in e["stimulus"]]
    m = _SIMPLE.match(ev.when)
    if m:
        return [{"instance": iid, "signal": m.group(1), "value": float(m.group(2)), "force": True}]
    return []


def _satisfy(op: str, value: Any, options: Optional[dict]) -> Any:
    v = _num(value)
    if op in ("==", ">=", "<="):
        return v
    if op == ">":
        return v + max(1, abs(v) * 0.05) if isinstance(v, float) else v
    if op == "<":
        return v - max(1, abs(v) * 0.05) if isinstance(v, float) else v
    if options:  # «!=» — любой другой вариант
        for k in options:
            if float(k) != v:
                return float(k)
    return v + 1 if isinstance(v, float) else v


def auto_plan(sc: Scenario, h: Hub) -> Tuple[List[dict], List[str]]:
    """План проверки: подготовить условия, затем вызвать первую причину сценария."""
    plan: List[dict] = []
    notes: List[str] = []
    for c in sc.conditions:
        inst = h.instances.get(c.instance)
        spec = inst.device.specs.get(c.signal) if inst and inst.device else None
        if spec is None:
            continue
        plan.append({"at": 1, "instance": c.instance, "signal": c.signal,
                     "value": _satisfy(c.op, c.value, spec.options), "why": "подготовить условие",
                     "force": spec.group == "property"})
    t = sc.triggers[0]
    if t.type == "event":
        st = _stimulus(h, t.instance, t.event)
        if not st:
            notes.append("Не знаю, как вызвать это событие автоматически — добавьте устройству «стимул» "
                         "события в конструкторе.")
        for s in st:
            plan.append({"at": 3, "why": "вызвать причину", **s})
    elif t.type == "value":
        inst = h.instances.get(t.instance)
        spec = inst.device.specs.get(t.signal) if inst and inst.device else None
        if spec is not None:
            cur = inst.device.signals[t.signal].value
            if compare(cur, t.op, t.value):  # уже выполнено — сначала «снять», иначе не будет перехода
                plan.append({"at": 2, "instance": t.instance, "signal": t.signal,
                             "value": _satisfy("!=", t.value, spec.options), "why": "снять причину, чтобы был переход",
                             "force": spec.group == "property"})
            plan.append({"at": 3, "instance": t.instance, "signal": t.signal,
                         "value": _satisfy(t.op, t.value, spec.options), "why": "вызвать причину",
                         "force": spec.group == "property"})
    elif t.type == "manual":
        plan.append({"at": 3, "manual": True, "why": "нажать кнопку сценария"})
    elif t.type == "schedule":
        notes.append("Часы песочницы переведены так, чтобы время сценария наступило на 3-й секунде.")
    return plan, notes


def test_scenario(doc: Any, seconds: Optional[int] = None, plan: Optional[List[dict]] = None,
                  with_others: bool = False) -> dict:
    """Проверить сценарий на копии квартиры — мгновенно, без влияния на живые эмуляторы."""
    live = hub()
    cat = Catalog([i.describe() for i in live.instances.values()])
    sc, issues = analyze(doc, cat)
    if sc is None:
        return {"ok": False, "issues": issues, "verdict": {"status": "error", "message": "в сценарии есть ошибки"}}
    sc = sc.model_copy(update={"enabled": True})
    sb = Hub(persist=False)
    sb.running = False
    sb.t = 0
    others: List[Scenario] = []
    if with_others:
        for d in storage.scenarios().all():
            o, _ = analyze(d, cat)
            if o and o.enabled and o.id != sc.id:
                others.append(o)
    eng = Engine(sb, [sc] + others, live=False)
    auto, notes = auto_plan(sc, sb)
    plan = plan if plan is not None else auto
    trig = sc.triggers[0]
    if trig.type == "schedule":
        if trig.at:
            hh, mm = map(int, trig.at.split(":"))
            sb.day_start = (hh * 3600 + mm * 60 - 3) % 86400
        elif trig.every:
            sb.t = trig.every - 3
    t0 = sb.t
    horizon = 0.0
    for a in sc.actions:
        horizon += a.seconds if a.type == "wait" else 0
    horizon += max([(a.delay or 0) + (a.hold or 0) for a in sc.actions] + [0])
    seconds = int(seconds or min(600, max(20, horizon + 12)))

    watch: List[Tuple[str, str]] = []
    def add_watch(i: str, s: str):
        if i and s and (i, s) not in watch and i in sb.instances:
            watch.append((i, s))
    for t in sc.triggers:
        if t.type == "value":
            add_watch(t.instance, t.signal)
    for a in sc.actions:
        if a.type == "command":
            add_watch(a.instance, a.signal)
    for p in plan:
        if not p.get("manual"):
            add_watch(p["instance"], p["signal"])
    series = {f"{i}.{s}": [] for i, s in watch}
    times: List[int] = []
    applied: List[dict] = []
    events: List[dict] = []
    sb.add_hook(lambda k, p: events.append(p) if k == "event" else None)

    todo = sorted(plan, key=lambda p: p.get("at", 0))
    k = 0
    for _ in range(seconds + 1):
        rel = sb.t - t0
        while k < len(todo) and todo[k].get("at", 0) <= rel:
            p = todo[k]
            k += 1
            try:
                if p.get("manual"):
                    eng.run_now(sc.id)
                elif p.get("force"):
                    sb.force(p["instance"], p["signal"], p["value"])
                else:
                    sb.act(p["instance"], p["signal"], p["value"], "проверка")
                applied.append({**p, "t": rel, "ok": True})
            except (EmulationError, KeyError) as exc:
                applied.append({**p, "t": rel, "ok": False, "error": str(exc)})
        times.append(rel)
        for i, s in watch:
            series[f"{i}.{s}"].append(sb.instances[i].device.signals[s].value)
        if rel >= seconds:
            break
        sb.step(1)

    my_runs = [r for r in eng.runs if r["scenario"] == sc.id]
    for r in eng.runs:  # время в трассе — от начала проверки
        r["t"] -= t0
        for s in r["steps"]:
            s["t"] -= t0
    fired = [r for r in my_runs if r["status"] != "skipped"]
    if fired:
        r = fired[0]
        done = sum(1 for s in r["steps"] if s["status"] == "done")
        failed = [s for s in r["steps"] if s["status"] == "failed"]
        if failed:
            verdict = {"status": "failed", "message": f"Сценарий запустился, но {len(failed)} действ. не выполнено: "
                                                     + "; ".join(s.get("error", "") for s in failed)}
        elif r["status"] == "running":
            verdict = {"status": "partial", "message": "Сценарий запустился, но не все действия успели выполниться — "
                                                       "увеличьте длительность проверки."}
        else:
            verdict = {"status": "ok", "message": f"Сценарий сработал на {r['t']:g}-й секунде: выполнено "
                                                 f"{done} из {len(r['steps'])} шагов."}
    elif my_runs:
        verdict = {"status": "skipped", "message": "Причина наступила, но условия «И если» не выполнились."}
    else:
        verdict = {"status": "silent", "message": "Сценарий не запустился: причина не наступила за время проверки."}
    meta = {}
    for i, s in watch:
        spec = sb.instances[i].device.specs[s]
        meta[f"{i}.{s}"] = {"instance": sb.instances[i].describe()["title"],
                            "signal": spec.model_dump(exclude_none=True)}
    return {"ok": True, "issues": issues, "verdict": verdict, "plan": plan, "applied": applied,
            "notes": notes, "seconds": seconds, "t": times, "series": series, "meta": meta,
            "runs": list(eng.runs), "notifications": [dict(n, t=n["t"] - t0) for n in eng.notifications],
            "events": [dict(e, t=e["t"] - t0) for e in events]}


_engine: Optional[Engine] = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine(hub())
    return _engine
