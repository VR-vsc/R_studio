"""Блок 6 — API главной страницы и режима «Демо»."""
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, HTTPException

from . import storage
from .demo import demo
from .emulation import hub
from .engine import engine
from .ujin import bridge

router = APIRouter(prefix="/api", tags=["обзор и демо"])


@router.get("/overview")
def overview() -> Dict:
    """Сводка для главной: что есть в R Studio прямо сейчас."""
    h, e, b = hub(), engine(), bridge()
    scen = storage.scenarios().all()
    st = b.state()
    published = sum((d.get("status") or {}).get("published", 0) for d in st["devices"])
    return {
        "devices": len(storage.devices().ids()),
        "instances": len(h.instances),
        "rooms": len({i.cfg.get("room") for i in h.instances.values()}),
        "scenarios": len(scen),
        "scenarios_on": sum(1 for s in scen if s.get("enabled", True)),
        "runs": len(e.runs),
        "notifications": len(e.notifications),
        "events": len(h.events),
        "t": h.t, "day_start": h.day_start, "running": h.running,
        "ujin": {"mode": st["cfg"]["mode"], "bound": sum(1 for d in st["devices"] if d["ext"]),
                 "published": published, "ready": st["ready"]},
        "demo": demo().current,
    }


@router.get("/demo")
def stories() -> Dict:
    return {"stories": demo().list(), "current": demo().current}


@router.post("/demo/{sid}/start")
async def start(sid: str) -> Dict:
    try:
        return demo().start(sid)
    except KeyError:
        raise HTTPException(404, "нет такой истории")


@router.post("/demo/stop")
async def stop() -> Dict:
    demo().stop()
    return {"ok": True}
