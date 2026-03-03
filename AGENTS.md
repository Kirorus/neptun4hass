# AGENTS.md

Информация о проекте для ИИ-агентов (Claude, Cursor, Copilot, Cline и др.).

## Проект

**neptun4hass** — кастомная интеграция Home Assistant для системы защиты от протечек Neptun ProW+ WiFi (производитель SST). Работает по локальному бинарному TCP-протоколу (порт 6350), без облака.

## Структура

```
neptun4hass/
├── custom_components/neptun4hass/   # Интеграция HA
│   ├── __init__.py                  # async_setup_entry / async_unload_entry
│   ├── manifest.json                # domain: neptun4hass, version: 1.0.0
│   ├── config_flow.py               # UI: ввод IP → проверка → MAC как unique_id
│   ├── const.py                     # DOMAIN, порт, типы пакетов, теги, статус-маска
│   ├── neptun_client.py             # Async TCP клиент протокола Neptun (ядро)
│   ├── coordinator.py               # DataUpdateCoordinator, опрос каждые 30с
│   ├── entity.py                    # Базовый класс NeptunEntity
│   ├── binary_sensor.py             # Датчики протечки (проводные + беспроводные) + alarm
│   ├── sensor.py                    # Счётчики воды (м³), сигнал, батарея, статус
│   ├── switch.py                    # Кран (valve), режим уборки (cleaning)
│   ├── strings.json                 # Строки UI
│   └── translations/{en,ru}.json    # Локализация
├── hacs.json                        # Метаданные HACS
├── test_server.py                   # Мок-сервер протокола Neptun
├── test_client.py                   # Тест-скрипт для клиента
├── README.md                        # Документация для пользователей
├── CLAUDE.md                        # Контекст для Claude Code
└── AGENTS.md                        # Этот файл
```

## Архитектура

```
neptun_client.py  →  coordinator.py  →  entity.py  →  binary_sensor.py
   (TCP-протокол)     (опрос 30с)       (базовый)     sensor.py
                                                       switch.py
```

**Ключевой файл — `neptun_client.py`**. Содержит всю логику протокола:
- CRC-16/CCITT (полином 0x1021, начальное значение 0xFFFF)
- Формирование и парсинг бинарных пакетов (TLV-формат для SYSTEM_STATE)
- Dataclass-ы: `DeviceData`, `WiredSensor`, `WirelessSensor`
- Методы: `get_system_state()`, `get_counter_names()`, `get_counter_values()`, `get_sensor_names()`, `get_sensor_states()`, `get_full_state()`, `set_state()`

## Протокол Neptun ProW+ WiFi

- **Транспорт**: TCP, порт 6350, каждый запрос — отдельное соединение
- **Формат запроса**: `[0x02, 0x54, 0x51, тип, размер_hi, размер_lo, ...тело, crc_hi, crc_lo]`
- **Формат ответа**: `[0x02, 0x54, 0x41, тип, размер_hi, размер_lo, ...тело, crc_hi, crc_lo]`

### Типы пакетов

| Код | Имя | Описание |
|-----|-----|----------|
| `0x52` | SYSTEM_STATE | Информация об устройстве + состояние проводных линий. Ответ — TLV-теги |
| `0x63` | COUNTER_NAME | Имена проводных линий (CP1251, null-terminated) |
| `0x43` | COUNTER_STATE | Значения счётчиков (4B значение + 1B шаг на линию) |
| `0x4E` | SENSOR_NAME | Имена беспроводных датчиков (CP1251, null-terminated) |
| `0x53` | SENSOR_STATE | Состояние беспроводных (1B сигнал + 1B линия + 1B батарея + 1B статус) |
| `0x57` | SET_SYSTEM_STATE | Управление: кран, уборка, офлайн, конфиг линий. **Без ответа (fire-and-forget)** |

### TLV-теги в SYSTEM_STATE

| Тег | Содержимое |
|-----|-----------|
| `0x49` (73) | Тип устройства (2B) + версия прошивки (3B: X.Y.Z) |
| `0x4E` (78) | Имя устройства (ASCII) |
| `0x4D` (77) | MAC-адрес (ASCII) |
| `0x41` (65) | Флаг доступа (1B) |
| `0x53` (83) | Состояние: кран(1B), кол-во датчиков(1B), реле(1B), уборка(1B), офлайн(1B), конфиг линий(1B), статус(1B) |
| `0x73` (115) | Состояние проводных линий (4B, по одному на линию) |

### Битовая маска статуса

| Бит | Значение |
|-----|----------|
| `0x01` | ALARM — протечка |
| `0x02` | MAIN_BATTERY — основная батарея разряжена |
| `0x04` | SENSOR_BATTERY — батарея датчика разряжена |
| `0x08` | SENSOR_OFFLINE — датчик не на связи |

### Цепочка опроса

```
get_system_state → (0.5с) → get_counter_names* → (0.5с) → get_counter_values → (0.5с) → get_sensor_names* → (0.5с) → get_sensor_states

* имена кешируются после первого запроса
```

## Критические особенности (из тестирования на реальном устройстве)

1. **Пауза 0.5с между соединениями** — без неё устройство возвращает пустой ответ или сбрасывает соединение
2. **SET_SYSTEM_STATE (0x57) — fire-and-forget** — устройство НЕ отправляет ответ. Мок-сервер отвечает, реальное устройство — нет
3. **Только одно соединение одновременно** — устройство не поддерживает параллельные TCP-сессии
4. **SET требует ВСЕ поля** — valve, dry, close_on_offline, line_in_config. Нельзя отправить только изменённое
5. **Таймаут чтения 10с** — устройство может отвечать медленно, особенно после переподключения к WiFi
6. **Интервал опроса >= 5с** — при более частом опросе устройство может зависнуть. По умолчанию 30с
7. **Строки в CP1251** — имена датчиков и линий

## Источники протокола

Протокол реверс-инженирен из двух проектов:
- **`neptun2mqtt`** (`github.com/ptvoinfo/neptun2mqtt`) — полная реализация протокола на Python (threading/socket). Файл `neptun.py` — основной источник логики парсинга и формирования пакетов. Содержит баг в строке 628: парсинг значений счётчиков использует `data[offset]` для всех 4 байт вместо `data[offset+0..+3]` — исправлено в нашем клиенте.
- **`neptun_homeassistant`** (`github.com/allovaro/neptun_homeassistant`) — устаревшая HA-интеграция (YAML, без config flow). Использована как альтернативная проверка смещений полей и для тест-сервера.

## Соглашения

- Имя интеграции: `neptun4hass` (domain, пакет, HACS, UI title)
- Имя устройства: `Neptun ProW+ WiFi` (описания, документация, docstrings)
- Производитель в DeviceInfo: `Neptun/SST`
- Модель в DeviceInfo: `ProW+ WiFi`
- Язык кода и комментариев: английский
- Язык документации: русский (README), английский (CLAUDE.md, код)

## Тестирование

```bash
python3 test_server.py                    # мок-сервер на 127.0.0.1:6350
python3 test_client.py [host] [port]      # тест клиента (по умолчанию localhost)
```

Для тестирования в HA: скопировать `custom_components/neptun4hass/` в `config/custom_components/`, перезапустить HA, добавить через UI.
