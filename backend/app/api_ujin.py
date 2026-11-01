"""Блок 5 — API интеграции с Ujin OS: настройки, импорт доступов, проверка связи, публикация, autoscripts."""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from . import storage
from .scenarios import Catalog, analyze, to_ujin
from .emulation import hub
from .ujin import bridge

router = APIRouter(prefix="/api/ujin", tags=["Ujin OS"])


@router.get("/state")
def state() -> Dict:
    """Настройки (токены замаскированы), привязки устройств, журнал запросов, последняя проверка."""
    return bridge().state()


@router.put("/config")
def config(patch: Dict[str, Any] = Body(...)) -> Dict:
    try:
        return bridge().update_cfg(patch)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/import")
def import_access(data: Dict[str, Any] = Body(...), resident: int = 0) -> Dict:
    """Загрузить доступы.json из пакета команды — URL, ust резидента, квартира и привязки устройств."""
    if not isinstance(data.get("residents"), list) and not data.get("devices"):
        raise HTTPException(400, "это не похоже на доступы.json: нет residents и devices")
    return bridge().import_access(data, resident)


@router.post("/check")
async def check() -> Dict:
    """Проверить связь (только чтение): стенд, токен, карточки устройств и сверка значений."""
    return await asyncio.to_thread(bridge().check)


@router.post("/publish")
async def publish() -> Dict:
    """Отправить текущее состояние всех привязанных устройств прямо сейчас."""
    b = bridge()
    if b.cfg["mode"] == "off":
        raise HTTPException(400, "интеграция выключена — выберите режим «Пробный» или «На стенд»")
    return {"results": await asyncio.to_thread(b.publish_now)}


@router.get("/debug/difference")
async def debug_difference(hours: int = 24) -> Dict:
    """Открыть в браузере: полный ответ платформы по вашим устройствам (токены не показываются)."""
    return await asyncio.to_thread(bridge().raw_difference, hours)


@router.get("/debug/signals")
async def debug_signals() -> Dict:
    """Открыть в браузере: какие имена сигналов стенд знает для вашей квартиры."""
    return await asyncio.to_thread(bridge().known_signals)


@router.post("/reset-created")
def reset_created() -> Dict:
    """Забыть, какие сигналы уже созданы, — при следующей отправке снова пройдут две фазы."""
    bridge().reset_created()
    return {"ok": True}


@router.get("/scenarios")
def exportable() -> Dict:
    """Какие сценарии R Studio можно завести в autoscripts резидента."""
    cat = Catalog([i.describe() for i in hub().instances.values()])
    out = []
    for doc in storage.scenarios().all():
        sc, _ = analyze(doc, cat)
        if sc is None:
            continue
        u = to_ujin(sc, cat)
        out.append({"id": sc.id, "title": sc.title, "exportable": u["exportable"],
                    "requests": len(u["requests"]), "conditions": u["conditions"],
                    "set_signals": u["set_signals"], "skipped": u["skipped"]})
    return {"items": out}


@router.post("/scenarios/{sid}/push")
async def push(sid: str) -> Dict:
    lib = storage.scenarios()
    if not lib.exists(sid):
        raise HTTPException(404, "сценарий не найден")
    b = bridge()
    if b.ready():
        raise HTTPException(400, b.ready())
    cat = Catalog([i.describe() for i in hub().instances.values()])
    sc, _ = analyze(lib.get(sid), cat)
    if sc is None:
        raise HTTPException(400, "в сценарии есть ошибки")
    u = to_ujin(sc, cat)
    if not u["exportable"]:
        raise HTTPException(400, "эту часть платформа исполнить не сможет: " + "; ".join(u["skipped"][:3]))
    return {"results": await asyncio.to_thread(b.push_scenario, u["requests"])}


@router.get("/remote-scenarios")
async def remote() -> Dict:
    """Сценарии резидента, которые уже есть на платформе (autoscripts/list)."""
    return await asyncio.to_thread(bridge().list_scenarios)
