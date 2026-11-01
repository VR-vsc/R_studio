"""R Studio — точка входа: `uvicorn app.main:app --port 8000` (из папки backend)."""
from __future__ import annotations

import os

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api_devices import router as devices_router
from .api_emulation import router as emulation_router
from .api_scenarios import router as scenarios_router
from .api_ujin import router as ujin_router
from .api_demo import router as demo_router
from .emulation import hub
from .engine import engine
from .ujin import bridge


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine()               # сценарии слушают квартиру с первого такта
    hub().start()          # квартира живёт, пока работает сервер
    bridge().start()       # мост в Ujin OS (режим выбирается в разделе «Ujin»)
    yield
    await bridge().stop()
    await hub().stop()


app = FastAPI(title="R Studio API", version=__version__, lifespan=lifespan,
              description="Редактор сценариев умных устройств на базе Ujin OS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(devices_router)
app.include_router(emulation_router)
app.include_router(scenarios_router)
app.include_router(ujin_router)
app.include_router(demo_router)


@app.get("/api/health")
def health():
    return {"ok": True, "app": "R Studio", "version": __version__}


_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = os.path.join(_DIST, path)
        if path and os.path.isfile(f):
            return FileResponse(f)
        return FileResponse(os.path.join(_DIST, "index.html"))
