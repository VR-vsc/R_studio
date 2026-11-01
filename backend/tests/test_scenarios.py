"""Блок 3: язык сценариев — проверка по квартире, текст, конфликты, экспорт в Ujin, API."""
import copy
import os
import tempfile

os.environ.setdefault("RSTUDIO_DATA", tempfile.mkdtemp(prefix="rstudio-test-"))

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402,F401
from app import storage  # noqa: E402
from app.emulation import hub  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.scenarios import Catalog, analyze, conflicts, describe, to_ujin  # noqa: E402


def cat():
    hub().reset_to_seed()
    return Catalog.from_hub()


def seed(sid):
    return copy.deepcopy(storage.scenarios().template(sid))


def test_all_seed_scenarios_valid():
    c = cat()
    ids = storage.scenarios().ids()
    assert len(ids) >= 7
    for sid in ids:
        sc, issues = analyze(storage.scenarios().get(sid), c)
        assert sc is not None, (sid, issues)


def test_semantic_errors_are_specific():
    c = cat()
    doc = seed("leak_protect")
    doc["triggers"][0]["event"] = "boom"
    doc["actions"][0] = {"type": "command", "instance": "bath_leak", "signal": "leak", "value": 1}
    doc["actions"][1] = {"type": "command", "instance": "ghost", "signal": "x", "value": 1}
    doc["actions"].append({"type": "command", "instance": "bath_valve", "signal": "valve", "value": 7})
    doc["actions"].append({"type": "notify", "text": " "})
    sc, issues = analyze(doc, c)
    assert sc is None
    msg = {i["path"]: i["message"] for i in issues}
    assert "нет события «boom»" in msg["triggers[0].event"]
    assert "показание датчика" in msg["actions[0].signal"]
    assert "нет устройства «ghost»" in msg["actions[1].instance"]
    assert "такого варианта нет" in msg["actions[3].value"]
    assert "текст уведомления" in msg["actions[4].text"]


def test_loop_warning_and_structure_errors():
    c = cat()
    doc = {"id": "loop", "title": "Петля",
           "triggers": [{"type": "value", "instance": "living_light", "signal": "lamp", "op": "==", "value": 1}],
           "actions": [{"type": "command", "instance": "living_light", "signal": "lamp", "value": 0}]}
    sc, issues = analyze(doc, c)
    assert sc is not None and any("цикл" in i["message"] for i in issues)
    sc, issues = analyze({"id": "Bad-Id", "title": "", "triggers": [], "actions": []}, c)
    assert sc is None and {i["path"] for i in issues} >= {"id", "title", "triggers", "actions"}


def test_human_sentence():
    c = cat()
    sc, _ = analyze(seed("leak_protect"), c)
    text = describe(sc, c)["sentence"]
    assert text.startswith("Когда «Протечка в ванной» сообщает «Обнаружена протечка», то ")
    assert "«Кран на вводе воды»: кран → «закрыт»" in text
    assert "на 1 мин, потом вернуть" in text
    sc, _ = analyze(seed("fresh_air"), c)
    assert "CO₂ в комнате превышает 1200 ppm" in describe(sc, c)["sentence"]


def test_conflicts():
    c = cat()
    a, _ = analyze(seed("window_heating"), c)
    b_doc = seed("window_heating")
    b_doc.update(id="window_eco", title="Окно — эко")
    b_doc["actions"] = [{"type": "command", "instance": "living_thermo", "signal": "mode", "value": 2}]
    b, _ = analyze(b_doc, c)
    found = conflicts([a, b], c)
    assert len(found) == 1 and set(found[0]["scenarios"]) == {"window_heating", "window_eco"}
    b.enabled = False
    assert conflicts([a, b], c) == []


def test_ujin_export():
    c = cat()
    sc, _ = analyze(seed("window_heating"), c)
    u = to_ujin(sc, c)
    assert u["conditions"] == ["when:device-17048877610014040:integrations_devices_window_open=1"]
    assert u["set_signals"] == ["device-17048877610014040:integrations_devices_mode:0"]
    assert u["exportable"] and u["requests"][0]["params"]["scenario_type"] == "trigger"
    assert any("И если" in x for x in u["skipped"])
    sc, _ = analyze(seed("leak_protect"), c)  # событие leak == 1 → условие платформы
    u = to_ujin(sc, c)
    assert u["conditions"] == ["when:device-17048697650011558:integrations_devices_leak=1"]
    assert not u["exportable"]  # кран и сирена не на стенде — исполняет R Studio
    sc, _ = analyze(seed("overload_guard"), c)
    assert to_ujin(sc, c)["set_signals"] == ["device-17036889610009538:integrations_devices_load_relay:0:30"]


def test_api():
    with TestClient(fastapi_app) as cl:
        cl.post("/api/emu/reset")
        cat_ = cl.get("/api/scenarios/catalog").json()
        assert len(cat_["instances"]) == 9 and cat_["instances"][0]["signals"]
        lst = cl.get("/api/scenarios").json()
        assert all(i["valid"] for i in lst["items"]) and lst["conflicts"] == []
        got = cl.get("/api/scenarios/leak_protect").json()
        assert got["ok"] and got["text"]["sentence"] and "ujin" in got
        new = {"id": "night_light", "title": "Ночник",
               "triggers": [{"type": "schedule", "at": "23:00"}],
               "actions": [{"type": "command", "instance": "living_light", "signal": "brightness", "value": 10}]}
        assert cl.post("/api/scenarios", json=new).json()["ok"]
        assert cl.post("/api/scenarios", json=new).status_code == 409
        bad = dict(new, actions=[{"type": "command", "instance": "living_light", "signal": "power_w", "value": 1}])
        assert cl.put("/api/scenarios/night_light", json=bad).status_code == 422
        assert cl.post("/api/scenarios/night_light/enabled", json={"enabled": False}).json()["enabled"] is False
        assert cl.delete("/api/scenarios/night_light").json()["ok"]
        r = cl.post("/api/scenarios/check", json=new).json()
        assert r["ok"] and r["text"]["when"] == ["на часах 23:00"]
