# Эмуляторы устройств Ujin (каркас)

> **Твой стенд: тест-ОАЭ** (API `https://api-uae-test.ujin.tech/api`). Все адреса в этом документе уже переведены на него; где осталось слово «preprod» (история прогонов) — читай «тест-ОАЭ». Устройства: команда запуска в брошюре (`--ust-auth`), dev-токен не нужен.

Python 3.8+, только стандартная библиотека. Сетевые вызовы по умолчанию в `dry-run`
(печать + журнал) — работать можно без стенда.

## Быстрый старт

```bash
# 8 тиков лифта, без сети
python main.py elevator --ticks 8 --interval 0 --floors 5

# завести устройство на стенде и публиковать сигналы вживую
python main.py thermostat --live --token dev-<serial>-<token> \
  --base-url https://<стенд> --register --apartment-id <id>

# принимать команды платформы на HTTP-порту + веб-панель (формат сервера опроса Ujin)
python main.py barrier --port 8099 --live --token ...
curl "http://localhost:8099/?data={\"recv\":[{\"command\":\"management\",\"id\":\"5\",\"open_cmd\":1}]}"
# панель: http://localhost:8099/ — таблица сигналов + форма команды; /state — JSON
```

Тесты (без сети):

```bash
python -m unittest discover -s tests
```

# Приём команды с платформы (поллинг, вариант без публичного HTTP)

```bash
python live_loop.py --sn <serialnumber> --ust <ust-token> \
  --model parkcloud_device --dict-prefix integrations_devices_ --once
```

Цикл: `get-device-info` → `pending_tasks()` (читает `task` сигнала) → исполнение
→ подтверждение `group-update-device-signal`. **Важно:** платформа отдаёт
task-команду только для сигналов `signal_management<>'r'`; автословари — `'r'`,
поэтому на preprod команда вниз заблокирована (детали:
`research/ujin-hackathon/preprod-evidence/2026-10-13-command-path.md`).

## WebSocket (контракт МП, ujin-ios)

```bash
python -c "import ws_client; print(ws_client.fetch_wss_address(
  'https://api-uae-test.ujin.tech/api', open('token.txt').read()...))"
```

`ws_client.py` повторяет контракт iOS-приложения (`Common/Services/DeviceManager/`):
адрес — `GET /api/devices/wss/?token=<ust>` → `data.wss[0]` (параметр именно
`token=`; на `user_token` шлюз отдаёт гостя -17000000); auth после open —
`{"token":...,"event":"authenticate","signals":true}`; команда —
`{"event":"setValue","devices":[{"id":uniq,"sn":<число>,"signals":[{"name","value"}]}]}`;
эхо — `setValue` с тем же `id` (`status=failed` = отказ). Входящие сигналы
матчатся по числовому `sn` и проходят через `Device.apply_ws_signal`
(управляемый = команда, читаемый = удалённое показание).
**Состояние preprod:** WS-сервер не настроен (`WSS_URL` пуст, `devices/wss/`
отдаёт `wss:[""]`, у устройств кейса `apartment_id=0`) — рабочий транспорт
пока pull (`live_loop.py`). Детали:
`research/ujin-hackathon/preprod-evidence/2026-10-14-websocket.md`.

## Структура

