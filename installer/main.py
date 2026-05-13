"""
installer/main.py — Точка входа установщика VLESS Ultimate.

Этот модуль:
1. Инициализирует среду (директории, логирование)
2. Проверяет root и зависимости
3. Запускает главное меню

Бизнес-логика установки НЕ живёт здесь — она в соответствующих модулях:
  - Установка пакетов     → core/system.py
  - Xray                  → services/xray.py
  - Nginx                 → services/nginx.py
  - Конфиги               → config_builders/
  - Диагностика           → diagnostics/
  - Меню                  → cli/menu.py (обёртка вокруг оригинального main_menu)

Для полноценного рефакторинга меню (27 000+ строк кода) — см. ARCHITECTURE.md.
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
    Минимальная инициализация до загрузки всех модулей:
    - monkey-patch input() для безопасного ввода в нестандартных терминалах
    - создание базовых директорий
    """
    import builtins as _builtins

    _orig_input = _builtins.input

    def _safe_input(prompt: str = "") -> str:
        """
        Защита от UnicodeDecodeError при чтении ввода.
        Monkey-patches input() глобально — покрывает все 277 мест вызова.
        """
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


_state_ref: InstallerState | None = None


def _on_exit() -> None:
    """
    EXIT TRAP: при аварийном завершении установки:
    - открывает SSH (на случай если UFW был настроен)
    - останавливает Xray/Nginx если они были запущены частично
    - показывает путь к логу

    Не срабатывает если установка завершилась успешно (progress.completed=True)
    или если пользователь просто вышел из меню (progress.started=False).
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
    Запускает установщик:
    1. Инициализация среды и логирования
    2. Проверка root
    3. Установка базовых зависимостей
    4. Главное меню

    Перехватывает FileNotFoundError (отсутствие пакетов) и пытается
    восстановить работоспособность автоматически.
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

    _ensure_startup_dependencies(state)

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


def _ensure_startup_dependencies(state: InstallerState) -> None:
    """
    Проверяет и устанавливает базовые зависимости.
    Делегирует оригинальному ensure_startup_dependencies() из install.py
    через legacy-мост до завершения полного рефакторинга.
    """
    try:
        import importlib.util, sys as _sys
        _legacy = _get_legacy_module()
        if _legacy:
            _legacy.ensure_startup_dependencies()
    except Exception as e:
        log_to_file("WARN", f"ensure_startup_dependencies: {e}")


def _run_main_loop(state: InstallerState) -> None:
    """
    Главный цикл с умным восстановлением при FileNotFoundError.
    Максимум MAX_RETRIES попыток.
    """
    _legacy = _get_legacy_module()
    if _legacy is None:
        from installer.core.logging import die
        die("Не удалось загрузить модуль установщика")
        return

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

            _legacy.main_menu()
            checkpoint_file.unlink(missing_ok=True)
            break

        except KeyboardInterrupt:
            print()
            print("\033[0;32mДо свидания! 👋\033[0m")
            log_to_file("INFO", "Скрипт завершён пользователем (Ctrl+C)")
            checkpoint_file.unlink(missing_ok=True)
            sys.exit(0)

        except FileNotFoundError as fnf:
            recovered = _legacy._smart_recover(fnf)
            if not recovered:
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


_legacy_module = None
_legacy_loaded = False


def _get_legacy_module():
    """
    Загружает оригинальный install.py как модуль для вызова ещё не
    перенесённых функций (main_menu, _smart_recover, ensure_startup_dependencies...).

    По мере завершения рефакторинга этот мост будет удаляться по частям.
    """
    global _legacy_module, _legacy_loaded
    if _legacy_loaded:
        return _legacy_module

    _legacy_loaded = True
    import importlib.util

    candidates = [
        Path(__file__).parent.parent / "install.py",
        Path(__file__).parent.parent / "install (2).py",
        Path("/opt/vless-ultimate/install.py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                spec = importlib.util.spec_from_file_location("_vless_legacy", candidate)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _legacy_module = mod
                log_to_file("INFO", f"Legacy-модуль загружен из {candidate}")
                return mod
            except Exception as e:
                log_to_file("WARN", f"Не удалось загрузить {candidate}: {e}")

    log_to_file("ERROR", "Legacy install.py не найден")
    return None


def handle_cli_args() -> bool:
    """
    Обрабатывает специальные аргументы командной строки (cron-задачи и т.д.).
    Возвращает True если аргумент обработан и основной запуск не нужен.
    """
    if "--status" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            legacy.do_quick_status()
        return True

    if "--smart-balance" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy and not legacy._awg_guard_cron("SmartBalancer"):
            legacy._smart_balancer_run_once()
        return True

    if "--autoban" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            legacy._autoban_run_once()
        return True

    if "--ttl-check" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            removed = legacy._ttl_check_and_expire()
            if removed:
                print(f"[TTL] Удалено {removed} пользователей")
        return True

    if "--dpi-check" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            n = legacy._dpi_run_once()
            if n:
                print(f"[DPI] Заблокировано: {n}")
        return True

    if "--ingress-geoip-update" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            state = legacy._ingress_state_load()
            if state.get("enabled"):
                port = state.get("port", 443)
                legacy._ingress_remove()
                legacy._ingress_enable(port)
        return True

    if "--tg-event" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            idx = sys.argv.index("--tg-event")
            args = sys.argv[idx + 1: idx + 3]
            legacy._tg_notify_event(*args)
        return True

    if "--switch-mode-a" in sys.argv or "--switch-mode-b" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            legacy.switch_mode_ab()
        return True

    if "--update-ru-subnets" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            legacy._awg_apply_policy_routing_all_nodes()
        return True

    if "--pinned-fallback-check" in sys.argv:
        _init_quick()
        legacy = _get_legacy_module()
        if legacy:
            if not legacy._awg_guard_cron("PinnedFallback"):
                legacy._pinned_node_check_and_fallback()
        return True

    return False


def _init_quick() -> None:
    """Минимальная инициализация для cron-команд (без баннера и меню)."""
    if os.geteuid() != 0:
        print("ERROR: требуются права root", file=sys.stderr)
        sys.exit(1)
    ensure_dirs()
    setup_logging(LOG_FILE)

