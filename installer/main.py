"""
installer/main.py — Точка входа установщика VLESS Ultimate.

Инициализирует среду, проверяет root, устанавливает базовые зависимости
и запускает главное меню из cli/menu.py.

Бизнес-логика живёт в:
  - services/       — установка и управление сервисами
  - config_builders/ — сборка конфигов Xray/Nginx
  - diagnostics/    — проверки здоровья
  - cli/menu.py     — интерактивное меню
"""

from __future__ import annotations

import sys
import os
import time
import json
import atexit
from pathlib import Path


def _bootstrap() -> None:
    """
    Минимальная патч-инициализация до загрузки модулей:
    переопределяет input() для безопасной работы в нестандартных терминалах,
    покрывает все места вызова input() в проекте разом.
    """
    import builtins as _builtins

    _orig_input = _builtins.input

    def _safe_input(prompt: str = "") -> str:
        try:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            raw = sys.stdin.buffer.readline()
            if not raw:
                raise EOFError
            return raw.decode("utf-8", errors="replace").rstrip("\n\r")
        except UnicodeDecodeError:
            return ""
        except (EOFError, OSError):
            raise EOFError

    _builtins.input = _safe_input


_bootstrap()


from installer.core.paths import (
    LOG_FILE, STATE_FILE, XRAY_CONFIG_FILE, BACKUP_DIR, STATE_DIR,
)
from installer.core.logging import setup_logging, info, log_to_file
from installer.core.constants import (
    THEME_ENV_VAR, THEME_LIGHT_VAL, VERSION, APP_NAME_FULL,
    MAX_RETRIES,
)
from installer.core.system import (
    ensure_dirs, get_total_ram_mb, get_total_cpu,
    detect_pkg_mgr, get_server_country,
)
from installer.core.state import InstallerState
from installer.cli.banner import print_banner
from installer.cli.menu import main_menu, ensure_startup_dependencies


_state_ref: InstallerState | None = None


def _on_exit() -> None:
    """
    EXIT TRAP: при аварийном завершении во время установки:
    - гарантирует открытый SSH-порт в UFW
    - останавливает частично поднятые сервисы
    - показывает путь к логу

    Молчит если установка завершилась успешно или пользователь просто вышел.
    """
    if _state_ref is None:
        return
    p = _state_ref.progress

    if p.completed or not p.started:
        return

    print()
    print("\033[0;31m[ERROR]\033[0m Скрипт завершился с ошибкой.")
    print("\033[1;33m[WARN]\033[0m  Система может быть в неполном состоянии.")

    import shutil
    if shutil.which("ufw"):
        from installer.services.ufw import ensure_ssh_open
        ensure_ssh_open()

    from installer.core.shell import run as _run
    if p.xray_done:
        _run(["systemctl", "stop",    "xray"], check=False, quiet=True)
        _run(["systemctl", "disable", "xray"], check=False, quiet=True)
    if p.nginx_done:
        _run(["systemctl", "stop", "nginx"], check=False, quiet=True)

    print(f"\033[1;33m[WARN]\033[0m  Полный лог: {LOG_FILE}")


atexit.register(_on_exit)


