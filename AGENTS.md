# AGENTS.md

Руководство для агентных кодинг-агентов (Claude/Cursor/Copilot/Cline и т.п.) в репозитории **neptun4hass**.

Интеграция: custom Home Assistant integration для Neptun ProW+ WiFi (SST). Локальный TCP протокол на `:6350`, без облака.

Правила редактора/ассистента:
- Cursor rules (`.cursor/rules/`, `.cursorrules`) — нет
- Copilot rules (`.github/copilot-instructions.md`) — нет

## Команды (Build/Lint/Test)

Быстрые локальные проверки:

```bash
# Python: синтаксис/импорты
python3 -m compileall -q custom_components/neptun4hass

# JSON: translations/strings
python3 -m json.tool custom_components/neptun4hass/strings.json > /dev/null
python3 -m json.tool custom_components/neptun4hass/translations/en.json > /dev/null
python3 -m json.tool custom_components/neptun4hass/translations/ru.json > /dev/null

# Git whitespace
git diff --check
```

Мок протокола (smoke):

```bash
python3 test_server.py
python3 test_client.py 127.0.0.1 6350
```

"Один тест" (single run) против реального устройства:

```bash
python3 test_client.py <IP> 6350
```

CI в GitHub:
- `hassfest`: `.github/workflows/hassfest.yml`
- `hacs/action`: `.github/workflows/hacs.yml`

## Структура репозитория

Код интеграции: `custom_components/neptun4hass/`

Ключевые файлы:
- `custom_components/neptun4hass/neptun_client.py`: async TCP клиент протокола (CRC, TLV, парсинг)
- `custom_components/neptun4hass/coordinator.py`: `DataUpdateCoordinator` (polling, кэш, resync)
- `custom_components/neptun4hass/config_flow.py`: `ConfigFlow` + `OptionsFlow` (IP/Name, опции)
- `custom_components/neptun4hass/registry.py`: enable/disable сущностей линий по `line_in_config`
- `custom_components/neptun4hass/options_sync.py`: mismatch options vs device (persistent_notification)
- `custom_components/neptun4hass/warnings.py`: уведомления (например limited access)
- `custom_components/neptun4hass/{binary_sensor,sensor,switch}.py`: HA платформы
- `custom_components/neptun4hass/brand/`: `icon.png`, `dark_icon.png`, `logo.png`, `dark_logo.png` (+ `@2x` варианты)

## Архитектура

`neptun_client.py` → `coordinator.py` → `entity.py` → platforms (`binary_sensor.py`, `sensor.py`, `switch.py`).

Данные обновляются через coordinator; сущности берут состояние только из `coordinator.data`.

## Протокол (важное)

- TCP `:6350`, каждый запрос = новое соединение (connect → send → recv → close).
- CRC16/CCITT (poly `0x1021`, init `0xFFFF`).
- Запрос: `[0x02, 0x54, 0x51, type, size_hi, size_lo, body..., crc_hi, crc_lo]`
- Ответ:  `[0x02, 0x54, 0x41, type, size_hi, size_lo, body..., crc_hi, crc_lo]`

Основные типы:
- `0x52` SYSTEM_STATE (TLV): device info + flags + wired states
- `0x63` COUNTER_NAME (CP1251, null-separated)
- `0x43` COUNTER_STATE (4 bytes value + 1 byte step на линию)
- `0x4E` SENSOR_NAME (CP1251)
- `0x53` SENSOR_STATE (signal/line/battery/state)
- `0x57` SET_SYSTEM_STATE (fire-and-forget, у реального устройства нет ответа)
- `0xFB` ERROR: устройство отказало в доступе (в коде -> `NeptunAccessDenied`)

SYSTEM_STATE TLV tag `0x53` (7 bytes):
`valve_open, sensor_count, relay_count, cleaning_mode, close_on_offline, line_in_config, status`.

Status bits: `0x01` alarm, `0x02` main battery, `0x04` sensor battery, `0x08` sensor offline.

## Опрос (polling)

- Быстрый цикл: `get_system_state` + `get_counter_values` (+ `get_sensor_states`, если есть wireless).
- Полный опрос: подтягивает имена линий/датчиков. Опция `full_refresh_cycles` делает full refresh раз в N циклов.
- Если `sensor_count` поменялся — coordinator форсирует full refresh, чтобы пересинхронизировать список wireless.

Опции (OptionsFlow):
- `line_in_config`: тип каждой из 4 проводных линий (бит=1 -> counter, 0 -> leak sensor)
- `close_on_offline`: закрывать краны при офлайне беспроводных датчиков (пишется в устройство)
- `scan_interval`: интервал опроса coordinator (min 5s, default 30s)
- `full_refresh_cycles`: полный опрос раз в N циклов (min 1, default 20)

## Критические особенности устройства

- Минимальная пауза между соединениями: `REQUEST_DELAY = 0.5s` (иначе часто `Empty response`).
- Только одно TCP соединение одновременно: мобильное приложение/другой клиент может ломать опрос.
- SET требует ВСЕ поля (`valve_open`, `cleaning_mode`, `close_on_offline`, `line_in_config`), не только изменённые.
- После SET всегда подтверждать изменённые значения чтением `SYSTEM_STATE` с таймаутом.
- `access=false`/`0xFB`: некоторые запросы (имена/счётчики) могут быть запрещены — не валить всю интеграцию, показывать предупреждение.

## Code Style Guidelines

Python/HA:
- Только async IO; не делать blocking network/disk внутри HA loop.
- Соблюдать `DataUpdateCoordinator`: не делать самостоятельные polling loops в entity.

Imports/formatting:
- Порядок imports: stdlib → third-party → `homeassistant.*` → локальные (`from .const import ...`).
- Без автогенерированных больших комментариев; non-obvious логика — короткий англ. комментарий.

Types/naming:
- Type hints обязательны для публичных методов, dataclass полей, flow шагов.
- Keys опций хранить в `custom_components/neptun4hass/const.py`.
- `unique_id` стабильный: `{mac}_{key}`; не менять без migration.

Entities:
- Для проводных линий всегда держим две сущности: `... Leak` и `... Counter`.
- Включение/выключение актуальной сущности делать через entity registry (`registry.py`), чтобы история не терялась.

Error handling/logging:
- `NeptunConnectionError`: transient; допустимы ретраи на `Empty response`.
- `NeptunAccessDenied`: продолжать базовый `SYSTEM_STATE`, использовать persistent_notification (`warnings.py`).
- Логи: info/warn без спама; повторяющиеся проблемы логировать один раз до восстановления.

Translations/UI:
- При добавлении опций/ошибок/полей: обновлять `strings.json` и `translations/en.json`, `translations/ru.json`.
- Сообщения для пользователя — короткие и понятные; технические детали — в лог.

## Релизы

- Версия в `custom_components/neptun4hass/manifest.json`.
- Release workflow: `.github/workflows/release.yml`.
- Тег `vX.Y.Z` должен совпадать с manifest `X.Y.Z`.

## Запуск в Home Assistant

Для ручного теста в HA:
- скопировать `custom_components/neptun4hass/` в `<config>/custom_components/`
- restart HA
- добавить интеграцию через UI (Config Flow)
