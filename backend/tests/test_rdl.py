"""Блок 1: язык RDL — выражения, проверка, рантайм, шаблоны, API."""
import glob
import json
import os
import tempfile

os.environ.setdefault("RSTUDIO_DATA", tempfile.mkdtemp(prefix="rstudio-test-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402,F401  (подключает emulators/ в sys.path)
from app.main import app as fastapi_app  # noqa: E402
from app.rdl import ExprError, analyze, build_device, compile_expr, simulate, ujin_declaration  # noqa: E402

TPL = os.path.join(os.path.dirname(__file__), "..", "app", "rdl", "templates")


def tpl(name):
    with open(os.path.join(TPL, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def run(name, seconds, commands=()):
    spec, issues = analyze(tpl(name))
    assert spec, issues
    return simulate(spec, seconds, 1, list(commands))


# ------------------------------------------------------------------ выражения
def test_expr_basic_and_c_style_ops():
    e = compile_expr("a > 1 && !b || c == 2")
    assert e({"a": 2, "b": 0, "c": 0}) == 1
    assert e({"a": 0, "b": 0, "c": 2}) == 1
    assert e({"a": 0, "b": 1, "c": 0}) == 0
    assert compile_expr("x != 3")({"x": 3}) == 0


def test_expr_ternary_funcs_div_zero():
    assert compile_expr("1 if t > 5 else 0")({"t": 6}) == 1
    assert compile_expr("clamp(x, 0, 10)")({"x": 50}) == 10
    assert compile_expr("x / 0")({"x": 5}) == 0


@pytest.mark.parametrize("bad", ["__import__('os')", "a.b", "a[0]", "lambda: 1", "open('x')", "2 ** 100"])
def test_expr_rejects_unsafe(bad):
    with pytest.raises(ExprError):
        compile_expr(bad)({"a": 1})


def test_expr_unknown_name():
    with pytest.raises(ExprError, match="неизвестное имя: foo"):
        compile_expr("foo + 1", known={"bar"})


# ------------------------------------------------------------------ проверка
def test_all_templates_valid():
    files = glob.glob(os.path.join(TPL, "*.json"))
    assert len(files) >= 9
    for f in files:
        with open(f, encoding="utf-8") as fh:
            spec, issues = analyze(json.load(fh))
        assert spec is not None, (f, issues)
        assert not [i for i in issues if i["severity"] == "error"]


def test_validation_messages_are_human():
    doc = tpl("siren")
    doc["signals"][0]["name"] = "Siren-1"
    doc["signals"].append({"name": "volume", "title": "x", "group": "setting"})
    doc["behavior"][0]["do"][0]["to"] = "nonexistent + 1"
    spec, issues = analyze(doc)
    assert spec is None
    paths = {i["path"]: i["message"] for i in issues}
    assert "без дефисов" in paths["signals[0].name"]


def test_validation_semantic():
    doc = tpl("siren")
    doc["signals"].append({"name": "volume", "title": "дубль", "group": "setting"})
    doc["signals"].append({"name": "temp", "title": "t", "group": "property", "access": "rw"})
    doc["behavior"][0]["do"][0]["to"] = "nonexistent + 1"
    spec, issues = analyze(doc)
    assert spec is None
    msgs = " | ".join(i["message"] for i in issues)
    assert "уже занято" in msgs
    assert "свойство только читается" in msgs
    assert "неизвестное имя: nonexistent" in msgs


# ------------------------------------------------------------------ физика
def test_leak_debounce_event_and_self_test():
    r = run("leak_sensor", 12, [{"at": 2, "signal": "wet", "value": 1},
                                {"at": 8, "signal": "wet", "value": 0}])
    leak = r["series"]["leak"]
    assert leak[2] == 0 and leak[3] == 0
    assert 1 in leak[3:6]
    assert leak[-1] == 0
    names = [e["event"] for e in r["events"]]
    assert "leak_detected" in names and "leak_cleared" in names
    r2 = run("leak_sensor", 6, [{"at": 1, "signal": "self_test", "value": 1}])
    assert max(r2["series"]["leak"]) == 1 and r2["series"]["leak"][-1] == 0


def test_valve_closes_gradually_and_flow_stops():
    r = run("water_valve", 8, [{"at": 1, "signal": "valve", "value": 0}])
    pos = r["series"]["position"]
    assert pos[1] == 100 and 0 < pos[2] < 100 and pos[-1] == 0
    assert r["series"]["flow"][-1] == 0
    tot = r["series"]["water_total"]
    assert all(b >= a for a, b in zip(tot, tot[1:]))


def test_siren_auto_off():
    doc = tpl("siren")
    doc["signals"][3]["default"] = 3
    spec, _ = analyze(doc)
    r = simulate(spec, 8, 1, [{"at": 1, "signal": "siren", "value": 1}])
    s = r["series"]["siren"]
    assert s[1:4] == [1, 1, 1] and s[-1] == 0


def test_thermostat_heats_and_releases():
    r = run("thermostat", 400)
    temps, heat = r["series"]["room_temp"], r["series"]["heating"]
    assert heat[1] == 1
    assert max(temps) >= 22.4
    assert 0 in heat[100:]
    assert any(e["event"] == "target_reached" for e in r["events"])


def test_ventilation_auto_speeds_up():
    r = run("ventilation", 300, [{"at": 1, "signal": "people", "value": 15}])
    assert max(r["series"]["fan_speed"]) >= 4
    assert any(e["event"] == "stuffy" for e in r["events"])
    r2 = run("ventilation", 5, [{"at": 1, "signal": "mode", "value": 0}])
    assert r2["series"]["fan_speed"][-1] == 0


def test_barrier_cycle_and_reverse():
    r = run("barrier", 25, [{"at": 1, "signal": "open_cmd", "value": 1}])
    st = r["series"]["state"]
    assert 2 in st and 3 in st and st[-1] == 0
    r2 = run("barrier", 20, [{"at": 1, "signal": "open_cmd", "value": 1},
                              {"at": 11, "signal": "obstacle", "value": 1},
                              {"at": 13, "signal": "obstacle", "value": 0}])
    assert any(e["event"] == "obstacle_reverse" for e in r2["events"])


def test_meter_monotonic_and_relay():
    r = run("power_meter", 10, [{"at": 3, "signal": "load_relay", "value": 0}])
    assert r["series"]["power_w"][-1] == 0
    tot = r["series"]["total_kwh"]
    assert all(b >= a for a, b in zip(tot, tot[1:]))


def test_light_motion_and_auto_off():
    doc = tpl("smart_light")
    doc["signals"][5]["default"] = 5
    spec, _ = analyze(doc)
    r = simulate(spec, 15, 1, [{"at": 1, "signal": "motion", "value": 1},
                               {"at": 3, "signal": "motion", "value": 0}])
    lamp = r["series"]["lamp"]
    assert lamp[2] == 1 and lamp[-1] == 0


def test_hold_and_after_actions():
    doc = {"id": "pulse", "title": "Импульс", "signals": [
        {"name": "out", "title": "Выход", "group": "capability", "type": "bool"},
        {"name": "level", "title": "Уровень", "group": "property"}],
        "behavior": [
            {"on": "command:out", "when": "value == 1", "do": [{"set": "out", "to": 1, "hold": 3}]},
            {"on": "start", "do": [{"set": "level", "to": 5, "after": 2}]},
            {"on": "tick", "when": "out", "do": [{"set": "level", "to": "level + 1"}]}]}
    spec, issues = analyze(doc)
    assert spec, issues
    r = simulate(spec, 8, 1, [{"at": 1, "signal": "out", "value": 1}])
    assert r["series"]["out"][1:4] == [1, 1, 1] and r["series"]["out"][-1] == 0


# ------------------------------------------------------------------ совместимость с Ujin
def test_compiled_device_is_ujin_compatible():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def update_signals(self, serial, model, batch):
            self.calls.append((serial, model, batch))

    cli = FakeClient()
    dev = build_device(tpl("leak_sensor"), serial="rtut_leak_01", client=cli)
    dev.announce()
    serial, model, batch = cli.calls[0]
    names = {b["signal"] for b in batch}
    assert serial == "rtut_leak_01" and model == "rs_leak_sensor"
    assert "leak" in names and "wet" not in names          # окружение не публикуется
    assert {b["value"] for b in batch if b["signal"] == "leak"} == {0.001}  # мина №1
    dev.handle_recv({"recv": [{"command": "management", "id": "1", "self_test": 1}]})
    dev.step(1)
    assert dev.signals["leak"].value == 1


def test_ujin_declaration():
    spec, _ = analyze(tpl("power_meter"))
    d = ujin_declaration(spec)
    names = {s["name"] for s in d["signals"]}
    assert "load_w" not in names and "fw" not in names
    meter = next(s for s in d["signals"] if s["name"] == "total_kwh")
    assert meter["control"] == "counter" and meter["full_name"] == "integrations_devices_total_kwh"
    relay = next(s for s in d["signals"] if s["name"] == "load_relay")
    assert relay["control"] == "switch" and relay["management"] == "rw"
    assert d["publish_example"]["body"]["data"][0]["c"] == "integrations_devices"


# ------------------------------------------------------------------ API
def test_api_flow():
    c = TestClient(fastapi_app)
    lst = c.get("/api/devices").json()
    assert len(lst) >= 9 and all(d["valid"] for d in lst)
    doc = c.get("/api/devices/water_valve").json()["device"]
    assert c.post("/api/rdl/validate", json=doc).json()["ok"]
    assert c.post("/api/rdl/compile", json=doc).json()["ujin"]["model"] == "rs_water_valve"
    sim = c.post("/api/rdl/simulate", json={"device": doc, "seconds": 6,
                                             "commands": [{"at": 1, "signal": "valve", "value": 0}]}).json()
    assert sim["series"]["position"][-1] == 0
    r = c.post("/api/devices/water_valve/clone", json={"new_id": "valve_kitchen", "title": "Кран на кухне"})
    assert r.status_code == 200
    bad = dict(doc, id="valve_kitchen", signals=[])
    assert c.put("/api/devices/valve_kitchen", json=bad).status_code == 422
    assert c.put("/api/devices/valve_kitchen?force=true", json=bad).status_code == 200
    assert c.delete("/api/devices/valve_kitchen").json()["ok"]
    assert c.get("/api/rdl/schema").json()["title"] == "DeviceSpec"
