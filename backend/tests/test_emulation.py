"""Блок 2: эмуляция квартиры — такты, команды, окружение, события, Ujin-приём, WebSocket."""
import json
import os
import tempfile

os.environ.setdefault("RSTUDIO_DATA", tempfile.mkdtemp(prefix="rstudio-test-"))

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402,F401
from app.emulation import hub  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


def fresh():
    h = hub()
    h.reset_to_seed()
    h.set_clock(running=False, speed=1)
    return h


def test_seed_apartment_has_team_devices():
    h = fresh()
    snap = h.snapshot()
    ids = {i["id"] for i in snap["instances"]}
    assert {"bath_leak", "bath_valve", "hall_siren", "yard_barrier", "shield_meter"} <= ids
    bound = {i["ujin"]["ext"] for i in snap["instances"] if i["ujin"]}
    assert bound == {"rtut_leak_01", "rtut_thermostat_01", "rtut_light_01", "rtut_counter_01", "rtut_barrier_01"}
    assert all(not i["error"] for i in snap["instances"])
    # настройка из конфига квартиры применена
    siren = next(i for i in snap["instances"] if i["id"] == "hall_siren")
    assert siren["values"]["auto_off"] == 60


def test_environment_drives_events_and_hooks():
    h = fresh()
    seen = []
    h.add_hook(lambda kind, p: seen.append((kind, p)))
    h.act("bath_leak", "wet", 1)
    h.step(4)
    assert h.get("bath_leak").device.signals["leak"].value == 1
    evs = [e for e in h.events if e["event"] == "leak_detected"]
    assert evs and evs[-1]["room"] == "Ванная" and evs[-1]["severity"] == "critical"
    assert any(k == "event" and p["event"] == "leak_detected" for k, p in seen)
    assert any(k == "values" and "bath_leak" in p["changes"] for k, p in seen)


def test_commands_settings_and_errors():
    h = fresh()
    h.act("bath_valve", "valve", 0)
    h.step(5)
    assert h.get("bath_valve").device.signals["position"].value == 0
    h.act("living_thermo", "hysteresis", 1.5)  # настройка запоминается в конфиге
    assert h.get("living_thermo").cfg["settings"]["hysteresis"] == 1.5
    for bad in [("bath_leak", "leak", 1), ("bath_leak", "nope", 1), ("ghost", "x", 1)]:
        try:
            h.act(*bad)
            raise AssertionError(f"ожидали ошибку для {bad}")
        except ValueError:
            pass


def test_ujin_poll_format():
    h = fresh()
    r = h.recv("yard_barrier", {"recv": [{"command": "management", "id": "1", "open_cmd": 1}]})
    assert r["error"] == 0
    h.step(6)
    assert h.get("yard_barrier").device.signals["state"].value == 2


def test_reload_after_library_change_and_restart():
    h = fresh()
    h.act("bath_leak", "wet", 1)
    h.step(5)
    h.restart("bath_leak")
    assert h.get("bath_leak").device.signals["leak"].value == 0
    h.reload_device("leak_sensor")
    assert h.get("bath_leak").device is not None


def test_api_and_websocket():
    with TestClient(fastapi_app) as c:
        c.post("/api/emu/reset")
        c.post("/api/emu/clock", json={"running": False})
        assert c.post("/api/emu/clock", json={"speed": 7}).status_code == 400
        st = c.get("/api/emu/state").json()
        assert len(st["instances"]) == 9 and st["running"] is False
        with c.websocket_connect("/api/emu/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert c.post("/api/emu/instances/kitchen_smoke/act",
                          json={"signal": "smoke_density", "value": 90}).json()["ok"]
            c.post("/api/emu/step?n=5")
            got = set()
            for _ in range(40):
                m = ws.receive_json()
                got.add(m["type"])
                if m["type"] == "event" and m["event"] == "fire_alarm":
                    break
            assert "event" in got and "values" in got
        # Ujin-формат через HTTP
        data = json.dumps({"recv": [{"command": "management", "id": "1", "lamp": 1}]})
        assert c.get("/api/emu/instances/living_light/ujin", params={"data": data}).json()["error"] == 0
        # состав квартиры
        r = c.post("/api/emu/instances", json={"id": "kitchen_valve", "device_id": "water_valve",
                                               "title": "Кран на кухне", "room": "Кухня"})
        assert r.status_code == 200 and r.json()["room"] == "Кухня"
        assert c.post("/api/emu/instances", json={"id": "kitchen_valve", "device_id": "water_valve"}).status_code == 400
        assert c.patch("/api/emu/instances/kitchen_valve", json={"room": "Санузел"}).json()["room"] == "Санузел"
        # нельзя удалить из библиотеки устройство, которое стоит в квартире
        assert c.delete("/api/devices/water_valve").status_code == 409
        assert c.delete("/api/emu/instances/kitchen_valve").json()["ok"]
        c.post("/api/emu/reset")
