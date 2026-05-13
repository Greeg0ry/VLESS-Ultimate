# ARCHITECTURE.md — Архитектура VLESS Ultimate Installer

## Обзор модулей

```
core/           — Ядро, никакого UI, никаких системных side-эффектов при import
cli/            — Терминальный интерфейс (баннер, прогресс, меню)
services/       — Установка и управление системными сервисами
config_builders/ — Сборщики JSON-конфигов (чистые функции)
diagnostics/    — Проверки здоровья без side-эффектов
```

**Новые модули (v4.06):**

| Модуль | Назначение |
|--------|-----------|
| `services/asn_routing.py` | AS-маршрутизация через RIPE NCC API |
| `services/logrotate.py` | Управление ротацией логов |
| `services/xray.py` → `xray_safe_apply_config()` | Атомарное применение конфига с pre-flight и авто-откатом |
| `config_builders/client_links.py` → `export_*` | Экспорт Clash Meta / Sing-box конфигов |
| `core/backup.py` → `create_scheduled_backup()` | Плановый tar.gz-бэкап по cron |

---

## Поток выполнения установки

```
install.py
  └── installer/main.py::run()
        ├── ensure_dirs()               ← core/system.py
        ├── setup_logging()             ← core/logging.py
        ├── InstallerState.load()       ← core/state.py
        ├── detect_pkg_mgr()            ← core/system.py
        ├── ensure_startup_dependencies() ← legacy (install.py)
        ├── print_banner()              ← cli/banner.py
        └── main_menu()                 ← legacy (install.py)
              ├── do_full_install()
              │     ├── prompt_parameters()        ← заполняет InstallerState
              │     ├── configure_firewall()       ← services/ufw.py
              │     ├── install_xray()             ← services/xray.py
              │     ├── generate_xray_config()     ← config_builders/xray_config.py
              │     ├── setup_nginx_temp()         ← services/nginx.py
              │     ├── obtain_ssl_cert()          ← services/certbot.py
              │     ├── setup_nginx_final()        ← services/nginx.py
              │     ├── create_xray_service()      ← services/xray.py
              │     └── generate_client_links()    ← config_builders/client_links.py
              └── [другие пункты меню]
```

---

## Где собирается Xray config

```
config_builders/xray_config.py

build_reality_config(state, config_dir)
  ├── build_log_block()
  ├── build_dns_block(is_ipv6, use_dnscrypt, ...)
  ├── inbound (VLESS + REALITY + realitySettings)
  ├── outbounds (freedom + blackhole)
  ├── routing rules
  └── apply_stats_to_config()    ← встраивает Stats API

build_xhttp_config(state, config_dir)
  ├── build_log_block()
  ├── build_dns_block(...)
  ├── inbound (VLESS + xHTTP + TLS)
  ├── outbounds
  ├── routing rules
  └── apply_stats_to_config()
```

После сборки dict записывается через `write_config(config, path)`:
- Устанавливаются права `640 root:xray`
- Создаётся симлинк `/usr/local/etc/xray/config.json → /etc/xray/config.json`

---

## Где собирается Nginx config

```
services/nginx.py

setup_nginx_final(domain, web_root, socket_path, ...)
  ├── protocol=xhttp  → _setup_redirect_only()   HTTP→HTTPS редирект
  ├── awg_enabled     → _setup_redirect_only()   HTTP→HTTPS редирект
  └── REALITY         → _setup_reality_full()    полный proxy_protocol конфиг
```

Временный конфиг для certbot создаётся через `setup_nginx_temp()` — только HTTP на 80.

---

## Как работает InstallerState

`InstallerState` — единственный dataclass для всего состояния установщика.
Заменяет ~50 глобальных переменных оригинального скрипта.

```python
@dataclass
class InstallerState:
    install_mode: str           # "A" или "B"
    protocol_mode: str          # "reality" или "xhttp"
    server_port: int            # 443

    xray:             XrayParams       # UUID, ключи, домен, spiderx...
    xhttp:            XhttpParams      # xHTTP-специфичные параметры
    nginx:            NginxParams      # домен Nginx
    awg:              AwgConfig        # AWG-параметры
    warp:             WarpConfig       # WARP-параметры
    split_tunnel:     SplitTunnelConfig
    chain:            ChainParams      # каскад (Режим B)
    progress:         InstallProgress  # флаги для EXIT TRAP
    asn_routing:      AsnRoutingConfig # AS-маршруты (список ASN + действия)
    scheduled_backup: ScheduledBackupConfig  # параметры планового бэкапа
```

**Сохранение/загрузка:**
```python
state.save(STATE_FILE)          # → /var/lib/xray-installer/state.json
state = InstallerState.load(STATE_FILE)
```

