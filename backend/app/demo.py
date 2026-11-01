"""Блок 6 — режим «Демо»: готовые истории для показа жюри и записи видео.

История — последовательность шагов «подпись + воздействие на квартиру». Подписи приходят
в интерфейс через WebSocket (сообщение `demo`) и показываются крупной строкой над квартирой,
а сценарии R Studio срабатывают сами — история только меняет «мир вокруг» и жмёт кнопки,
как это сделал бы человек.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from .emulation import EmulationError, hub

# шаг: (пауза перед шагом в секундах реального времени, подпись, действие или None)
# действие: ("act", instance, signal, value) | ("run", scenario_id) | ("speed", x)
STORIES: Dict[str, Dict[str, Any]] = {
    "leak": {
        "title": "Протечка в ванной",
        "about": "Вода на полу → кран перекрыт, сирена, уведомление жителю и в УК",
        "steps": [
            (0, "Обычный вечер. Квартира работает, R Studio следит за всеми устройствами.", ("speed", 5)),
            (3, "Под стиральной машиной появилась вода — меняем «мир вокруг» датчика.", ("act", "bath_leak", "wet", 1)),
            (5, "Датчик подтвердил протечку → сценарий «Защита от протечки» перекрыл кран и включил сирену.", None),
            (5, "Житель и УК получили тревогу. Заслонка крана закрылась за 4 секунды — как у настоящего привода.", None),
            (5, "Воду убрали — датчик снова сухой. Сирена выключится сама через минуту.", ("act", "bath_leak", "wet", 0)),
        ],
    },
    "fire": {
        "title": "Пожар на кухне",
        "about": "Дым → сирена, свет для эвакуации, стоп притока, въезд для пожарных",
        "steps": [
            (0, "На кухне начинает идти дым.", ("speed", 5)),
            (1, "Задымлённость растёт — пожарный датчик набирает дым в камеру.", ("act", "kitchen_smoke", "smoke_density", 90)),
            (6, "Порог превышен → «Пожар: эвакуация»: сирена, свет 100 %, приток воздуха остановлен, шлагбаум открыт.", None),
            (6, "Всё это — одно правило, собранное в редакторе мышкой, без строчки кода.", None),
            (4, "Проветрили — дым ушёл.", ("act", "kitchen_smoke", "smoke_density", 0)),
        ],
    },
    "comfort": {
        "title": "Комфорт и экономия",
        "about": "Душно → вентиляция в авто; окно открыто → отопление на паузе",
        "steps": [
            (0, "Вечером в спальне собрались гости, вентиляция в ручном режиме.", ("act", "bedroom_vent", "mode", 1)),
            (2, "Людей стало 15 — CO₂ быстро растёт.", ("act", "bedroom_vent", "people", 15)),
            (1, "Ускоряем время ×60, чтобы не ждать.", ("speed", 60)),
            (8, "CO₂ выше 1200 → «Душно в спальне» перевёл вентиляцию в авто, скорость растёт сама.", ("speed", 5)),
            (3, "В гостиной открыли окно проветрить.", ("act", "living_thermo", "window_open", 1)),
            (4, "«Окно открыто — пауза отопления»: термостат не греет улицу.", None),
            (4, "Окно закрыли — второй сценарий вернул обогрев.", ("act", "living_thermo", "window_open", 0)),
            (3, "Гости ушли.", ("act", "bedroom_vent", "people", 1)),
        ],
    },
    "guest": {
        "title": "Встречаем гостя",
        "about": "Кнопка в приложении → шлагбаум открыт, через 10 с свет в гостиной",
        "steps": [
            (0, "Житель ждёт гостя и нажимает в приложении кнопку «Встречаем гостя».", ("speed", 5)),
            (1, "Шлагбаум поднимается, держит паузу и закроется сам.", ("run", "guest_arrival")),
            (4, "Под стрелой машина — шлагбаум не опустится, пока проезд не свободен.", ("act", "yard_barrier", "obstacle", 1)),
            (4, "Машина проехала.", ("act", "yard_barrier", "obstacle", 0)),
            (3, "Через 10 секунд модели включился свет в гостиной — гость дома.", None),
        ],
    },
}


class Demo:
    def __init__(self) -> None:
        self.task: Optional[asyncio.Task] = None
        self.current: Optional[dict] = None

    def list(self) -> List[dict]:
        return [{"id": k, "title": v["title"], "about": v["about"], "steps": len(v["steps"]),
                 "seconds": sum(s[0] for s in v["steps"]) + 4} for k, v in STORIES.items()]

    async def _run(self, sid: str, story: dict) -> None:
        from .engine import engine
        h = hub()
        total = len(story["steps"])
        try:
            h.set_clock(running=True)
            for i, (pause, caption, action) in enumerate(story["steps"]):
                await asyncio.sleep(pause)
                self.current = {"story": sid, "title": story["title"], "step": i + 1, "total": total,
                                "caption": caption, "done": False}
                h.broadcast("demo", self.current)
                if action is None:
                    continue
                try:
                    if action[0] == "act":
                        h.act(action[1], action[2], action[3], "демо")
                    elif action[0] == "run":
                        engine().run_now(action[1])
                    elif action[0] == "speed":
                        h.set_clock(speed=action[1])
                except EmulationError as exc:
                    h.log("demo", f"шаг пропущен: {exc}")
            await asyncio.sleep(4)
            h.set_clock(speed=1)
            self.current = {"story": sid, "title": story["title"], "step": total, "total": total,
                            "caption": "Готово. Трасса каждого запуска — во вкладке «Сценарии» справа.", "done": True}
            h.broadcast("demo", self.current)
        except asyncio.CancelledError:
            h.set_clock(speed=1)
            self.current = None
            h.broadcast("demo", {"story": sid, "done": True, "caption": "", "stopped": True})
            raise

    def start(self, sid: str) -> dict:
        if sid not in STORIES:
            raise KeyError(sid)
        self.stop()
        from .engine import engine
        hub().reset_to_seed()  # каждая история — с чистой квартиры и предсказуемым результатом
        engine().clear()
        self.task = asyncio.get_running_loop().create_task(self._run(sid, STORIES[sid]))
        return {"ok": True, "story": sid}

    def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = None


_demo: Optional[Demo] = None


def demo() -> Demo:
    global _demo
    if _demo is None:
        _demo = Demo()
    return _demo