| Файл | Роль |
|---|---|
| `core.py` | `Signal` (declaration: control/management/kind), `Device` (тики, грязные сигналы, `announce`, приём `{"recv":[...]}`), `CommandServer` (+веб-панель `/`, `/state`, `/declaration`, `/command`, `/shutdown`) |
| `ujin_client.py` | клиент API: import_device (create-update, update/group-update-signal, hide) + autoscripts (signals, edit, list, activate); `dry_run=True` по умолчанию |
| `devices/leak_sensor.py` | датчик протечки (батарея, тампер, самотест) |
| `devices/barrier.py` | шлагбаум (авто-закрытие `hold_time`, реверс по препятствию, джем-авария) |
| `devices/thermostat.py` | термостат (гистерезис ±0.5, режимы, дрейф к окружающей) |
| `devices/elevator.py` | лифт (вызовы, движение этаж-за-этажом, `floor_changed`, авария-стоп) |
| `devices/leak_hub.py` | композит: хаб + 3 внутренних датчика (коммутация вне Ujin) |
| `devices/counter.py` | **Учёт** (э/в/тепло): тарифы, мощность, реле нагрузки — самый живой класс preprod |
| `devices/ventilation.py` | **Вентиляция** (приточка): CO2/PM2.5, авто-режим по цели |
| `devices/fire.py` | **ПОЖС**: задымлённость, порог, тампер, самотест |
| `devices/light.py` | **Свет/реле**: яркость, энергия, авто-выключение |
| `live_loop.py` | pull-цикл приёма команд платформы (get-device-info → task → исполнение → подтверждение) |
| `ws_client.py` | WS-клиент по контракту МП (auth/setValue/эхо) + `WsDeviceHub` поверх FSM |
| `tests/test_devices.py` | 24 теста конечных автоматов, клиента, команды по HTTP |
| `tests/test_families.py` | 10 тестов новых семейств + групп `signal.group` |
| `tests/test_ws_client.py` | 8 тестов WS-протокола и хаба (офлайн) |
| `tests/test_client_publish.py` | 3 теста payload'а публикаций (рудимент wire_value) |
| `tests/test_new_device.py` | 5 тестов генератора new_device.py |
| `tests/test_booklet.py` | 4 теста брошюры (credentials → HTML) |
| `tests/test_provision.py` | 9 тестов плана провижининга, генераторов (secrets), locality/provider |
| `tests/test_provision_live.py` | 4 теста идемпотентности `--live` (cos/комплы/резиденты, сетьзаглушена) |
| `tests/test_live_loop.py` | 4 теста дедупа задач pull-цикла (task_dt) |

Итого 71 unittest, все офлайн. Оговорка: живой WS-зонд (`ws_client.probe`)
требует `pip install websockets` — единственная внешняя либа, импортируется
лениво; ядро и тесты от неё не зависят.

## Три группы сигналов (для людей, не для протокола)

`Signal.group` (в `declaration()`): **Свойства** (property, только читаю),
**Возможности** (capability, `rw/w` — чем управляю), **Настройки** (setting,
пороги/таймеры/периоды; kind=`setting`). Панель и START.md.group по этому же.
Новое семейство = файл в `devices/`, минимум по одному сигналу property+capability.

## Сигнальная декларация

`device.declaration()` отдаёт JSON-описание сигналов (name/title/control/management/kind/
group/диапазоны/layout) — источник для конструктора устройств и для сида `signal_dict`.
Маппинг kind: `property`=состояние (`r`), `capability`=управление (`rw/w`),
`setting`=настройка, `system`=обвязка.
Детали — `../../../research/ujin-hackathon/device-templates.md`,
`../../../research/ujin-hackathon/gap-analysis.md`.

## Как подключиться к живому стенду (когда будет)

1. Получить `dev-token` якоря-шлюза (не самого устройства! —
   `../../../research/ujin-hackathon/gap-analysis.md`, пункт 1).
2. `--register --apartment-id <тестовая квартира>` — иначе привязка `--building-id`/`path`.
3. Для команд «вниз»: базовый путь — не HTTP, а опрос задачи (`difference`/`signal_task_value`),
   см. `../../../research/ujin-hackathon/gap-analysis.md` пункт 7; `CommandServer` — продвинутый путь, требует доступности
   эмулятора из облака и прописанного `device_first_server`.
4. Сигнальные атрибуты (show_window/control) авто-дефолтятся в `text/r/show_window=0` —
   доводка словаря обязательна (`../../../research/ujin-hackathon/bms-display.md`).
5. Сценарии: `client.autoscripts_signals/edit/activate` (ust-токен) — условие
   `when:device-<sn>:<signal>=<value>`, действие `device-<sn>:<signal>:<value>[:hold]`.

## Своё устройство

0. Быстрее — генератор: `python new_device.py valve --title "Клапан" [--clone light]`
   (создаст `devices/valve.py` с тремя группами, зарегистрирует, подскажет запуск).
1. Класс в `devices/`, наследник `Device`: добавить `Signal`-ы, реализовать `tick()` и
   `on_command()`.
2. Зарегистрировать в `devices/__init__.py:REGISTRY` (генератор делает это сам).
3. Тест — конечный автомат без сети (см. `tests/test_devices.py`).
