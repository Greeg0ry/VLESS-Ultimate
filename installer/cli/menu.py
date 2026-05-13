"""
cli/menu.py — Главное интерактивное меню установщика VLESS Ultimate.

Этот модуль связывает воедино все сервисные модули в интерактивный
пользовательский интерфейс. Бизнес-логика живёт в services/, config_builders/,
diagnostics/ — здесь только UI-оркестрация.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from installer.core.state import InstallerState
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import (
    XRAY_BIN, XRAY_CONFIG_DIR, XRAY_CONFIG_FILE,
    XRAY_LOCK_FILE, STATE_FILE, BACKUP_DIR,
)
from installer.core.constants import (
    PROTOCOL_REALITY, PROTOCOL_XHTTP,
    INSTALL_MODE_A, INSTALL_MODE_B,
    VERSION,
)


def main_menu(state: InstallerState) -> None:
    """Главный интерактивный цикл. Вход после баннера."""
    while True:
        _print_main_menu(state)
        choice = _prompt("Ваш выбор").strip()

        if choice == "1":
            _do_install_reality(state)
        elif choice == "2":
            _do_install_xhttp(state)
        elif choice == "3":
            _show_status(state)
        elif choice == "4":
            _run_diagnostics(state)
        elif choice == "5":
            _manage_backup(state)
        elif choice == "6":
            _show_client_info(state)
        elif choice == "7":
            _restart_services(state)
        elif choice in ("0", "q", "exit", "quit"):
            print("\033[0;32mДо свидания! 👋\033[0m")
            break
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _print_main_menu(state: InstallerState) -> None:
    installed = XRAY_LOCK_FILE.exists()
    mode_tag  = f" [{state.protocol_mode.upper()}]" if installed else ""

    print()
    _title(f"VLESS Ultimate v{VERSION}  Главное меню")
    print(f"  1)  Установить VLESS REALITY (Режим A)"
          + (" ✓" if installed and state.protocol_mode == PROTOCOL_REALITY else ""))
    print(f"  2)  Установить VLESS xHTTP TLS (Режим B)"
          + (" ✓" if installed and state.protocol_mode == PROTOCOL_XHTTP else ""))
    _hr()
    print(f"  3)  Статус сервисов")
    print(f"  4)  Диагностика")
    print(f"  5)  Backup / Rollback")
    print(f"  6)  Показать клиентскую ссылку")
    print(f"  7)  Перезапустить Xray / Nginx")
    _hr()
    print(f"  0)  Выйти")
    print()


def _do_install_reality(state: InstallerState) -> None:
    """Полный флоу установки VLESS REALITY (Режим A)."""
    _title("Установка VLESS REALITY (Режим A)")

    if XRAY_LOCK_FILE.exists():
        ans = _prompt("Xray уже установлен. Переустановить?", default="n")
        if ans.lower() not in ("y", "yes", "да"):
            return

    _prompt_reality_params(state)
    state.protocol_mode = PROTOCOL_REALITY
    state.install_mode  = INSTALL_MODE_A

    state.progress.started = True
    state.save(STATE_FILE)

    try:
        from installer.core.backup import create_backup
        from installer.services.xray import install_xray, create_xray_service
        from installer.services.ufw import configure_firewall
        from installer.config_builders.xray_config import build_reality_config, write_config

        info("Шаг 1/4 — Настройка файервола...")
        configure_firewall(state.server_port)
        state.progress.ufw_done = True
        state.save(STATE_FILE)

        info("Шаг 2/4 — Установка Xray...")
        xray_bin = install_xray()
        state.progress.xray_done = True
        state.save(STATE_FILE)

        info("Шаг 3/4 — Сборка конфига Xray...")
        cfg = build_reality_config(state, str(XRAY_CONFIG_DIR))
        write_config(cfg, XRAY_CONFIG_FILE)

        info("Шаг 4/4 — Создание сервиса...")
        create_xray_service(
            config_dir=XRAY_CONFIG_DIR,
            xray_bin=xray_bin,
            protocol_mode=PROTOCOL_REALITY,
            socket_path=state.xray.socket_path,
            awg_enabled=state.awg.enabled,
            use_dnscrypt=state.use_dnscrypt,
        )

        from installer.core.shell import run as _run
        _run(["systemctl", "start", "xray"], check=False, quiet=True)
        time.sleep(3)

        XRAY_LOCK_FILE.touch()
        state.progress.completed = True
        state.save(STATE_FILE)

        success("Установка VLESS REALITY завершена!")
        _show_client_info(state)

    except Exception as exc:
        import traceback
        warn(f"Ошибка установки: {exc}")
        log_to_file("ERROR", f"install_reality: {traceback.format_exc()}")


def _do_install_xhttp(state: InstallerState) -> None:
    """Полный флоу установки VLESS xHTTP TLS (Режим B)."""
    _title("Установка VLESS xHTTP TLS (Режим B)")

    if XRAY_LOCK_FILE.exists():
        ans = _prompt("Xray уже установлен. Переустановить?", default="n")
        if ans.lower() not in ("y", "yes", "да"):
            return

    _prompt_xhttp_params(state)
    state.protocol_mode = PROTOCOL_XHTTP
    state.install_mode  = INSTALL_MODE_B

    state.progress.started = True
    state.save(STATE_FILE)

    try:
        from installer.services.xray import install_xray, create_xray_service
        from installer.services.ufw import configure_firewall
        from installer.services.nginx import setup_nginx_temp, setup_nginx_final
        from installer.services.certbot import obtain_ssl_cert
        from installer.config_builders.xray_config import build_xhttp_config, write_config

        info("Шаг 1/6 — Настройка файервола...")
        configure_firewall(state.server_port)
        state.progress.ufw_done = True
        state.save(STATE_FILE)

        info("Шаг 2/6 — Установка Xray...")
        xray_bin = install_xray()
        state.progress.xray_done = True
        state.save(STATE_FILE)

        web_root = Path(f"/var/www/{state.nginx.domain}")

        info("Шаг 3/6 — Временный Nginx для получения сертификата...")
        setup_nginx_temp(state.nginx.domain, web_root)
        state.progress.nginx_done = True
        state.save(STATE_FILE)

        info("Шаг 4/6 — Получение TLS-сертификата...")
        obtain_ssl_cert(state.nginx.domain, state.xray.email, web_root)

        info("Шаг 5/6 — Сборка конфига Xray (xHTTP)...")
        cfg = build_xhttp_config(state, str(XRAY_CONFIG_DIR))
        write_config(cfg, XRAY_CONFIG_FILE)

        info("Шаг 6/6 — Настройка финального Nginx и сервиса Xray...")
        setup_nginx_final(
            domain=state.nginx.domain,
            web_root=web_root,
            socket_path=state.xray.socket_path,
            server_port=state.server_port,
            protocol_mode=PROTOCOL_XHTTP,
            awg_enabled=state.awg.enabled,
        )
        create_xray_service(
            config_dir=XRAY_CONFIG_DIR,
            xray_bin=xray_bin,
            protocol_mode=PROTOCOL_XHTTP,
            socket_path=state.xray.socket_path,
            awg_enabled=state.awg.enabled,
            use_dnscrypt=state.use_dnscrypt,
        )

        from installer.core.shell import run as _run
        _run(["systemctl", "start", "xray"],  check=False, quiet=True)
        _run(["systemctl", "start", "nginx"], check=False, quiet=True)
        time.sleep(3)

        XRAY_LOCK_FILE.touch()
        state.progress.completed = True
        state.save(STATE_FILE)

        success("Установка VLESS xHTTP TLS завершена!")
        _show_client_info(state)

    except Exception as exc:
        import traceback
        warn(f"Ошибка установки: {exc}")
        log_to_file("ERROR", f"install_xhttp: {traceback.format_exc()}")


def _prompt_reality_params(state: InstallerState) -> None:
    """Запрашивает у пользователя параметры для VLESS REALITY."""
    from installer.core.validators import is_valid_domain, is_valid_port, is_valid_ip
    from installer.core.system import get_server_ip
    from installer.config_builders.client_links import gen_uuid, gen_hex, gen_spiderx

    _title("Параметры VLESS REALITY")

    server_ip = get_server_ip("4") or ""
    if server_ip:
        info(f"IPv4 сервера: {server_ip}")

    port_str = _prompt("Порт Xray", default=str(state.server_port))
    from installer.core.validators import parse_port
    state.server_port = parse_port(port_str, default=443)

    reality_dest = _prompt("REALITY destination (SNI-сайт для маскировки)", default="yahoo.com")
    state.xray.reality_dest = reality_dest.strip()
    state.xray.domain       = reality_dest.strip()

    cur_uuid = state.xray.uuid or gen_uuid()
    uuid_inp = _prompt(f"UUID пользователя", default=cur_uuid)
    state.xray.uuid = uuid_inp.strip() or cur_uuid

    state.xray.spiderx = gen_spiderx()

    if not state.xray.private_key:
        info("Генерация REALITY ключей...")
        priv, pub = _gen_reality_keys()
        state.xray.private_key = priv
        state.xray.public_key  = pub

    if not state.xray.short_id:
        state.xray.short_id = gen_hex(8)

    state.xray.socket_path = f"/run/xray/xray.sock"

    info(f"  Порт:        {state.server_port}")
    info(f"  Destination: {state.xray.reality_dest}")
    info(f"  UUID:        {state.xray.uuid}")
    info(f"  Short ID:    {state.xray.short_id}")
    info(f"  Public Key:  {state.xray.public_key}")
    info(f"  SpiderX:     {state.xray.spiderx}")


def _prompt_xhttp_params(state: InstallerState) -> None:
    """Запрашивает у пользователя параметры для VLESS xHTTP TLS."""
    from installer.core.validators import is_valid_domain, parse_port
    from installer.config_builders.client_links import gen_uuid, gen_hex

    _title("Параметры VLESS xHTTP TLS")
    info("Для Режима B требуется домен с DNS A-записью, указывающей на этот сервер.")

    while True:
        domain = _prompt("Домен (например: vpn.example.com)").strip()
        if is_valid_domain(domain):
            break
        warn(f"{domain!r} не является валидным доменом. Повторите.")

    state.nginx.domain = domain
    state.xray.domain  = domain

    email = _prompt("Email для Let's Encrypt (уведомления)", default=state.xray.email or f"admin@{domain}")
    state.xray.email = email.strip()

    port_str = _prompt("Порт Xray (TLS)", default=str(state.server_port))
    state.server_port = parse_port(port_str, default=443)

    cur_uuid = state.xray.uuid or gen_uuid()
    uuid_inp = _prompt("UUID пользователя", default=cur_uuid)
    state.xray.uuid = uuid_inp.strip() or cur_uuid

    xhttp_path = _prompt("Путь xHTTP", default=state.xhttp.path or f"/{gen_hex(4)}")
    state.xhttp.path = xhttp_path.strip() or "/"

    info(f"  Домен:  {domain}")
    info(f"  Порт:   {state.server_port}")
    info(f"  UUID:   {state.xray.uuid}")
    info(f"  Путь:   {state.xhttp.path}")


def _gen_reality_keys() -> tuple[str, str]:
    """
    Генерирует пару ключей REALITY через 'xray x25519'.
    Возвращает (private_key, public_key).
    """
    from installer.core.shell import run_capture
    import re

    r = run_capture([str(XRAY_BIN), "x25519"])
    if r.returncode == 0:
        priv = re.search(r"Private key:\s*(\S+)", r.stdout)
        pub  = re.search(r"Public key:\s*(\S+)", r.stdout)
        if priv and pub:
            return priv.group(1), pub.group(1)

    warn("xray x25519 недоступен, генерирую ключи через openssl...")
    priv_r = run_capture([
        "openssl", "genpkey", "-algorithm", "X25519",
        "-outform", "DER",
    ])
    if priv_r.returncode == 0:
        import base64
        priv_b64 = base64.urlsafe_b64encode(priv_r.stdout.encode()[-32:]).rstrip(b"=").decode()
        pub_r = run_capture([
            "openssl", "pkey", "-pubout", "-outform", "DER",
        ], input_text=priv_r.stdout)
        if pub_r.returncode == 0:
            pub_b64 = base64.urlsafe_b64encode(pub_r.stdout.encode()[-32:]).rstrip(b"=").decode()
            return priv_b64, pub_b64

    import secrets
    key = secrets.token_bytes(32)
    import base64
    b64 = base64.urlsafe_b64encode(key).rstrip(b"=").decode()
    warn("Используется случайный ключ — замените вручную через 'xray x25519'")
    return b64, b64


def _show_status(state: InstallerState) -> None:
    """Выводит текущий статус сервисов."""
    from installer.core.shell import service_is_active, run_capture
    from installer.services.xray import get_xray_version

    _title("Статус сервисов")

    xray_active  = service_is_active("xray")
    nginx_active = service_is_active("nginx")

    xray_ver = get_xray_version()
    _status_line("Xray",  xray_active,  xray_ver)
    _status_line("Nginx", nginx_active, "")

    if state.xray.domain:
        info(f"  Домен/SNI:  {state.xray.domain}")
    if state.xray.uuid:
        info(f"  UUID:       {state.xray.uuid}")
    if state.server_port:
        info(f"  Порт:       {state.server_port}")
    if state.protocol_mode:
        info(f"  Протокол:   {state.protocol_mode.upper()}")

    if state.xray.public_key:
        info(f"  Public Key: {state.xray.public_key}")
    if state.xray.short_id:
        info(f"  Short ID:   {state.xray.short_id}")

    _prompt_enter()


def _run_diagnostics(state: InstallerState) -> None:
    """Запускает полную диагностику."""
    from installer.diagnostics.health import run_full_health_check
    from installer.diagnostics.network import run_network_diagnostics

    _title("Диагностика")
    run_network_diagnostics(state.xray.domain, state.server_port)
    print()
    run_full_health_check(state.xray.domain, state.server_port)
    _prompt_enter()


def _manage_backup(state: InstallerState) -> None:
    """Подменю управления backup/rollback."""
    from installer.core.backup import create_backup, list_backups, perform_rollback

    while True:
        _title("Backup / Rollback")
        backups = list_backups()
        if backups:
            info(f"Доступные бэкапы ({len(backups)}):")
            for i, b in enumerate(backups[:10], 1):
                print(f"  {i}) {b}")
        else:
            info("Бэкапы не найдены")

        print()
        print("  1)  Создать backup сейчас")
        print("  2)  Откатиться к последнему backup")
        print("  3)  Откатиться к выбранному backup")
        print("  0)  Назад")
        print()
        choice = _prompt("Выбор").strip()

        if choice == "1":
            ts = create_backup()
            success(f"Backup создан: {ts}")
            _prompt_enter()
        elif choice == "2":
            if backups:
                ok = perform_rollback(backups[0])
                if ok:
                    success(f"Откат к {backups[0]} выполнен")
                _prompt_enter()
            else:
                warn("Нет доступных бэкапов")
        elif choice == "3":
            if backups:
                idx = _prompt(f"Номер backup (1-{min(len(backups),10)})").strip()
                try:
                    b = backups[int(idx) - 1]
                    perform_rollback(b)
                    _prompt_enter()
                except (ValueError, IndexError):
                    warn("Неверный номер")
            else:
                warn("Нет доступных бэкапов")
        elif choice == "0":
            break
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _show_client_info(state: InstallerState) -> None:
    """Выводит VLESS-ссылки для клиентов."""
    from installer.config_builders.client_links import generate_client_links, print_qr

    if not state.xray.uuid:
        warn("Установка ещё не выполнена — нет клиентских данных")
        _prompt_enter()
        return

    _title("Клиентские данные")
    links = generate_client_links(state)

    if not links:
        warn("Нет данных для генерации ссылок (не заполнен UUID или IP)")
        _prompt_enter()
        return

    for link in links:
        print(f"\n\033[1;36m{link}\033[0m")
        print_qr(link)

    _prompt_enter()


def _restart_services(state: InstallerState) -> None:
    """Перезапускает Xray и Nginx."""
    from installer.services.xray import restart_xray
    from installer.core.shell import service_restart, service_is_active

    _title("Перезапуск сервисов")
    ok = restart_xray()
    if not ok:
        warn("Xray не вышел в active после перезапуска — проверьте логи")

    if service_is_active("nginx") or Path("/usr/sbin/nginx").exists():
        service_restart("nginx", check=False)
        success("Nginx перезапущен")

    _prompt_enter()


def ensure_startup_dependencies(pkg_mgr: str) -> None:
    """
    Устанавливает базовые зависимости, необходимые для работы установщика:
    curl, unzip, openssl, dnsutils (dig), jq.

    Вызывается однократно в начале main.py::run() до первого меню.
    """
    from installer.core.shell import command_exists, run
    from installer.core.system import wait_apt_lock

    needed = []
    checks = {
        "curl":   "curl",
        "unzip":  "unzip",
        "openssl":"openssl",
        "dig":    "dnsutils",
        "jq":     "jq",
    }
    for cmd, pkg in checks.items():
        if not command_exists(cmd):
            needed.append(pkg)

    if not needed:
        return

    info(f"Устанавливаю зависимости: {', '.join(needed)}...")
    if pkg_mgr in ("apt-get", "apt"):
        wait_apt_lock()
        run(
            ["apt-get", "install", "-y", "-q", "--no-install-recommends"] + needed,
            env={"DEBIAN_FRONTEND": "noninteractive"},
            check=False, quiet=True,
        )
    elif pkg_mgr == "dnf":
        run(["dnf", "install", "-y"] + needed, check=False, quiet=True)


def _prompt(msg: str, default: Optional[str] = None) -> str:
    """Безопасный запрос ввода с опциональным значением по умолчанию."""
    if default is not None:
        prompt_str = f"  {msg} [{default}]: "
    else:
        prompt_str = f"  {msg}: "
    try:
        val = input(prompt_str).strip()
        return val if val else (default or "")
    except (EOFError, KeyboardInterrupt):
        raise


def _prompt_enter() -> None:
    """Ждёт нажатия Enter."""
    try:
        input("\n  [Enter для продолжения] ")
    except (EOFError, KeyboardInterrupt):
        pass


def _status_line(name: str, active: bool, extra: str = "") -> None:
    if active:
        status = "\033[0;32m● активен\033[0m"
    else:
        status = "\033[0;31m○ неактивен\033[0m"
    suffix = f"  {extra}" if extra else ""
    print(f"  {name:<12} {status}{suffix}")


def _hr() -> None:
    print("  " + "─" * 50)


def _title(text: str) -> None:
    print()
    print(f"  \033[1;36m{'─' * 4} {text} {'─' * 4}\033[0m")
    print()

