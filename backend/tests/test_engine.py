"""Блок 4: исполнение сценариев — живой движок, песочница проверки, API."""
import os
import tempfile

os.environ.setdefault("RSTUDIO_DATA", tempfile.mkdtemp(prefix="rstudio-test-"))

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402,F401
from app import storage  # noqa: E402
from app.emulation import Hub  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.engine import test_scenario as run_test  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.scenarios import Catalog, analyze  # noqa: E402


def setup(*docs):
    h = Hub(persist=False)
    h.running = False
    cat = Catalog([i.describe() for i in h.instances.values()])
    items = []
    for d in docs:
        sc, issues = analyze(d, cat)
        assert sc, issues
        items.append(sc)
    return h, Engine(h, items, live=False)


def val(h, iid, sig):
    return h.instances[iid].device.signals[sig].value


def seed(sid):
    return storage.scenarios().template(sid)


def test_leak_protect_live():
    h, e = setup(seed("leak_protect"))
    h.act("bath_leak", "wet", 1)
    h.step(4)
    assert val(h, "bath_valve", "valve") == 0
    assert val(h, "hall_siren", "siren") == 1
    run = e.runs[-1]
    assert run["title"] == "Защита от протечки" and "Обнаружена протечка" in run["reason"]
    assert e.notifications[-1]["severity"] == "critical"
    h.step(61)  # hold 60 с → сирена вернулась
    assert val(h, "hall_siren", "siren") == 0
    assert e.runs[-1]["status"] == "done"
    h.step(5)
    assert val(h, "bath_valve", "position") == 0  # физика крана довела заслонку


def test_conditions_and_cooldown():
    h, e = setup(seed("window_heating"))
    h.act("living_thermo", "mode", 0)
    h.act("living_thermo", "window_open", 1)
    assert e.runs[-1]["status"] == "skipped" and e.runs[-1]["conditions"][0]["ok"] is False
    h.act("living_thermo", "window_open", 0)
    h.act("living_thermo", "mode", 1)
    h.act("living_thermo", "window_open", 1)
    assert e.runs[-1]["status"] == "done" and val(h, "living_thermo", "mode") == 0
    doc = dict(seed("guest_arrival"), cooldown=100)
    h2, e2 = setup(doc)
    e2.start(e2.scenarios["guest_arrival"], "тест")
    n = len(e2.runs)
    e2.start(e2.scenarios["guest_arrival"], "тест")
    assert len(e2.runs) == n  # пауза между запусками


def test_delay_wait_and_schedule():
    doc = {"id": "morning", "title": "Утро",
           "triggers": [{"type": "schedule", "at": "08:00"}],
           "actions": [{"type": "command", "instance": "living_light", "signal": "lamp", "value": 1},
                       {"type": "wait", "seconds": 5},
                       {"type": "command", "instance": "living_light", "signal": "brightness", "value": 30},
                       {"type": "notify", "text": "Доброе утро", "delay": 2}]}
    h, e = setup(doc)
    h.day_start = 8 * 3600 - 2  # 08:00 наступит на t=2
    h.step(2)
    assert val(h, "living_light", "lamp") == 1 and val(h, "living_light", "brightness") == 80
    h.step(5)
    assert val(h, "living_light", "brightness") == 30
    h.step(3)
    assert e.notifications[-1]["text"] == "Доброе утро" and e.runs[-1]["status"] == "done"


def test_loop_guard():
    a = {"id": "ping", "title": "Пинг", "triggers": [{"type": "value", "instance": "living_light", "signal": "lamp", "op": "==", "value": 1}],
         "actions": [{"type": "command", "instance": "living_light", "signal": "lamp", "value": 0}]}
    b = {"id": "pong", "title": "Понг", "triggers": [{"type": "value", "instance": "living_light", "signal": "lamp", "op": "==", "value": 0}],
         "actions": [{"type": "command", "instance": "living_light", "signal": "lamp", "value": 1}]}
    h, e = setup(a, b)
    h.act("living_light", "lamp", 1)  # не должно повиснуть
    assert len(e.runs) <= 21
    assert any("зацикливания" in l["text"] for l in h.logs)


def test_sandbox_all_demo_scenarios_pass():
    for sid in storage.scenarios().ids():
        r = run_test(storage.scenarios().get(sid))
        assert r["verdict"]["status"] == "ok", (sid, r["verdict"], r["plan"], r["notes"])
        assert r["series"] and r["runs"]


def test_sandbox_reports_problems():
    doc = dict(seed("window_heating"))
    plan = [{"at": 1, "instance": "living_thermo", "signal": "mode", "value": 0},
            {"at": 3, "instance": "living_thermo", "signal": "window_open", "value": 1}]
    assert run_test(doc, plan=plan)["verdict"]["status"] == "skipped"
    assert run_test(doc, plan=[])["verdict"]["status"] == "silent"
    bad = dict(doc, actions=[{"type": "command", "instance": "nope", "signal": "x", "value": 1}])
    assert run_test(bad)["verdict"]["status"] == "error"


def test_api_run_and_test():
    with TestClient(fastapi_app) as c:
        c.post("/api/emu/reset")
        c.post("/api/emu/clock", json={"running": False})
        r = c.post("/api/scenarios/guest_arrival/run").json()
        assert r["status"] == "running"  # свет включится через 10 с
        c.post("/api/emu/step?n=11")
        st = c.get("/api/scenarios/engine").json()
        assert st["runs"][-1]["status"] == "done" and "leak_protect" in st["scenarios"]
        t = c.post("/api/scenarios/test", json={"scenario": seed("fire_evacuation")}).json()
        assert t["verdict"]["status"] == "ok"
        assert any(n["severity"] == "critical" for n in t["notifications"])
        # выключенный сценарий движок не исполняет
        c.post("/api/scenarios/leak_protect/enabled", json={"enabled": False})
        assert "leak_protect" not in c.get("/api/scenarios/engine").json()["scenarios"]
        c.post("/api/scenarios/leak_protect/enabled", json={"enabled": True})
        c.post("/api/emu/reset")
