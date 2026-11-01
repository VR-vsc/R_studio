"""Блок 3 — API редактора сценариев: каталог квартиры, проверка, текст, конфликты, экспорт в Ujin."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException

from . import storage
from .emulation import EmulationError
from .engine import engine, test_scenario
from .scenarios import Catalog, Scenario, analyze, conflicts, describe, to_ujin

router = APIRouter(prefix="/api/scenarios", tags=["сценарии"])


def _summary(doc: Dict, cat: Catalog) -> Dict:
    sc, issues = analyze(doc, cat)
    out = {
        "id": doc.get("id"), "title": doc.get("title"), "enabled": doc.get("enabled", True),
        "description": doc.get("description", ""),
        "valid": sc is not None,
        "errors": sum(1 for i in issues if i["severity"] == "error"),
        "warnings": sum(1 for i in issues if i["severity"] == "warning"),
        "trigger_types": sorted({t.get("type") for t in doc.get("triggers", [])}),
        "sentence": describe(sc, cat)["sentence"] if sc else "",
        "builtin": storage.scenarios().is_builtin(doc.get("id", "")),
    }
    return out


def _valid_all(cat: Catalog) -> List[Scenario]:
    out = []
    for d in storage.scenarios().all():
        sc, _ = analyze(d, cat)
        if sc:
            out.append(sc)
    return out


@router.get("/engine")
def engine_state() -> Dict:
    """Что исполняет движок: активные сценарии, последние запуски, уведомления."""
    return engine().state()


@router.post("/test")
def test(body: Dict[str, Any] = Body(...)) -> Dict:
    """Проверить сценарий на копии квартиры: {scenario, seconds?, plan?, with_others?}."""
    return test_scenario(body.get("scenario"), body.get("seconds"), body.get("plan"),
                         bool(body.get("with_others")))


@router.post("/{sid}/run")
def run_now(sid: str) -> Dict:
    """Запустить сценарий сейчас в живой квартире (как кнопка в приложении)."""
    try:
        return engine().run_now(sid)
    except EmulationError as e:
        raise HTTPException(400, str(e))


@router.get("/catalog")
def catalog() -> Dict:
    """Устройства квартиры для конструктора сценариев: сигналы по группам и события."""
    cat = Catalog.from_hub()
    items = []
    for i in cat.inst.values():
        items.append({k: i.get(k) for k in ("id", "title", "room", "device_id", "device_title",
                                             "signals", "events", "ujin", "error")})
    return {"instances": items}


@router.get("")
def list_scenarios() -> Dict:
    cat = Catalog.from_hub()
    docs = storage.scenarios().all()
    return {"items": [_summary(d, cat) for d in docs], "conflicts": conflicts(_valid_all(cat), cat)}


@router.get("/{sid}")
def get_scenario(sid: str) -> Dict:
    lib = storage.scenarios()
    if not lib.exists(sid):
        raise HTTPException(404, "сценарий не найден")
    doc = lib.get(sid)
    return {"scenario": doc, **check(doc)}


@router.post("/check")
def check(doc: Any = Body(...)) -> Dict:
    """Проверить черновик: замечания, фраза по-русски, конфликты с другими, экспорт в Ujin."""
    cat = Catalog.from_hub()
    sc, issues = analyze(doc, cat)
    res: Dict[str, Any] = {"ok": sc is not None, "issues": issues}
    if sc:
        res["text"] = describe(sc, cat)
        others = [s for s in _valid_all(cat) if s.id != sc.id] + [sc]
        res["conflicts"] = [c for c in conflicts(others, cat) if sc.id in c["scenarios"]]
        res["ujin"] = to_ujin(sc, cat)
    return res


@router.put("/{sid}")
def save(sid: str, doc: Dict[str, Any] = Body(...), force: bool = False) -> Dict:
    if doc.get("id") != sid:
        raise HTTPException(400, "id в сценарии не совпадает с адресом")
    sc, issues = analyze(doc)
    if sc is None and not force:
        raise HTTPException(422, {"message": "в сценарии есть ошибки", "issues": issues})
    storage.scenarios().put(sid, doc)
    engine().reload()
    return {"ok": True, "issues": issues}


@router.post("")
def create(doc: Dict[str, Any] = Body(...)) -> Dict:
    lib = storage.scenarios()
    sid = doc.get("id", "")
    if lib.exists(sid):
        raise HTTPException(409, f"сценарий «{sid}» уже есть")
    try:
        Scenario.model_validate({**doc, "triggers": doc.get("triggers") or [{"type": "manual"}],
                                 "actions": doc.get("actions") or [{"type": "wait", "seconds": 1}]})
    except Exception:
        raise HTTPException(422, {"message": "проверьте id и название", "issues": []})
    lib.put(sid, doc)
    engine().reload()
    return {"ok": True}


@router.post("/{sid}/enabled")
def set_enabled(sid: str, enabled: bool = Body(..., embed=True)) -> Dict:
    lib = storage.scenarios()
    if not lib.exists(sid):
        raise HTTPException(404, "сценарий не найден")
    doc = lib.get(sid)
    doc["enabled"] = enabled
    lib.put(sid, doc)
    engine().reload()
    return {"ok": True, "enabled": enabled}


@router.post("/{sid}/reset")
def reset(sid: str) -> Dict:
    lib = storage.scenarios()
    if not lib.is_builtin(sid):
        raise HTTPException(400, "это не встроенный сценарий")
    doc = lib.template(sid)
    lib.put(sid, doc)
    engine().reload()
    return {"ok": True, "scenario": doc}


@router.delete("/{sid}")
def delete(sid: str) -> Dict:
    if not storage.scenarios().delete(sid):
        raise HTTPException(404, "сценарий не найден")
    engine().reload()
    return {"ok": True}
