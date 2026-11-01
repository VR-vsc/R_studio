"""Блок 6: истории демо доигрываются и действительно запускают сценарии."""
import asyncio
import os
import tempfile

os.environ.setdefault("RSTUDIO_DATA", tempfile.mkdtemp(prefix="rstudio-test-"))

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402,F401
from app import demo as demo_mod  # noqa: E402
from app.demo import STORIES, demo  # noqa: E402
from app.emulation import hub  # noqa: E402
from app.engine import engine  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


def play(sid):
    """Проиграть историю мгновенно: паузы → такты модели."""
    async def fake_sleep(sec):
        hub().step(max(1, int(sec * hub().speed)))
    orig = demo_mod.asyncio.sleep
    demo_mod.asyncio.sleep = fake_sleep
    try:
        hub().reset_to_seed()
        engine().clear()
        hub().running = False
        asyncio.run(demo()._run(sid, STORIES[sid]))
    finally:
        demo_mod.asyncio.sleep = orig
        hub().set_clock(running=False, speed=1)
    return {r["scenario"] for r in engine().runs if r["status"] != "skipped"}


def test_every_story_triggers_its_scenarios():
    assert "leak_protect" in play("leak")
    assert "fire_evacuation" in play("fire")
    ran = play("comfort")
    assert {"fresh_air", "window_heating", "window_closed"} <= ran
    assert "guest_arrival" in play("guest")
    assert demo().current["done"]


def test_api_overview_and_demo():
    with TestClient(fastapi_app) as c:
        o = c.get("/api/overview").json()
        assert o["devices"] >= 9 and o["instances"] == 9 and o["scenarios"] >= 7
        lst = c.get("/api/demo").json()["stories"]
        assert {s["id"] for s in lst} == {"leak", "fire", "comfort", "guest"}
        assert c.post("/api/demo/nope/start").status_code == 404
        assert c.post("/api/demo/leak/start").json()["ok"]
        assert c.post("/api/demo/stop").json()["ok"]
        c.post("/api/emu/reset")
