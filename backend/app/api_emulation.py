"""Блок 2 — API эмуляторов: квартира, такты, команды, окружение, события, WebSocket."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .emulation import SPEEDS, EmulationError, hub

router = APIRouter(prefix="/api/emu", tags=["эмуляторы"])

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def _err(exc: Exception):
    raise HTTPException(400, str(exc))


@router.get("/state")
async def state() -> Dict:
    """Полный снимок: часы, устройства квартиры со значениями, последние события."""
    return hub().snapshot()


class Clock(BaseModel):
    running: Optional[bool] = None
    speed: Optional[float] = None


@router.post("/clock")
async def clock(c: Clock) -> Dict:
    try:
        hub().set_clock(c.running, c.speed)
    except EmulationError as e:
        _err(e)
    return {"t": hub().t, "running": hub().running, "speed": hub().speed, "speeds": SPEEDS}


@router.post("/step")
async def step(n: int = Query(1, ge=1, le=3600)) -> Dict:
    """Прокрутить N секунд модели мгновенно (удобно для демо и тестов)."""
    hub().step(n)
    return {"t": hub().t}


class Act(BaseModel):
    signal: str
    value: Any


@router.post("/instances/{iid}/act")
async def act(iid: str, a: Act) -> Dict:
    """Команда устройству (возможность/настройка) или изменение окружения."""
    try:
        return hub().act(iid, a.signal, a.value, "пульт")
    except EmulationError as e:
        _err(e)


@router.get("/instances/{iid}/ujin")
async def ujin_poll_server(iid: str, data: str = Query(...)) -> Dict:
    """Путь B Ujin: GET <device_first_server>/?data={"recv":[{"command":"management","id":..,"<signal>":v}]}."""
    try:
        return hub().recv(iid, json.loads(data))
    except (EmulationError, ValueError) as e:
        return {"error": 2, "message": str(e)}


class InstanceIn(BaseModel):
    id: str = Field(pattern=ID_RE.pattern)
    device_id: str
    title: str = ""
    room: str = ""
    ujin: Dict[str, str] = {}


@router.post("/instances")
async def add_instance(cfg: InstanceIn) -> Dict:
    try:
        return hub().add(cfg.model_dump()).describe()
    except EmulationError as e:
        _err(e)


@router.patch("/instances/{iid}")
async def update_instance(iid: str, patch: Dict[str, Any] = Body(...)) -> Dict:
    try:
        return hub().update(iid, patch).describe()
    except EmulationError as e:
        _err(e)


@router.delete("/instances/{iid}")
async def delete_instance(iid: str) -> Dict:
    try:
        hub().remove(iid)
    except EmulationError as e:
        _err(e)
    return {"ok": True}


@router.post("/restart")
async def restart(iid: Optional[str] = None) -> Dict:
    """Вернуть устройство (или всю квартиру) в начальное состояние."""
    hub().restart(iid)
    if iid is None:
        from .engine import engine
        engine().clear()
    return {"ok": True}


@router.post("/reset")
async def reset() -> Dict:
    """Вернуть квартиру к исходному составу (9 устройств) и обнулить часы."""
    hub().reset_to_seed()
    from .engine import engine
    engine().clear()
    return {"ok": True}


@router.get("/events")
async def events(limit: int = Query(100, ge=1, le=400)) -> Dict:
    return {"events": list(hub().events)[-limit:], "logs": list(hub().logs)[-limit:]}


@router.websocket("/ws")
async def ws(sock: WebSocket):
    """Живой поток: snapshot → values/event/log/clock/tick."""
    await sock.accept()
    h = hub()
    q = h.subscribe()
    try:
        await sock.send_json({"type": "snapshot", **h.snapshot()})
        while True:
            msg = await q.get()
            if msg["type"] == "tick":
                continue  # такт и так виден в values
            await sock.send_json(msg)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        h.unsubscribe(q)