**Legacy-совместимость:**
Пока не все функции переведены на `InstallerState`, функция
`_load_state_into_globals()` в оригинальном коде читает state.json
и заполняет глобальные переменные.

---

## Как добавить новый режим установки

1. Добавить константу в `core/constants.py`:
   ```python
   PROTOCOL_MYPROTO = "myproto"
   ```

2. Добавить параметры в `core/state.py` (новый dataclass или поля в XrayParams):
   ```python
   @dataclass
   class MyProtoParams:
       option1: str = ""
   ```
   И добавить поле в `InstallerState`.

3. Создать сборщик конфига в `config_builders/`:
   ```python
   # config_builders/myproto_config.py
   def build_myproto_config(state: InstallerState) -> dict:
       ...
   ```

4. Добавить установку сервиса в `services/`:
   ```python
   # services/myproto.py
   def install_myproto() -> None:
       ...
   ```

5. Добавить пункт меню в оригинальный `install.py::main_menu()`
   (до завершения рефакторинга меню).

6. Написать тест в `tests/test_config_builders.py`.

---

## Правило: no side-effects при import

Ни один модуль не должен производить I/O при импорте:
- **НЕТ** `mkdir()` при `import installer.core.paths`
- **НЕТ** системных вызовов при `import installer.services.xray`
- **НЕТ** `print()` при `import installer.core.logging`

Все операции запускаются явно из `main.py::run()` или из функций меню.

---

## AS-маршрутизация (services/asn_routing.py)

Модуль управляет трафиком на уровне автономных систем (ASN).

**Поток работы:**
```
add_or_update_asn_route(asn=8359, action="direct")
  ├── validate_asn(8359)
  ├── get_prefixes(8359)              ← кэш SQLite → RIPE NCC API
  │     └── save_prefixes_to_cache()  ← SQLite + as_direct_8359.txt
  ├── patch_xray_config_with_asn()
  │     ├── _make_cidr_rules()        ← батч-правила по 500 CIDR
  │     └── xray_safe_apply_config()  ← атомарное применение
  └── save_asn_list()                 ← /etc/xray/as_direct_list.json
```

**Кэш:**
- SQLite: `/var/lib/xray-installer/asn_prefix_cache.sqlite3`
- txt-файлы: `/etc/xray/as_direct_<ASN>.txt`
- TTL кэша: 30 дней (автообновление через systemd timer ежесуточно в 04:00)

**Идемпотентность:** каждое правило помечается `_comment: "_asn_<ASN>_auto"`.
При повторном применении старые правила удаляются, вставляются новые.

---

## Безопасное применение конфига (xray_safe_apply_config)

```
xray_safe_apply_config(config_dict, cfg_path, reason)
  │
  ├── 1. Pre-flight: xray run -test <tmpfile>   ← проверка перед записью
  │       └── FAIL → return False (ничего не записывается)
  │
  ├── 2. Создать config.json.pre-apply          ← точка отката
  │
  ├── 3. Записать новый config.json
  │
  ├── 4. Sync /usr/local/etc/xray/config.json
  │
  ├── 5. systemctl restart xray → ждать active (до 15с)
  │       └── OK → return True
  │
  └── 6. TIMEOUT → xray_config_rollback(pre-apply)
              └── systemctl restart xray
```

---

## Экспорт клиентских конфигов (config_builders/client_links.py)

```
export_client_configs(state)
  ├── export_clash_config(state)   → /root/xray-client-configs/clash-meta.yaml
  └── export_singbox_config(state) → /root/xray-client-configs/sing-box.json
```

Поддерживаемые форматы: **Clash Meta** (YAML), **Sing-box** (JSON).
Для каждого формата поддерживаются оба протокола: REALITY и xHTTP TLS.

---

## Ротация логов (services/logrotate.py)

```
/etc/logrotate.d/xray-vless
  ├── /var/log/vless-install.log
  ├── /var/log/xray-changes.log
  ├── /var/log/xray/access.log
  └── /var/log/xray/error.log

postrotate: systemctl reload xray
```

Управление через `configure_logrotate(frequency, keep)` или `apply_default_logrotate()`.

---

## Плановый backup (core/backup.py)

```
create_scheduled_backup(keep_last=7)
  ├── tar.gz: config.json + state.json + LE-сертификаты + ASN-списки
  ├── Хранится в /var/backups/xray/vless-backup-<ts>.tar.gz
  ├── Лог: /var/log/xray-scheduled-backup.log
  └── Ротация: оставляет последние keep_last архивов

setup_scheduled_backup_cron(interval_days, hour, minute, keep_last)
  └── /etc/cron.d/xray-backup
```

