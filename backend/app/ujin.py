"""Блок 5 — мост R Studio ↔ Ujin OS.

Что делает:
  • публикует значения устройств квартиры, привязанных к стенду (ext_guid/serialnumber),
    в Ujin: POST import_device/group-update-device-signal (JSON), с учётом всех «мин»
    стартового пакета — две фазы для новых сигналов, 0 → 0.001, c = класс модели,
    авторизация uae: token=<ust>&apartment_id=<id>&serialnumber=<ext> в query;
  • опрашивает команды платформы (get-device-info → task, дедуп по task_dt) и передаёт
    их эмулятору — «путь A» из PULL-CLIENT.md;
  • сверяет: читает значения с платформы и сравнивает с эмулятором;
  • отправляет сценарии в autoscripts резидента.

Режимы: off — ничего не отправляем; dry — собираем запросы и показываем их, но не шлём;
live — шлём на стенд. Токены хранятся только в backend/data/ujin.json и в ответах API
маскируются.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from . import storage
from .emulation import EmulationError, hub

PUBLISH_PATH = "/api/import_device/group-update-device-signal/"
DEFAULTS = {
    "mode": "off",                     # off | dry | live
    "base_url": "https://api-uae-test.ujin.tech",
    "ust": "",                         # токен резидента квартиры
    "apartment_id": "",
    "cls": "integrations_devices",     # класс модели: поле c и префикс полного имени
    "interval": 2,                     # как часто отправлять накопленные изменения, с
    "poll_tasks": True,                # опрашивать команды платформы
    "poll_interval": 5,
    "employee_ust": "",                # необязательно: для чтения get-device-info (на uae — только сотрудник)
    "naming": "short",                 # имена при отправке значений: short (имя — так хранит стенд тест-ОАЭ) | full | both
}
SECRET_KEYS = ("ust", "employee_ust")
FAMILY_TO_DEVICE = {"leak": "leak_sensor", "barrier": "barrier", "thermostat": "thermostat",
                    "counter": "power_meter", "light": "smart_light", "ventilation": "ventilation",
                    "fire": "smoke_detector", "hub": "leak_sensor"}


def mask(token: str) -> str:
    if not token:
        return ""
    return token[:8] + "…" + token[-4:] if len(token) > 14 else "…"


def wire(v: Any) -> Any:
    """Мина №1: платформа не пишет 0 (empty()) — отправляем 0.001."""
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, (int, float)):
        return 0.001 if v == 0 else v
    return v


class UjinBridge:
    def __init__(self) -> None:
        self.cfg: Dict[str, Any] = dict(DEFAULTS)
        self.created: set = set()                    # «ext:signal» — словарь уже создан
        self.journal: Deque[dict] = deque(maxlen=200)
        self.status: Dict[str, dict] = {}            # по instance id
        self.pending: Dict[Tuple[str, str], Any] = {}
        self.task_seen: Dict[str, str] = {}
        self.last_check: Optional[dict] = None
        self._lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None
        self._poll_at = 0.0
        self.poll_blocked = ""  # токен, которому стенд отказал в get-device-info
        self.timeout = 20.0     # стенд тест-ОАЭ отвечает медленно и иногда рвёт соединение
        self.retries = 2
        self.pace = 0.4         # пауза между устройствами, чтобы не душить стенд
        self.phase_pause = 2.0  # мина №2: пауза между созданием словаря и значениями
        self._cfg_file = os.path.join(storage.DATA, "ujin.json")
        self._state_file = os.path.join(storage.DATA, "ujin_state.json")
        self.load()
        hub().add_hook(self._on_hub)

    # ------------------------------------------------------------------ настройки
    def load(self) -> None:
        if os.path.exists(self._cfg_file):
            with open(self._cfg_file, encoding="utf-8") as fh:
                self.cfg.update(json.load(fh))
        if os.path.exists(self._state_file):
            with open(self._state_file, encoding="utf-8") as fh:
                self.created = set(json.load(fh).get("created", []))

    def save(self) -> None:
        os.makedirs(storage.DATA, exist_ok=True)
        with open(self._cfg_file, "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, ensure_ascii=False, indent=2)
        with open(self._state_file, "w", encoding="utf-8") as fh:
            json.dump({"created": sorted(self.created)}, fh, ensure_ascii=False, indent=2)

    def public_cfg(self) -> dict:
        out = {k: v for k, v in self.cfg.items() if k not in SECRET_KEYS}
        for k in SECRET_KEYS:
            out[k + "_set"] = bool(self.cfg.get(k))
            out[k + "_masked"] = mask(self.cfg.get(k, ""))
        return out

    def update_cfg(self, patch: dict) -> dict:
        for k, v in patch.items():
            if k not in DEFAULTS:
                continue
            if k in SECRET_KEYS and (v is None or v == ""):
                continue  # пустое поле в форме = «не менять токен»
            if k == "base_url":
                v = str(v).strip().rstrip("/")
                if v.endswith("/api"):
                    v = v[:-4]
            if k == "mode" and v not in ("off", "dry", "live"):
                raise ValueError("режим: off, dry или live")
            if k == "naming" and v not in ("full", "short", "both"):
                raise ValueError("имена: full, short или both")
            self.cfg[k] = v
        self.poll_blocked = ""
        self.save()
        if self.cfg["mode"] != "off":
            self.queue_all()  # включили — отправить текущее состояние
        return self.public_cfg()

    def import_access(self, data: dict, resident: int = 0) -> dict:
        """Разобрать доступы.json из пакета команды: URL, ust резидента, квартира, привязки."""
        res = (data.get("residents") or [{}])
        r = res[min(resident, len(res) - 1)] if res else {}
        patch = {"apartment_id": str(r.get("apartment_id") or data.get("team_apartment") or "")}
        if r.get("ust"):
            patch["ust"] = r["ust"]
        if data.get("api_base"):
            patch["base_url"] = data["api_base"]
        bound = []
        h = hub()
        for d in data.get("devices", []):
            dev_id = FAMILY_TO_DEVICE.get(d.get("family", ""))
            if not dev_id:
                continue
            inst = next((i for i in h.instances.values() if i.cfg["device_id"] == dev_id), None)
            if inst is None:
                continue
            if d.get("publish_class"):
                patch["cls"] = d["publish_class"]
            h.update(inst.id, {"ujin": {"ext": str(d.get("ext", "")), "sn": str(d.get("sn", ""))}})
            bound.append({"instance": inst.id, "title": inst.describe()["title"],
                          "ext": d.get("ext"), "sn": d.get("sn")})
        self.update_cfg(patch)
        emp = data.get("employee") or {}
        employee = None
        if emp.get("login") and emp.get("password") and not self.cfg.get("employee_ust"):
            employee = self.login(emp["login"], emp["password"], emp.get("app", ""))
            if employee.get("ok"):
                self.cfg["employee_ust"] = employee.pop("token")
                self.save()
        return {"cfg": self.public_cfg(), "bound": bound, "residents": len(res), "employee": employee}

    def login(self, login: str, password: str, app: str = "") -> dict:
        """auth/authenticate → ust. Нужен сотруднику, чтобы читать карточки устройств (get-device-info)."""
        body = {"login": login, "password": password}
        if app:
            body["app"] = app
        r = self._http("POST", "/api/auth/authenticate/", {}, body, form=True,
                       note="вход сотрудника", always=True)
        token = (r.get("data") or {}).get("token") if isinstance(r.get("data"), dict) else None
        if r.get("error") in (0, "0") and token:
            return {"ok": True, "token": token}
        return {"ok": False, "message": str(r.get("message") or r.get("error"))}

    # ------------------------------------------------------------------ HTTP
    def _http(self, method: str, path: str, query: Dict[str, Any], body: Any = None,
              form: bool = False, note: str = "", always: bool = False) -> dict:
        base = self.cfg["base_url"].rstrip("/")
        qs = urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
        url = base + path + ("?" + qs if qs else "")
        rec = {"at": time.time(), "method": method, "path": path, "note": note,
               "query": {k: (mask(str(v)) if k == "token" else v) for k, v in query.items() if v not in (None, "")},
               "body": body if not form else {k: v for k, v in (body or {}).items() if k not in ("token", "password")},
               "mode": self.cfg["mode"], "ok": False, "status": None, "error": None, "ms": 0}
        if self.cfg["mode"] == "dry" and not always:  # проверки (только чтение) идут и в пробном режиме
            rec.update(ok=True, status="не отправлено", error=None)
            self._log(rec)
            return {"error": 0, "dry_run": True}
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            if form:
                data = urllib.parse.urlencode({k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                                               for k, v in body.items()}).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body, ensure_ascii=False).encode()
                headers["Content-Type"] = "application/json"  # мина №5: только JSON-тело
        t0 = time.time()
        raw = None
        for attempt in range(1 + self.retries):  # стенд иногда рвёт соединение — пробуем ещё раз
            try:
                req = urllib.request.Request(url, data=data, method=method, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    rec["status"] = resp.status
                break
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                rec["status"] = e.code
                break
            except (urllib.error.URLError, socket.timeout, OSError) as e:
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                rec.update(ms=int((time.time() - t0) * 1000), retries=attempt,
                           error=f"нет связи со стендом: {getattr(e, 'reason', e)}")
                self._log(rec)
                return {"error": -1, "message": rec["error"]}
        if attempt:
            rec["retries"] = attempt
        rec["ms"] = int((time.time() - t0) * 1000)
        try:
            out = json.loads(raw)
        except ValueError:
            out = {"error": -2, "message": f"ответ не JSON: {raw[:120]}"}
        if not isinstance(out, dict):
            out = {"error": 0, "data": out}
        err = out.get("error")
        rec["ok"] = rec["status"] == 200 and (err in (0, "0", None))
        if not rec["ok"]:
            rec["error"] = str(out.get("message") or out.get("error_code") or f"HTTP {rec['status']}")[:200]
        rec["response"] = _short(_scrub(out))  # ответ входа содержит токен — в журнал не пускаем
        self._log(rec)
        return out

    def _log(self, rec: dict) -> None:
        self.journal.append(rec)
        hub().broadcast("ujin", {"journal": rec})

    def _auth(self, ext: str = "") -> Dict[str, Any]:
        # uae: ust + apartment_id В QUERY (гейт verif_crm_user_apartment) + serialnumber
        return {"token": self.cfg["ust"], "apartment_id": self.cfg["apartment_id"], "serialnumber": ext}

    def ready(self) -> Optional[str]:
        if not self.cfg.get("ust"):
            return "не задан токен резидента (ust)"
        if not str(self.cfg.get("apartment_id") or "").strip():
            return "не задана квартира (apartment_id)"
        return None

    # ------------------------------------------------------------------ публикация
    def bound(self) -> List[Any]:
        return [i for i in hub().instances.values() if (i.cfg.get("ujin") or {}).get("ext") and i.device]

    def publishable(self, inst) -> List[str]:
        return [n for n, s in inst.device.specs.items()
                if s.group != "environment" and s.type not in ("button", "text")
                and inst.device.signals[n].publishable]

    def _on_hub(self, kind: str, p: dict) -> None:
        if kind == "snapshot" and self.cfg["mode"] != "off":
            self.queue_all()
        if kind != "values" or self.cfg["mode"] == "off":
            return
        with self._lock:
            for inst in self.bound():
                ch = p["changes"].get(inst.id)
                if not ch:
                    continue
                allowed = set(self.publishable(inst))
                for name, value in ch.items():
                    if name in allowed:
                        self.pending[(inst.id, name)] = value

    def queue_all(self) -> None:
        with self._lock:
            for inst in self.bound():
                for n in self.publishable(inst):
                    self.pending[(inst.id, n)] = inst.device.signals[n].value

    def flush(self) -> List[dict]:
        """Отправить накопленное: по устройству — фаза 1 (новые словари), фаза 2 (значения)."""
        if self.cfg["mode"] == "off":
            return []
        problem = self.ready()
        if problem and self.cfg["mode"] == "live":
            return []
        with self._lock:
            items, self.pending = self.pending, {}
        if not items:
            return []
        cls = self.cfg["cls"]
        by_inst: Dict[str, Dict[str, Any]] = {}
        for (iid, name), v in items.items():
            by_inst.setdefault(iid, {})[name] = v
        results = []
        h = hub()
        for iid, values in by_inst.items():
            inst = h.instances.get(iid)
            if inst is None:
                continue
            ext = inst.cfg["ujin"]["ext"]
            st = self.status.setdefault(iid, {"published": 0, "errors": 0, "last_ok": None, "last_error": "",
                                              "created": 0})
            new = [n for n in values if f"{ext}:{n}" not in self.created]
            if new:
                r = self._http("POST", PUBLISH_PATH, self._auth(ext),
                               {"data": [{"sn": ext, "s": n, "v": 0.001, "c": cls} for n in new]},
                               note=f"{inst.describe()['title']}: создать сигналы ({len(new)})")
                if r.get("error") in (0, "0"):
                    if not r.get("dry_run"):
                        self.created.update(f"{ext}:{n}" for n in new)
                        st["created"] += len(new)
                        self.save()
                        time.sleep(self.phase_pause)  # мина №2: memcache-кэш нового словаря
                else:
                    st["errors"] += 1
                    st["last_error"] = str(r.get("message") or r.get("error"))
                    with self._lock:  # вернуть в очередь — попробуем на следующем круге
                        for n, v in values.items():
                            self.pending.setdefault((iid, n), v)
                    results.append({"instance": iid, "ok": False})
                    continue
            naming = self.cfg.get("naming", "both")
            rows = []
            for n, v in values.items():
                # по памятке — полное имя «класс_имя»; на стенде тест-ОАЭ значения видны под коротким —
                # в режиме both шлём оба, сверка покажет, какой вариант платформа хранит
                if naming in ("full", "both"):
                    rows.append({"sn": ext, "s": f"{cls}_{n}", "v": wire(v), "c": cls})
                if naming in ("short", "both"):
                    rows.append({"sn": ext, "s": n, "v": wire(v), "c": cls})
            r = self._http("POST", PUBLISH_PATH, self._auth(ext), {"data": rows},
                           note=f"{inst.describe()['title']}: значения ({len(rows)})")
            ok = r.get("error") in (0, "0")
            if ok:
                st["published"] += len(values)
                st["last_ok"] = time.time()
                st["last_values"] = {n: wire(v) for n, v in values.items()}
                st["last_error"] = ""
            else:
                st["errors"] += 1
                st["last_error"] = str(r.get("message") or r.get("error"))
                if r.get("error") == -1:  # сеть, а не отказ платформы — отправим на следующем круге
                    st["last_error"] += " — повторим автоматически"
                    with self._lock:
                        for n, v in values.items():
                            self.pending.setdefault((iid, n), v)
            results.append({"instance": iid, "ok": ok, "rows": len(rows)})
            if self.pace:
                time.sleep(self.pace)
        hub().broadcast("ujin", {"status": self.status})
        return results

    # ------------------------------------------------------------------ команды платформы (путь A)
    def poll_tasks(self) -> List[dict]:
        token = self.cfg.get("employee_ust") or self.cfg.get("ust")
        if not token or self.cfg["mode"] != "live":
            return []
        if self.poll_blocked == token:
            return []  # стенд уже ответил «только сотрудник УК» — не засоряем журнал
        applied = []
        prefix = self.cfg["cls"] + "_"
        for inst in self.bound():
            sn = (inst.cfg.get("ujin") or {}).get("sn")
            if not sn:
                continue
            info = self._http("GET", "/api/bmsdevice/get-device-info/",
                              {"token": token, "serialnumber": sn, "mts": 1}, note="команды платформы")
            if _denied(info):
                self.poll_blocked = token
                self._log({"at": time.time(), "method": "-", "path": "-", "ok": True, "status": "пауза",
                           "error": None, "ms": 0, "mode": self.cfg["mode"],
                           "note": "опрос команд остановлен: стенд разрешает его только сотруднику УК — "
                                   "добавьте токен сотрудника, и опрос возобновится"})
                return applied
            for s in ((info.get("data") or {}).get("signals") or []):
                name = s.get("name") or s.get("signal_name") or ""
                task = s.get("signal_task_value", s.get("task"))
                if task in (None, ""):
                    continue
                dt = str(s.get("signal_task_dt") or s.get("task_dt") or "")
                key = f"{inst.id}:{name}"
                if dt and self.task_seen.get(key) == dt:
                    continue  # дедуп: эту команду уже исполнили
                self.task_seen[key] = dt or str(task)
                short = name[len(prefix):] if name.startswith(prefix) else name
                try:
                    hub().act(inst.id, short, float(task), "Ujin")
                    applied.append({"instance": inst.id, "signal": short, "value": task})
                except (EmulationError, ValueError) as exc:
                    applied.append({"instance": inst.id, "signal": short, "error": str(exc)})
        return applied

    # ------------------------------------------------------------------ проверка связи и сверка
    def check(self) -> dict:
        """Только чтение: доступен ли стенд, принят ли токен, что платформа знает об устройствах."""
        steps = []
        problem = self.ready()
        if problem:
            steps.append({"title": "Настройки", "ok": False, "detail": problem})
            self.last_check = {"at": time.time(), "steps": steps, "ok": False}
            return self.last_check
        r = self._http("GET", "/api/devices/difference/",
                       {"token": self.cfg["ust"], "dt": int(time.time()) - 86400}, note="проверка связи", always=True)
        if r.get("error") == -1:
            steps.append({"title": "Стенд доступен", "ok": False, "detail": r.get("message")})
            self.last_check = {"at": time.time(), "steps": steps, "ok": False}
            return self.last_check
        steps.append({"title": "Стенд доступен", "ok": True, "detail": self.cfg["base_url"]})
        tok_ok = r.get("error") in (0, "0")
        steps.append({"title": "Токен резидента принят", "ok": tok_ok,
                      "detail": "devices/difference ответил без ошибки" if tok_ok
                      else f"ответ: {r.get('message') or r.get('error')}"})
        # значения квартиры глазами жителя: difference отдаёт сигналы по serialnumber
        seen = _difference(r) if tok_ok else {}
        emp = self.cfg.get("employee_ust")
        prefix = self.cfg["cls"] + "_"
        for inst in self.bound():
            sn = str(inst.cfg["ujin"].get("sn") or "")
            title = inst.describe()["title"]
            if not sn:
                steps.append({"title": title, "ok": False, "detail": "нет serialnumber — привяжите в «Эмуляторах»"})
                continue
            platform = dict(seen.get(sn, {}))
            source = "devices/difference (житель)"
            if emp:
                info = self._http("GET", "/api/bmsdevice/get-device-info/",
                                  {"token": emp, "serialnumber": sn, "mts": 1}, note="проверка связи", always=True)
                if info.get("error") in (0, "0"):
                    platform.update(_signals(info))
                    source = "get-device-info (сотрудник)"
            if False:  # пустой ответ тоже показываем таблицей — видно, чего нет
                steps.append({"title": title, "ok": None,
                              "detail": "платформа не прислала по этому устройству ни одного сигнала за сутки — "
                                        "включите «На стенд» и проверьте журнал отправки"})
                continue
            rows = []
            for n in self.publishable(inst):
                mine = wire(inst.device.signals[n].value)
                full, short = platform.get(prefix + n), platform.get(n)
                theirs = full if full is not None else short
                rows.append({"signal": n, "emulator": mine, "platform": theirs,
                             "as": "полное" if full is not None else "короткое" if short is not None else "",
                             "match": theirs is not None and _close(mine, theirs)})
            found = sum(1 for x in rows if x["platform"] is not None)
            other = sorted(k for k in platform if not k.startswith(prefix) and k not in
                           {x["signal"] for x in rows})[:8]
            missing = [x["signal"] for x in rows if x["platform"] is None]
            detail = f"на платформе найдено {found} из {len(rows)} сигналов ({source})"
            if missing:
                detail += (f". Нет на стенде: {', '.join(missing)} — для них на стенде нет словаря сигналов, "
                           "а создать новый с этого стенда нельзя (комплы ждут verify-compl организаторов)")
            steps.append({"title": title, "ok": found > 0 if rows else None, "rows": rows, "missing": missing,
                          "detail": detail})
        self.last_check = {"at": time.time(), "steps": steps,
                           "ok": all(s["ok"] is not False for s in steps)}
        return self.last_check

    def raw_difference(self, hours: int = 24) -> dict:
        """Диагностика: что devices/difference знает о привязанных устройствах — без обрезки."""
        r = self._http("GET", "/api/devices/difference/",
                       {"token": self.cfg["ust"], "dt": int(time.time()) - hours * 3600},
                       note="диагностика", always=True)
        sns = {str((i.cfg.get("ujin") or {}).get("sn")): i.describe()["title"] for i in self.bound()}
        data = r.get("data") if isinstance(r.get("data"), dict) else {}
        items = [it for it in (data.get("difference") or []) if str(it.get("serialnumber")) in sns]
        by = {}
        for it in items:
            by.setdefault(sns[str(it.get("serialnumber"))], []).append(
                {k: it.get(k) for k in ("signal", "value", "dt", "oc")})
        return {"error": r.get("error"), "message": r.get("message"), "total_items": len((data or {}).get("difference") or []),
                "naming": self.cfg.get("naming"), "devices": by}

    def known_signals(self) -> dict:
        """Какие сигналы стенд знает для квартиры: autoscripts/signals (справочник жителя) + difference за неделю."""
        r = self._http("GET", "/api/autoscripts/signals/", {"token": self.cfg["ust"]}, note="диагностика", always=True)
        names: Dict[str, set] = {}
        def walk(x, path=""):
            if isinstance(x, dict):
                n = x.get("signal") or x.get("signal_name") or x.get("name")
                if isinstance(n, str) and n:
                    names.setdefault(n, set()).add(path or "-")
                for k, v in x.items():
                    walk(v, k if not path else path)
            elif isinstance(x, list):
                for v in x:
                    walk(v, path)
        walk(r.get("data"))
        d = self._http("GET", "/api/devices/difference/", {"token": self.cfg["ust"], "dt": int(time.time()) - 7 * 86400},
                       note="диагностика", always=True)
        per_sn: Dict[str, set] = {}
        data = d.get("data") if isinstance(d.get("data"), dict) else {}
        for it in (data or {}).get("difference") or []:
            per_sn.setdefault(str(it.get("serialnumber")), set()).add(str(it.get("signal")))
        return {"autoscripts_signals": {"error": r.get("error"), "message": r.get("message"),
                                        "names": {k: sorted(v) for k, v in sorted(names.items())}},
                "difference_by_serialnumber": {k: sorted(v) for k, v in per_sn.items()}}

    def publish_now(self) -> List[dict]:
        self.queue_all()
        return self.flush()

    def reset_created(self) -> None:
        self.created.clear()
        self.save()

    # ------------------------------------------------------------------ сценарии → autoscripts
    def push_scenario(self, req_list: List[dict]) -> List[dict]:
        out = []
        for rq in req_list:
            params = dict(rq["params"])
            params["token"] = self.cfg["ust"]
            r = self._http("POST", "/api/autoscripts/edit/", {}, params, form=True,
                           note=f"сценарий «{params.get('title', '')}»")
            out.append({"ok": r.get("error") in (0, "0"), "message": r.get("message"),
                        "id": (r.get("data") or {}).get("id") if isinstance(r.get("data"), dict) else None,
                        "condition": params.get("condition"), "set_signal": params.get("set_signal")})
        return out

    def list_scenarios(self) -> dict:
        return self._http("GET", "/api/autoscripts/list/", {"token": self.cfg["ust"]}, note="проверка связи", always=True)

    # ------------------------------------------------------------------ фоновый цикл
    async def run(self) -> None:
        while True:
            try:
                if self.cfg["mode"] != "off":
                    await asyncio.to_thread(self.flush)
                    if self.cfg.get("poll_tasks") and time.time() >= self._poll_at:
                        self._poll_at = time.time() + max(2, float(self.cfg.get("poll_interval", 5)))
                        await asyncio.to_thread(self.poll_tasks)
            except Exception as exc:  # мост не должен ронять сервер
                self._log({"at": time.time(), "method": "-", "path": "-", "ok": False, "error": str(exc),
                           "note": "ошибка моста", "mode": self.cfg["mode"]})
            await asyncio.sleep(max(1.0, float(self.cfg.get("interval", 2))))

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

    def state(self) -> dict:
        h = hub()
        devices = []
        for inst in h.instances.values():
            u = inst.cfg.get("ujin") or {}
            devices.append({"instance": inst.id, "title": inst.describe()["title"], "room": inst.cfg.get("room", ""),
                            "device_id": inst.cfg["device_id"], "ext": u.get("ext", ""), "sn": u.get("sn", ""),
                            "signals": [f"{self.cfg['cls']}_{n}" for n in self.publishable(inst)] if inst.device and u.get("ext") else [],
                            "status": self.status.get(inst.id)})
        return {"cfg": self.public_cfg(), "ready": self.ready(), "devices": devices,
                "journal": list(self.journal)[-80:], "last_check": self.last_check,
                "created": len(self.created)}


def _signals(info: dict) -> Dict[str, Any]:
    out = {}
    data = info.get("data") or {}
    for s in (data.get("signals") or []) if isinstance(data, dict) else []:
        name = s.get("name") or s.get("signal_name")
        val = s.get("value", (s.get("state") or {}).get("value") if isinstance(s.get("state"), dict) else None)
        if name:
            out[name] = val
    return out


def _scrub(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: (mask(str(v)) if k in ("token", "ust", "password", "user_token") and v else _scrub(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


def _denied(r: dict) -> bool:
    return str(r.get("error_code", "")).lower() == "access denied" or "сотрудника" in str(r.get("message", ""))


def _difference(r: dict) -> Dict[str, Dict[str, Any]]:
    """devices/difference → {serialnumber: {signal: последнее значение}}."""
    out: Dict[str, Dict[str, Any]] = {}
    last: Dict[Tuple[str, str], float] = {}
    data = r.get("data") or {}
    items = data.get("difference") if isinstance(data, dict) else None
    for it in items or []:
        if not isinstance(it, dict):
            continue
        sn = str(it.get("serialnumber") or it.get("id") or "")
        sig = it.get("signal")
        if not sn or not sig:
            continue
        dt = float(it.get("dt") or 0)
        if dt >= last.get((sn, sig), -1):
            last[(sn, sig)] = dt
            out.setdefault(sn, {})[sig] = it.get("value")
    return out


def _close(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) <= max(0.01, abs(float(a)) * 0.01)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _short(obj: Any, limit: int = 600) -> Any:
    s = json.dumps(obj, ensure_ascii=False)
    if len(s) <= limit:
        return obj
    return s[:limit] + "…"


_bridge: Optional[UjinBridge] = None


def bridge() -> UjinBridge:
    global _bridge
    if _bridge is None:
        _bridge = UjinBridge()
    return _bridge
