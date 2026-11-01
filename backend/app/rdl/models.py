"""RDL — R Studio Device Language: единый язык описания устройства.

Один JSON-документ описывает всё, что нужно и конструктору, и эмулятору,
и редактору сценариев, и платформе Ujin:

    {
      "rdl": "1.0",
      "id": "water_valve",            # семейство (латиница, без дефисов)
      "title": "Кран подачи воды",
      "category": "plumbing",
      "signals": [ ... ],             # что устройство измеряет / умеет / как настроено
      "vars": {"left": 0},            # внутренняя память физики (на платформу не уходит)
      "behavior": [ ... ],            # физика: правила «когда → сделать»
      "events": [ ... ]               # события для сценариев («протечка обнаружена»)
    }

Группы сигналов (для людей и для Ujin):
    property     📊 свойство   — что устройство измеряет        (Ujin: r)
    capability   🎛 возможность — чем можно управлять           (Ujin: rw / w)
    setting      ⚙️ настройка   — пороги, таймеры, периоды       (Ujin: rw, kind=setting)
    environment  🌍 окружение   — физический мир для эмулятора   (на платформу не публикуется)
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

NAME_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
ID_PATTERN = r"^[a-z][a-z0-9_]{1,40}$"
ON_PATTERN = r"^(tick|start|command|command:[a-z][a-z0-9_]*|change:[a-z][a-z0-9_]*)$"

Group = Literal["property", "capability", "setting", "environment"]
SigType = Literal["bool", "number", "enum", "text", "button"]
Access = Literal["r", "rw", "w"]
Severity = Literal["info", "warning", "critical"]

DEFAULT_ACCESS: Dict[str, str] = {
    "property": "r",
    "capability": "rw",
    "setting": "rw",
    "environment": "w",
}

GROUP_TITLES = {
    "property": "Свойства",
    "capability": "Возможности",
    "setting": "Настройки",
    "environment": "Окружение (эмулятор)",
}

CATEGORIES = {
    "safety": "Безопасность",
    "plumbing": "Вода",
    "climate": "Климат",
    "energy": "Энергия и учёт",
    "light": "Свет",
    "access": "Доступ и въезд",
    "other": "Другое",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SignalSpec(_Strict):
    name: str = Field(pattern=NAME_PATTERN, description="Техническое имя (латиница, цифры, _)")
    title: str = Field(min_length=1, max_length=80, description="Название по-русски")
    group: Group = "property"
    type: SigType = "number"
    access: Optional[Access] = Field(None, description="Если не задан — по группе")
    unit: str = Field("", max_length=16)
    min: Optional[float] = None
    max: Optional[float] = None
    default: Union[bool, int, float, str] = 0
    options: Dict[str, str] = Field(default_factory=dict,
                                    description="Подписи значений: {\"0\":\"нет\",\"1\":\"протечка\"}")
    precision: int = Field(2, ge=0, le=6, description="Знаков после запятой")
    monotonic: bool = Field(False, description="Только растёт (счётчики учёта)")
    description: str = Field("", max_length=300)

    @property
    def effective_access(self) -> str:
        if self.type == "button":
            return self.access or "w"
        return self.access or DEFAULT_ACCESS[self.group]


class ActionSpec(_Strict):
    """Действие правила. Ровно одно из: set (присвоить) или log (сообщение)."""
    set: Optional[str] = Field(None, description="Сигнал или переменная")
    to: Union[str, int, float, bool, None] = Field(None, description="Выражение значения")
    after: Optional[float] = Field(None, ge=0, le=86400, description="Отложить на N секунд")
    hold: Optional[float] = Field(None, gt=0, le=86400, description="Через N секунд вернуть")
    then: Union[str, int, float, bool, None] = Field(None, description="Значение возврата для hold")
    log: Optional[str] = Field(None, max_length=200, description="Текст в журнал; {имя} — подстановка")


class RuleSpec(_Strict):
    id: str = Field("", max_length=40)
    title: str = Field("", max_length=120)
    on: str = Field("tick", pattern=ON_PATTERN,
                    description="tick | start | command | command:<сигнал> | change:<сигнал>")
    when: Union[str, int, bool, None] = Field(None, description="Условие (выражение)")
    do: List[ActionSpec] = Field(min_length=1)


class Stimulus(_Strict):
    signal: str = Field(pattern=NAME_PATTERN)
    value: Union[int, float]


class EventSpec(_Strict):
    name: str = Field(pattern=NAME_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    when: str = Field(description="Событие возникает, когда условие становится истинным")
    severity: Severity = "info"
    stimulus: List[Stimulus] = Field(default_factory=list,
                                     description="Как вызвать событие в эмуляторе (для автопроверки сценариев)")


class DeviceSpec(_Strict):
    rdl: Literal["1.0"] = "1.0"
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1, max_length=80)
    model: str = Field("", max_length=60, description="Модель Ujin; по умолчанию rs_<id>")
    category: str = "other"
    icon: str = Field("device", max_length=32)
    description: str = Field("", max_length=500)
    version: str = Field("1.0", max_length=16)
    signals: List[SignalSpec] = Field(min_length=1)
    vars: Dict[str, Union[int, float, str]] = Field(default_factory=dict)
    behavior: List[RuleSpec] = Field(default_factory=list)
    events: List[EventSpec] = Field(default_factory=list)

    @property
    def effective_model(self) -> str:
        return self.model or f"rs_{self.id}"

    def signal(self, name: str) -> Optional[SignalSpec]:
        for s in self.signals:
            if s.name == name:
                return s
        return None