def run() -> None:
    """
    Главный поток запуска:
    1. Создаёт служебные директории и настраивает логирование
    2. Проверяет root
    3. Устанавливает базовые зависимости (curl, unzip, openssl…)
    4. Показывает баннер и запускает главное меню
    """
    global _state_ref

    ensure_dirs()
    light_theme = os.environ.get(THEME_ENV_VAR, "").lower() == THEME_LIGHT_VAL
    setup_logging(LOG_FILE, light_theme=light_theme)

    log_to_file("INFO", f"=== Запуск {APP_NAME_FULL} ===")
    log_to_file("INFO", f"Время начала: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    state = InstallerState.load(STATE_FILE)
    state.total_ram_mb = get_total_ram_mb()
    state.total_cpu    = get_total_cpu()
    _state_ref = state

    state.pkg_mgr = detect_pkg_mgr()

    if os.geteuid() != 0:
        from installer.core.logging import die
        die(f"Запустите от root: sudo python3 {sys.argv[0]}")

    ensure_startup_dependencies(state.pkg_mgr)

    print_banner()
    print()
    _cc, _cn, _flag = get_server_country()
    info(
        f"{APP_NAME_FULL}  "
        f"RAM: {state.total_ram_mb}MB  CPU: {state.total_cpu}  "
        f"{_flag} {_cn} ({_cc})"
    )
    print()
    time.sleep(0.5)

    _run_main_loop(state)


def _run_main_loop(state: InstallerState) -> None:
    """
    Запускает главное меню с авто-восстановлением при FileNotFoundError.
    При падении с FileNotFoundError пробует установить недостающий пакет
    и повторяет запуск (до MAX_RETRIES раз).
    """
    checkpoint_file = STATE_DIR / "checkpoint.json"

    for attempt in range(MAX_RETRIES + 1):
        try:
            if attempt > 0:
                print()
                info(f"Повторная попытка после установки пакета ({attempt}/{MAX_RETRIES})...")
                print()

            try:
                checkpoint_file.write_text(json.dumps({
                    "stage": "main_menu",
                    "attempt": attempt,
                }))
            except Exception:
                pass

            main_menu(state)
            checkpoint_file.unlink(missing_ok=True)
            break

        except KeyboardInterrupt:
            print()
            print("\033[0;32mДо свидания! 👋\033[0m")
            log_to_file("INFO", "Скрипт завершён пользователем (Ctrl+C)")
            checkpoint_file.unlink(missing_ok=True)
            sys.exit(0)

        except FileNotFoundError as fnf:
            if not _smart_recover(fnf, state.pkg_mgr):
                print(f"\033[0;31mВосстановление невозможно. Скрипт остановлен.\033[0m")
                print(f"\033[2mЛог: {LOG_FILE}\033[0m")
                sys.exit(1)
            print()
            print("\033[0;36mПакет установлен. Продолжаем...\033[0m")
            continue

        except SystemExit:
            raise

        except Exception as exc:
            import traceback
            print(f"\033[0;31m[CRITICAL]\033[0m Неожиданная ошибка: {exc}")
            print(f"\033[2m{traceback.format_exc()}\033[0m")
            log_to_file("ERROR", f"Неожиданная ошибка: {exc}\n{traceback.format_exc()}")
            sys.exit(1)
    else:
        print(f"\033[0;31m[ERROR]\033[0m Исчерпан лимит авто-восстановлений ({MAX_RETRIES}).")
        sys.exit(1)


_BINARY_TO_PACKAGE: dict[str, str] = {
    "curl":       "curl",
    "wget":       "wget",
    "unzip":      "unzip",
    "openssl":    "openssl",
    "dig":        "dnsutils",
    "nginx":      "nginx",
    "certbot":    "certbot",
    "fail2ban":   "fail2ban",
    "ufw":        "ufw",
    "jq":         "jq",
    "systemctl":  "systemd",
    "qrencode":   "qrencode",
}


def _smart_recover(fnf: FileNotFoundError, pkg_mgr: str) -> bool:
    """
    При FileNotFoundError пытается определить недостающий пакет по имени
    бинарника и установить его.

    Returns:
        True если пакет установлен, False если восстановление невозможно.
    """
    import shutil

    missing_bin = Path(str(fnf)).name
    package = _BINARY_TO_PACKAGE.get(missing_bin)
    if not package:
        log_to_file("WARN", f"_smart_recover: неизвестный бинарник {missing_bin!r}")
        return False

    if shutil.which(missing_bin):
        log_to_file("WARN", f"_smart_recover: {missing_bin} уже в PATH, восстановление не нужно")
        return False

    info(f"Отсутствует {missing_bin!r}, устанавливаю пакет {package!r}...")
    log_to_file("RECOVER", f"installing {package} for missing {missing_bin}")

    from installer.core.shell import run
    from installer.core.system import wait_apt_lock

    if pkg_mgr in ("apt-get", "apt"):
        wait_apt_lock()
        r = run(
            ["apt-get", "install", "-y", "-q", "--no-install-recommends", package],
            env={"DEBIAN_FRONTEND": "noninteractive"},
            check=False, quiet=True,
        )
        return r.returncode == 0
    elif pkg_mgr == "dnf":
        r = run(["dnf", "install", "-y", package], check=False, quiet=True)
        return r.returncode == 0

    return False


def handle_cli_args() -> bool:
    """
    Обрабатывает специальные аргументы командной строки (cron-задачи).
    Возвращает True если аргумент обработан и основной запуск не нужен.
    """
    if "--status" in sys.argv:
        _init_quick()
        _do_quick_status()
        return True

    if "--backup" in sys.argv:
        _init_quick()
        from installer.core.backup import create_backup
        ts = create_backup()
        print(f"Backup создан: {ts}")
        return True

    if "--diagnostics" in sys.argv:
        _init_quick()
        state = InstallerState.load(STATE_FILE)
        from installer.diagnostics.health import run_full_health_check
        run_full_health_check(state.xray.domain, state.server_port)
        return True

    if "--rollback" in sys.argv:
        _init_quick()
        from installer.core.backup import get_latest_backup, perform_rollback
        ts = get_latest_backup()
        if ts:
            perform_rollback(ts)
        else:
            print("Нет доступных бэкапов")
        return True

    if "--scheduled-backup" in sys.argv:
        _init_quick()
        state = InstallerState.load(STATE_FILE)
        from installer.core.backup import create_scheduled_backup
        create_scheduled_backup(keep_last=state.scheduled_backup.keep_last)
        return True

    _unimplemented_cron_args = (
        "--smart-balance", "--autoban", "--ttl-check", "--dpi-check",
        "--ingress-geoip-update", "--tg-event", "--switch-mode-a",
        "--switch-mode-b", "--update-ru-subnets", "--pinned-fallback-check",
    )
    for arg in _unimplemented_cron_args:
        if arg in sys.argv:
            log_to_file("WARN", f"CLI arg {arg!r} not yet implemented in modular version")
            return True

    return False


def _do_quick_status() -> None:
    """Быстрый вывод статуса сервисов для cron/скриптов."""
    from installer.core.shell import service_is_active
    from installer.services.xray import get_xray_version

    xray_active  = service_is_active("xray")
    nginx_active = service_is_active("nginx")
    xray_ver     = get_xray_version()

    print(f"xray:  {'active' if xray_active else 'inactive'}  {xray_ver}")
    print(f"nginx: {'active' if nginx_active else 'inactive'}")


def _init_quick() -> None:
    """Минимальная инициализация для cron-команд (без баннера и меню)."""
    if os.geteuid() != 0:
        print("ERROR: требуются права root", file=sys.stderr)
        sys.exit(1)
    ensure_dirs()
    setup_logging(LOG_FILE)

