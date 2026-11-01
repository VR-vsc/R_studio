"""Блок 5: мост в Ujin OS против локального «стенда»-заглушки (контракт из стартового пакета)."""
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("RSTUDIO_DATA", tempfile.mkdtemp(prefix="rstudio-test-"))

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402,F401
from app import storage  # noqa: E402
from app.emulation import hub  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.ujin import UjinBridge, mask  # noqa: E402

GOOD = "ust-0000000-goodtokenforteststests"
ACCESS = {  # структура как в доступы.json, значения выдуманные
    "api_base": "{base}/api", "team_apartment": "2767",
    "residents": [{"login": "7000", "password": "x", "ust": GOOD, "apartment_id": "2767"}],
    "employee": {"login": "emp", "password": "pw", "app": "employee"},
    "devices": [
        {"family": "leak", "sn": "111", "ext": "t_leak_01", "publish_class": "integrations_devices"},
        {"family": "light", "sn": "222", "ext": "t_light_01", "publish_class": "integrations_devices"},
    ],
}


class Stand:
    """Минимальный стенд: принимает публикации, отдаёт карточки и одну task-команду."""

    def __init__(self):
        self.requests = []
        self.values = {}           # ext -> {full_name: value}
        self.ext_by_sn = {"111": "t_leak_01", "222": "t_light_01"}
        self.employee_only = False
        stand = self

        class H(BaseHTTPRequestHandler):
            def _reply(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                stand.requests.append(("GET", u.path, q, None, None))
                if q.get("token") != GOOD:
                    return self._reply({"error": 1, "message": "Ошибка авторизации"})
                if u.path == "/api/devices/difference/":
                    sn_by_ext = {e: sn for sn, e in stand.ext_by_sn.items()}
                    diff = [{"serialnumber": sn_by_ext[e], "signal": k, "value": str(v), "dt": 1}
                            for e, vals in stand.values.items() if e in sn_by_ext for k, v in vals.items()]
                    return self._reply({"error": 0, "data": {"difference": diff}})
                if u.path == "/api/bmsdevice/get-device-info/" and stand.employee_only and q.get("token") == GOOD:
                    return self._reply({"error": 1, "error_code": "Access denied",
                                         "message": "Метод может вызываться только от имени сотрудника УК"})
                if u.path == "/api/bmsdevice/get-device-info/":
                    ext = stand.ext_by_sn.get(q.get("serialnumber"))
                    sigs = [{"name": k, "value": v} for k, v in stand.values.get(ext, {}).items()]
                    if ext == "t_light_01":
                        sigs.append({"name": "integrations_devices_lamp", "value": 0,
                                     "signal_task_value": 1, "signal_task_dt": "1700000000"})
                    return self._reply({"error": 0, "data": {"signals": sigs}})
                if u.path == "/api/autoscripts/list/":
                    return self._reply({"error": 0, "data": []})
                self._reply({"error": 404}, 404)

            def do_POST(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                ctype = self.headers.get("Content-Type")
                stand.requests.append(("POST", u.path, q, raw, ctype))
                if u.path == "/api/import_device/group-update-device-signal/":
                    if ctype != "application/json":
                        return self._reply({"error": 1, "message": "Data is empty"})
                    if q.get("token") != GOOD or not q.get("apartment_id"):
                        return self._reply({"error": 1, "message": "Ошибка авторизации"})
                    for row in json.loads(raw)["data"]:
                        stand.values.setdefault(row["sn"], {})[row["s"]] = row["v"]
                    return self._reply({"error": 0})
                if u.path == "/api/auth/authenticate/":
                    form = {k: v[0] for k, v in parse_qs(raw).items()}
                    ok = form.get("login") == "emp" and form.get("password") == "pw"
                    return self._reply({"error": 0, "data": {"token": GOOD}} if ok else {"error": 1, "message": "Неверный пароль"})
                if u.path == "/api/autoscripts/edit/":
                    return self._reply({"error": 0, "data": {"id": 42}})
                self._reply({"error": 404}, 404)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def posts(self):
        return [r for r in self.requests if r[0] == "POST"]

    def close(self):
        self.srv.shutdown()


def setup_bridge(mode="live"):
    stand = Stand()
    h = hub()
    h.reset_to_seed()
    h.set_clock(running=False)
    b = UjinBridge()
    b.phase_pause = 0
    b.pace = 0
    b.retries = 0
    b.timeout = 3
    b.created.clear()
    access = json.loads(json.dumps(ACCESS).replace("{base}", stand.base))
    res = b.import_access(access)
    b.update_cfg({"mode": mode, "interval": 1, "naming": "both"})
    return stand, b, res


def test_import_access_binds_devices_and_masks_token():
    stand, b, res = setup_bridge()
    try:
        assert b.cfg["base_url"] == stand.base and b.cfg["apartment_id"] == "2767"
        assert {x["instance"] for x in res["bound"]} == {"bath_leak", "living_light"}
        assert hub().get("bath_leak").cfg["ujin"] == {"ext": "t_leak_01", "sn": "111"}
        pub = b.public_cfg()
        assert "ust" not in pub and pub["ust_set"] and GOOD not in json.dumps(b.state())
        assert mask(GOOD).startswith("ust-0000") and "…" in mask(GOOD)
        assert res["employee"]["ok"] and b.cfg["employee_ust"] == GOOD  # вход сотрудника для чтения карточек
        login = next(j for j in b.journal if j["path"] == "/api/auth/authenticate/")
        assert "password" not in json.dumps(login["body"]) and "pw" not in json.dumps(login["body"])
    finally:
        stand.close()


def test_two_phase_publish_with_mines():
    stand, b, _ = setup_bridge()
    try:
        b.flush()
        posts = [p for p in stand.posts() if "group-update" in p[1]]
        leak = [json.loads(p[3])["data"] for p in posts if json.loads(p[3])["data"][0]["sn"] == "t_leak_01"]
        phase1, phase2 = leak[0], leak[1]
        assert all(r["s"] in ("leak", "battery", "debounce") and r["v"] == 0.001 for r in phase1)   # короткие имена
        assert {r["s"] for r in phase2} == {"integrations_devices_leak", "integrations_devices_battery",
                                            "integrations_devices_debounce", "leak", "battery", "debounce"}  # both
        assert all(r["c"] == "integrations_devices" for r in phase1 + phase2)                       # c = класс модели
        assert next(r for r in phase2 if r["s"].endswith("_leak"))["v"] == 0.001                     # 0 → 0.001
        q = posts[0][2]
        assert q["token"] == GOOD and q["apartment_id"] == "2767" and q["serialnumber"] in ("t_leak_01", "t_light_01")
        assert all(p[4] == "application/json" for p in posts)                                        # только JSON
        assert not any("wet" in json.dumps(json.loads(p[3])) for p in posts)                          # окружение не уходит
        # повторная отправка — без фазы 1
        n = len(stand.posts())
        hub().act("bath_leak", "wet", 1)
        hub().step(4)
        b.flush()
        new_posts = [p for p in stand.posts()[n:] if json.loads(p[3])["data"][0]["sn"] == "t_leak_01"]
        assert len(new_posts) == 1 and any(r["s"].startswith("integrations_devices_")
                                           for r in json.loads(new_posts[0][3])["data"])
        b.update_cfg({"naming": "short"})
        hub().act("bath_leak", "wet", 0)
        hub().step(4)
        n = len(stand.posts())
        b.flush()
        rows = [r for p in stand.posts()[n:] for r in json.loads(p[3])["data"] if r["sn"] == "t_leak_01"]
        assert rows and all(not r["s"].startswith("integrations_devices_") for r in rows)
        assert "difference_by_serialnumber" in b.known_signals()
        dbg = b.raw_difference()
        assert dbg["error"] == 0 and "Протечка в ванной" in dbg["devices"]
        assert stand.values["t_leak_01"]["integrations_devices_leak"] == 1
        assert b.status["bath_leak"]["published"] > 0 and b.status["bath_leak"]["last_error"] == ""
    finally:
        stand.close()


def test_dry_mode_sends_nothing():
    stand, b, _ = setup_bridge("dry")
    try:
        b.flush()
        assert stand.posts() == []
        assert any(j["status"] == "не отправлено" for j in b.journal)
        assert not b.created  # в пробном режиме словари не считаются созданными
    finally:
        stand.close()


def test_check_compares_values_and_bad_token():
    stand, b, _ = setup_bridge()
    try:
        b.flush()
        r = b.check()
        titles = {s["title"]: s for s in r["steps"]}
        assert titles["Стенд доступен"]["ok"] and titles["Токен резидента принят"]["ok"]
        leak = titles["Протечка в ванной"]
        assert leak["ok"] and all(row["match"] for row in leak["rows"])
        b.update_cfg({"ust": "ust-bad-token-xxxxxxxx"})
        r = b.check()
        assert not next(s for s in r["steps"] if s["title"] == "Токен резидента принят")["ok"]
        b.update_cfg({"base_url": "http://127.0.0.1:9"})
        r = b.check()
        assert r["steps"][0]["ok"] is False and "нет связи" in r["steps"][0]["detail"]
    finally:
        stand.close()


def test_poll_tasks_applies_command_once():
    stand, b, _ = setup_bridge()
    try:
        assert hub().get("living_light").device.signals["lamp"].value == 0
        applied = b.poll_tasks()
        assert {"instance": "living_light", "signal": "lamp", "value": 1} in applied
        assert hub().get("living_light").device.signals["lamp"].value == 1
        hub().act("living_light", "lamp", 0)
        assert b.poll_tasks() == []  # тот же task_dt — повторно не исполняем
    finally:
        stand.close()


def test_api_and_push_scenario():
    stand = Stand()
    try:
        with TestClient(fastapi_app) as c:
            c.post("/api/emu/reset")
            access = json.loads(json.dumps(ACCESS).replace("{base}", stand.base))
            access["devices"].append({"family": "thermostat", "sn": "333", "ext": "t_thermo_01"})
            r = c.post("/api/ujin/import", json=access).json()
            assert len(r["bound"]) == 3
            assert c.post("/api/ujin/import", json={"foo": 1}).status_code == 400
            assert c.post("/api/ujin/publish").status_code in (200, 400)
            c.put("/api/ujin/config", json={"mode": "live"})
            st = c.get("/api/ujin/state").json()
            assert GOOD not in json.dumps(st) and st["ready"] is None
            items = {x["id"]: x for x in c.get("/api/ujin/scenarios").json()["items"]}
            assert items["window_heating"]["exportable"] and not items["leak_protect"]["exportable"]
            res = c.post("/api/ujin/scenarios/window_heating/push").json()["results"]
            assert res[0]["ok"] and res[0]["condition"] == "when:device-333:integrations_devices_window_open=1"
            edit = [p for p in stand.posts() if p[1] == "/api/autoscripts/edit/"][0]
            form = {k: v[0] for k, v in parse_qs(edit[3]).items()}
            assert form["token"] == GOOD and form["scenario_type"] == "trigger"
            assert c.post("/api/ujin/scenarios/leak_protect/push").status_code == 400
            assert c.post("/api/ujin/check").json()["steps"][0]["ok"]
            c.put("/api/ujin/config", json={"mode": "off"})
            c.post("/api/emu/reset")
    finally:
        stand.close()


def test_resident_check_via_difference_and_poll_pause():
    """Как на настоящем стенде: get-device-info только для УК — сверяем через difference, опрос не спамит."""
    stand, b, _ = setup_bridge()
    try:
        stand.employee_only = True
        b.cfg["employee_ust"] = ""
        b.flush()
        r = b.check()
        leak = next(s for s in r["steps"] if s["title"] == "Протечка в ванной")
        assert leak["ok"] and "difference" in leak["detail"] and all(x["match"] for x in leak["rows"])
        assert b.poll_tasks() == [] and b.poll_blocked == GOOD
        n = len(stand.requests)
        assert b.poll_tasks() == [] and len(stand.requests) == n  # больше не стучимся
        b.update_cfg({"employee_ust": "ust-other"})
        assert b.poll_blocked == ""
    finally:
        stand.close()


def test_network_error_requeues_values():
    stand, b, _ = setup_bridge()
    try:
        b.flush()
        good = b.cfg["base_url"]
        b.cfg["base_url"] = "http://127.0.0.1:9"  # стенд «упал»
        hub().act("bath_leak", "wet", 1)
        hub().step(4)
        b.flush()
        assert "повторим" in b.status["bath_leak"]["last_error"]
        assert ("bath_leak", "leak") in b.pending  # значение не потеряно
        b.cfg["base_url"] = good
        b.flush()
        assert stand.values["t_leak_01"]["integrations_devices_leak"] == 1
        assert b.status["bath_leak"]["last_error"] == ""
    finally:
        stand.close()
