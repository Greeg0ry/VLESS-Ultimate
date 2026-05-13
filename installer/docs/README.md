# VLESS Ultimate Installer

Автоматический установщик VPN-сервера на базе **Xray-core** с поддержкой VLESS+REALITY и VLESS+xHTTP+TLS.

---

## Что делает скрипт

Устанавливает и настраивает:
- **Xray-core** (VLESS + TCP + REALITY или VLESS + xHTTP + TLS)
- **Nginx** (для маскировки трафика или HTTP→HTTPS редирект)
- **Certbot** (SSL-сертификат Let's Encrypt)
- **Fail2ban** (защита от перебора)
- **UFW** (файервол)
- **DNSCrypt-proxy** (шифрование DNS)
- **Cloudflare WARP** (выход через WARP)
- **AmneziaWG** (WireGuard с обфускацией)
- **Split tunneling** (раздельный трафик для заблокированных ресурсов РФ)
- **AS-маршрутизация** (управление трафиком на уровне ASN через RIPE NCC)
- Диагностика, мониторинг, backup/rollback, автообновление Xray
- Автоматический плановый backup по расписанию
- Управление ротацией логов
- Экспорт клиентских конфигов (Clash Meta, Sing-box)

---

## Поддерживаемые ОС

| ОС | Версии |
|----|--------|
| Ubuntu | 20.04, 22.04, 24.04 |
| Debian | 11, 12, 13 |

**Минимальные требования:** 512 МБ RAM, Python 3.12+

**Рекомендуемые:** 2+ ГБ RAM

---

## Быстрый запуск

```bash
# Стандартный способ
sudo python3 install.py

# Альтернативный (модульный)
sudo python3 -m installer.main
```

---

## Основные режимы установки

| Режим | Описание |
|-------|----------|
| **A — одиночный сервер** | VLESS-сервер на одной машине |
| **B — каскад (chained)** | Российский VPS → зарубежный VPS |

### Протоколы

| Протокол | Описание |
|----------|----------|
| **VLESS+REALITY** | Маскировка под HTTPS-сайт, без TLS-сертификата |
| **VLESS+xHTTP+TLS** | HTTPS-туннель с настоящим сертификатом |

---

## Где лежат конфиги

| Файл | Назначение |
|------|-----------|
| `/etc/xray/config.json` | Основной конфиг Xray |
| `/etc/nginx/sites-available/<домен>` | Конфиг Nginx |
| `/etc/letsencrypt/live/<домен>/` | TLS-сертификаты |
| `/var/lib/xray-installer/state.json` | Состояние установщика |
| `/etc/xray/split_tunnel_custom.json` | Пользовательские правила split tunneling |
| `/etc/xray/as_direct_list.json` | Список активных AS-маршрутов |
| `/etc/xray/as_direct_<ASN>.txt` | Кэш префиксов конкретного AS |
| `/var/lib/xray-installer/asn_prefix_cache.sqlite3` | SQLite-кэш ASN-префиксов |
| `/root/xray-client-configs/` | Экспортированные конфиги Clash Meta / Sing-box |

---

## Где лежат логи

| Файл | Что пишется |
|------|-------------|
| `/var/log/vless-install.log` | Лог установщика |
| `/var/log/xray/access.log` | Лог доступа Xray |
| `/var/log/xray/error.log` | Лог ошибок Xray |
| `/var/log/xray-changes.log` | История изменений конфигов |
| `/var/log/xray-scheduled-backup.log` | Лог планового автобэкапа |

---

## Backup и Rollback

Backup создаётся автоматически перед каждым изменением конфига.

```bash
# Через меню
sudo python3 install.py
# → Управление → Backup/Rollback

# Просмотр бэкапов
ls /var/backups/xray/

# Ручной rollback (Python)
python3 -c "
from installer.core.backup import perform_rollback
perform_rollback('20240513_120000')  # замени на нужную дату
"
```

---

## Проверка статуса

```bash
# Быстрый статус без меню
sudo python3 install.py --status

# Статус сервисов вручную
systemctl status xray
systemctl status nginx

# Лог Xray в реальном времени
journalctl -u xray -f

# Версия Xray
/usr/local/bin/xray version
```

---

## Диагностика

```bash
# Запустить через меню
sudo python3 install.py
# → Диагностика → Полная диагностика

# Python API
python3 -c "
from installer.diagnostics.health import run_full_health_check
run_full_health_check(domain='yourdomain.com', server_port=443)
"
```

---

## Структура проекта

```
installer/
├── main.py                    # Точка входа
├── cli/
│   ├── banner.py              # ASCII-баннер
│   └── progress.py            # Прогресс-бар
├── core/
│   ├── constants.py           # Все константы, URL, имена
│   ├── paths.py               # Все файловые пути
│   ├── logging.py             # Логирование (info/warn/die)
│   ├── shell.py               # Безопасный subprocess wrapper
│   ├── state.py               # Dataclass-модели состояния
│   ├── system.py              # Системные утилиты (RAM, CPU, pkg)
│   ├── validators.py          # Чистые функции валидации
│   └── backup.py              # Backup и rollback
├── services/
│   ├── xray.py                # Установка и управление Xray
│   ├── nginx.py               # Установка и настройка Nginx
│   ├── certbot.py             # SSL-сертификаты
│   └── ufw.py                 # Файервол UFW
├── config_builders/
│   ├── xray_config.py         # Сборка JSON-конфигов Xray
│   └── client_links.py        # Генерация VLESS-ссылок и QR
├── diagnostics/
│   └── health.py              # Проверки здоровья сервисов
├── docs/
│   ├── README.md              # Этот файл
│   ├── ARCHITECTURE.md        # Архитектура проекта
│   └── TROUBLESHOOTING.md     # Частые проблемы и решения
└── tests/
    ├── test_validators.py     # Тесты валидации
    ├── test_generators.py     # Тесты генераторов
    └── test_config_builders.py # Тесты сборщиков конфигов
```

---

## Запуск тестов

```bash
# Без pytest
python installer/tests/test_validators.py
python installer/tests/test_generators.py
python installer/tests/test_config_builders.py

# С pytest
python -m pytest installer/tests/ -v

# Проверка синтаксиса всех файлов
python -m py_compile installer/core/constants.py
python -m py_compile installer/core/state.py
# ... и т.д.
```

---

## Переменные окружения

| Переменная | Значение | Описание |
|-----------|---------|---------|
| `VLESS_THEME` | `light` | Светлая тема терминала (белый фон) |

