"""Блок 1 — API конструктора устройств: язык RDL, библиотека, проверка, песочница."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from . import storage
from .emulation import hub
from .rdl import CATEGORIES, GROUP_TITLES, DeviceSpec, analyze, simulate, ujin_declaration
from .rdl.expr import FUNCS

router = APIRouter(prefix="/api", tags=["конструктор устройств"])


def _summary(doc: Dict) -> Dict:
    lib = storage.devices()
    spec, issues = analyze(doc)
    groups: Dict[str, int] = {}
    for s in doc.get("signals", []):
        g = s.get("group", "property")
        groups[g] = groups.get(g, 0) + 1
    return {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "category": doc.get("category", "other"),
        "icon": doc.get("icon", "device"),
        "description": doc.get("description", ""),
        "model": (spec.effective_model if spec else doc.get("model") or ""),
        "groups": groups,
        "events": [{"name": e.get("name"), "title": e.get("title")} for e in doc.get("events", [])],
        "valid": spec is not None,
        "errors": sum(1 for i in issues if i["severity"] == "error"),
        "builtin": lib.is_builtin(doc.get("id", "")),
    }


@router.get("/rdl/schema")
def rdl_schema() -> Dict:
    """JSON Schema языка RDL (для редакторов и внешних интеграторов)."""
    return DeviceSpec.model_json_schema()


@router.get("/rdl/meta")
def rdl_meta() -> Dict:
    """Справочник для UI: группы, категории, типы, функции выражений."""
    return {
        "groups": GROUP_TITLES,
        "categories": CATEGORIES,
        "types": {"bool": "Да / нет", "number": "Число", "enum": "Варианты",
                  "text": "Текст", "button": "Кнопка"},
        "functions": sorted(k for k in FUNCS),
        "triggers": {"tick": "каждую секунду", "start": "при запуске",
                     "command": "любая команда", "command:<сигнал>": "команда сигналу",
                     "change:<сигнал>": "сигнал изменился"},
    }


@router.post("/rdl/validate")
def rdl_validate(doc: Any = Body(...)) -> Dict:
    spec, issues = analyze(doc)
    return {"ok": spec is not None, "issues": issues}


@router.post("/rdl/compile")
def rdl_compile(doc: Any = Body(...), cls: str = "integrations_devices") -> Dict:
    """RDL → декларация Ujin (то, что уходит в ЛК разработчика / signal_dict)."""
    spec, issues = analyze(doc)
    if spec is None:
        raise HTTPException(422, {"message": "в описании есть ошибки", "issues": issues})
    return {"ok": True, "issues": issues, "ujin": ujin_declaration(spec, cls)}


class SimCommand(BaseModel):
    at: float = Field(0, ge=0)
    signal: str
    value: Any


class SimRequest(BaseModel):
    device: Dict[str, Any]
    seconds: int = Field(60, ge=1, le=3600)
    dt: int = Field(1, ge=1, le=60)
    commands: List[SimCommand] = []
    seed: int = 1


@router.post("/rdl/simulate")
def rdl_simulate(req: SimRequest) -> Dict:
    """Песочница конструктора: прогнать физику устройства без сети."""
    spec, issues = analyze(req.device)
    if spec is None:
        raise HTTPException(422, {"message": "в описании есть ошибки", "issues": issues})
    return simulate(spec, req.seconds, req.dt, [c.model_dump() for c in req.commands], req.seed)


# ---------------------------------------------------------------- библиотека
@router.get("/devices")
def list_devices() -> List[Dict]:
    return [_summary(d) for d in storage.devices().all()]


@router.get("/devices/{device_id}")
def get_device(device_id: str) -> Dict:
    lib = storage.devices()
    if not lib.exists(device_id):
        raise HTTPException(404, "устройство не найдено")
    doc = lib.get(device_id)
    _, issues = analyze(doc)
    return {"device": doc, "issues": issues, "builtin": lib.is_builtin(device_id)}


@router.put("/devices/{device_id}")
def save_device(device_id: str, doc: Dict[str, Any] = Body(...),
                force: bool = False) -> Dict:
    """Сохранить. С ошибками сохраняет только при force=1 (черновик)."""
    if doc.get("id") != device_id:
        raise HTTPException(400, "id в описании не совпадает с адресом")
    spec, issues = analyze(doc)
    if spec is None and not force:
        raise HTTPException(422, {"message": "в описании есть ошибки", "issues": issues})
    storage.devices().put(device_id, doc)
    if spec is not None:
        hub().reload_device(device_id)  # живые эмуляторы сразу получают новую физику
    return {"ok": True, "issues": issues, "summary": _summary(doc)}


@router.post("/devices")
def create_device(doc: Dict[str, Any] = Body(...)) -> Dict:
    lib = storage.devices()
    did = doc.get("id", "")
    if lib.exists(did):
        raise HTTPException(409, f"устройство '{did}' уже есть")
    spec, issues = analyze(doc)
    if spec is None:
        raise HTTPException(422, {"message": "в описании есть ошибки", "issues": issues})
    lib.put(did, doc)
    return {"ok": True, "issues": issues, "summary": _summary(doc)}


@router.post("/devices/{device_id}/clone")
def clone_device(device_id: str, new_id: str = Body(..., embed=True),
                 title: Optional[str] = Body(None, embed=True)) -> Dict:
    lib = storage.devices()
    if not lib.exists(device_id):
        raise HTTPException(404, "устройство не найдено")
    if lib.exists(new_id):
        raise HTTPException(409, f"устройство '{new_id}' уже есть")
    doc = lib.get(device_id)
    doc["id"] = new_id
    doc["model"] = ""
    doc["title"] = title or f"{doc['title']} (копия)"
    spec, issues = analyze(doc)
    if spec is None:
        raise HTTPException(422, {"message": "некорректный id", "issues": issues})
    lib.put(new_id, doc)
    return {"ok": True, "summary": _summary(doc)}


@router.post("/devices/{device_id}/reset")
def reset_device(device_id: str) -> Dict:
    lib = storage.devices()
    if not lib.is_builtin(device_id):
        raise HTTPException(400, "это не встроенный шаблон")
    doc = lib.template(device_id)
    lib.put(device_id, doc)
    hub().reload_device(device_id)
    return {"ok": True, "device": doc}


@router.delete("/devices/{device_id}")
def delete_device(device_id: str) -> Dict:
    used = [i.id for i in hub().instances.values() if i.cfg["device_id"] == device_id]
    if used:
        raise HTTPException(409, "устройство стоит в квартире эмулятора: " + ", ".join(used)
                            + ". Сначала уберите его оттуда.")
    if not storage.devices().delete(device_id):
        raise HTTPException(404, "устройство не найдено")
    return {"ok": True}
