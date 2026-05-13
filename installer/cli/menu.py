"""
cli/menu.py — Главное интерактивное меню установщика VLESS Ultimate.

Связывает все сервисные модули в интерактивный UI.
Бизнес-логика живёт в services/, config_builders/, diagnostics/.
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
    AWG_CONF_DIR, AWG_CONF_FILE,
)
from installer.core.constants import (
    PROTOCOL_REALITY, PROTOCOL_XHTTP,
    INSTALL_MODE_A, INSTALL_MODE_B,
    VERSION,
)


# ─────────────────────────────────────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────────────────────────────────────────

def main_menu(state: InstallerState) -> None:
    """Главный интерактивный цикл."""
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
            _menu_diagnostics(state)
        elif choice == "5":
            _manage_backup(state)
        elif choice == "6":
            _menu_users(state)
        elif choice == "7":
            _menu_network(state)
        elif choice == "8":
            _menu_security(state)
        elif choice == "9":
            _menu_maintenance(state)
        elif choice == "10":
            _manage_awg(state)
        elif choice == "0":
            print("\033[0;32mДо свидания! 👋\033[0m")
            break
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _print_main_menu(state: InstallerState) -> None:
    installed = XRAY_LOCK_FILE.exists()
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
    print(f"  6)  Управление пользователями")
    print(f"  7)  Сеть (WARP, DNSCrypt, Split Tunneling, ASN)")
    print(f"  8)  Безопасность (Fail2ban)")
    print(f"  9)  Обслуживание (Обновление Xray, Logrotate, Geo)")
    print(f"  10) AmneziaWG 2.0" + (" ✓" if state.awg.enabled else ""))
    _hr()
    print(f"  0)  Выйти")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# УСТАНОВКА
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# ПАРАМЕТРЫ УСТАНОВКИ
# ─────────────────────────────────────────────────────────────────────────────

def _prompt_reality_params(state: InstallerState) -> None:
    from installer.core.validators import parse_port
    from installer.core.system import get_server_ip
    from installer.config_builders.client_links import gen_uuid, gen_hex, gen_spiderx

    _title("Параметры VLESS REALITY")

    server_ip = get_server_ip("4") or ""
    if server_ip:
        info(f"IPv4 сервера: {server_ip}")

    port_str = _prompt("Порт Xray", default=str(state.server_port))
    state.server_port = parse_port(port_str, default=443)

    reality_dest = _prompt("REALITY destination (SNI-сайт для маскировки)", default="yahoo.com")
    state.xray.reality_dest = reality_dest.strip()
    state.xray.domain       = reality_dest.strip()

    cur_uuid = state.xray.uuid or gen_uuid()
    state.xray.uuid = _prompt("UUID пользователя", default=cur_uuid).strip() or cur_uuid
    state.xray.spiderx = gen_spiderx()

    if not state.xray.private_key:
        info("Генерация REALITY ключей...")
        priv, pub = _gen_reality_keys()
        state.xray.private_key = priv
        state.xray.public_key  = pub

    if not state.xray.short_id:
        state.xray.short_id = gen_hex(8)

    state.xray.socket_path = "/run/xray/xray.sock"

    info(f"  Порт:        {state.server_port}")
    info(f"  Destination: {state.xray.reality_dest}")
    info(f"  UUID:        {state.xray.uuid}")
    info(f"  Short ID:    {state.xray.short_id}")
    info(f"  Public Key:  {state.xray.public_key}")
    info(f"  SpiderX:     {state.xray.spiderx}")


def _prompt_xhttp_params(state: InstallerState) -> None:
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
    state.xray.email   = _prompt("Email для Let's Encrypt", default=state.xray.email or f"admin@{domain}").strip()
    state.server_port  = parse_port(_prompt("Порт Xray (TLS)", default=str(state.server_port)), default=443)

    cur_uuid = state.xray.uuid or gen_uuid()
    state.xray.uuid  = _prompt("UUID пользователя", default=cur_uuid).strip() or cur_uuid
    state.xhttp.path = _prompt("Путь xHTTP", default=state.xhttp.path or f"/{gen_hex(4)}").strip() or "/"

    print()
    print("  Транспорт для выхода в Интернет:")
    print("  1) Прямой выход (без AWG)")
    print("  2) AmneziaWG 2.0 (через AWG-туннель)")
    if _prompt("Выбор транспорта", default="1").strip() == "2":
        if not _configure_awg_for_mode_b(state):
            warn("AWG не активирован, продолжаем без AWG")
            state.awg.enabled = False
    else:
        state.awg.enabled = False

    info(f"  Домен: {domain}  Порт: {state.server_port}  UUID: {state.xray.uuid}  Путь: {state.xhttp.path}")


def _gen_reality_keys() -> tuple[str, str]:
    from installer.core.shell import run, run_capture
    import re, base64, secrets

    r = run_capture([str(XRAY_BIN), "x25519"])
    if r.returncode == 0:
        priv = re.search(r"Private key:\s*(\S+)", r.stdout)
        pub  = re.search(r"Public key:\s*(\S+)", r.stdout)
        if priv and pub:
            return priv.group(1), pub.group(1)

    warn("xray x25519 недоступен, генерирую ключи через openssl...")
    priv_r = run(["openssl", "genpkey", "-algorithm", "X25519", "-outform", "DER"],
                 check=False, capture=True)
    if priv_r.returncode == 0:
        priv_b64 = base64.urlsafe_b64encode(priv_r.stdout.encode()[-32:]).rstrip(b"=").decode()
        pub_r = run(["openssl", "pkey", "-pubout", "-outform", "DER"],
                    check=False, capture=True, input_text=priv_r.stdout)
        if pub_r.returncode == 0:
            pub_b64 = base64.urlsafe_b64encode(pub_r.stdout.encode()[-32:]).rstrip(b"=").decode()
            return priv_b64, pub_b64

    key = secrets.token_bytes(32)
    b64 = base64.urlsafe_b64encode(key).rstrip(b"=").decode()
    warn("Используется случайный ключ — замените вручную через 'xray x25519'")
    return b64, b64


# ─────────────────────────────────────────────────────────────────────────────
# СТАТУС
# ─────────────────────────────────────────────────────────────────────────────

def _show_status(state: InstallerState) -> None:
    from installer.core.shell import service_is_active
    from installer.services.xray import get_xray_version

    _title("Статус сервисов")
    _status_line("Xray",  service_is_active("xray"),  get_xray_version())
    _status_line("Nginx", service_is_active("nginx"), "")

    if state.dnscrypt_installed:
        _status_line("DNSCrypt", service_is_active("dnscrypt-proxy"), "")

    from installer.services.warp import get_warp_status
    ws = get_warp_status()
    if ws.get("installed"):
        _status_line("WARP", ws.get("connected", False), ws.get("status", ""))

    if state.awg.enabled:
        info(f"  AWG: включён  ({state.awg.interface} → {state.awg.exit_host}:{state.awg.exit_port})")

    print()
    if state.xray.domain:     info(f"  Домен/SNI:  {state.xray.domain}")
    if state.xray.uuid:       info(f"  UUID:       {state.xray.uuid}")
    if state.server_port:     info(f"  Порт:       {state.server_port}")
    if state.protocol_mode:   info(f"  Протокол:   {state.protocol_mode.upper()}")
    if state.xray.public_key: info(f"  Public Key: {state.xray.public_key}")
    if state.xray.short_id:   info(f"  Short ID:   {state.xray.short_id}")

    _prompt_enter()


# ─────────────────────────────────────────────────────────────────────────────
# ДИАГНОСТИКА
# ─────────────────────────────────────────────────────────────────────────────

def _menu_diagnostics(state: InstallerState) -> None:
    while True:
        _title("Диагностика")
        print("  1)  Полная диагностика")
        print("  2)  Сетевая диагностика")
        print("  3)  Трафик (Xray Stats API)")
        print("  4)  Быстрый статус")
        print("  5)  Перезапустить Xray / Nginx")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            from installer.diagnostics.health import run_full_health_check
            from installer.diagnostics.network import run_network_diagnostics
            _title("Полная диагностика")
            run_network_diagnostics(state.xray.domain, state.server_port)
            print()
            run_full_health_check(state.xray.domain, state.server_port)
            _prompt_enter()
        elif choice == "2":
            from installer.diagnostics.network import run_network_diagnostics
            run_network_diagnostics(state.xray.domain, state.server_port)
            _prompt_enter()
        elif choice == "3":
            from installer.diagnostics.xray_stats import print_traffic_stats
            print_traffic_stats()
            _prompt_enter()
        elif choice == "4":
            _do_quick_status()
            _prompt_enter()
        elif choice == "5":
            _restart_services(state)
        elif choice == "0":
            return
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _do_quick_status() -> None:
    from installer.core.shell import service_is_active
    from installer.services.xray import get_xray_version
    _title("Быстрый статус")
    _status_line("xray",  service_is_active("xray"),  get_xray_version())
    _status_line("nginx", service_is_active("nginx"), "")


def _restart_services(state: InstallerState) -> None:
    from installer.services.xray import restart_xray
    from installer.core.shell import service_restart, service_is_active

    _title("Перезапуск сервисов")
    ok = restart_xray()
    if not ok:
        warn("Xray не вышел в active — проверьте логи")
    if service_is_active("nginx") or Path("/usr/sbin/nginx").exists():
        service_restart("nginx", check=False)
        success("Nginx перезапущен")
    _prompt_enter()


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP / ROLLBACK
# ─────────────────────────────────────────────────────────────────────────────

def _manage_backup(state: InstallerState) -> None:
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
                    perform_rollback(backups[int(idx) - 1])
                    _prompt_enter()
                except (ValueError, IndexError):
                    warn("Неверный номер")
        elif choice == "0":
            return
        else:
            warn(f"Неизвестный выбор: {choice!r}")


# ─────────────────────────────────────────────────────────────────────────────
# ПОЛЬЗОВАТЕЛИ
# ─────────────────────────────────────────────────────────────────────────────

def _menu_users(state: InstallerState) -> None:
    from installer.services.users import (
        list_users, add_user, delete_user, get_user_link, save_user_link,
        get_config_path,
    )

    if not get_config_path():
        warn("Xray не установлен. Сначала выполните установку.")
        _prompt_enter()
        return

    while True:
        _title("Управление пользователями")
        print("  1)  Список пользователей")
        print("  2)  Добавить пользователя")
        print("  3)  Удалить пользователя")
        print("  4)  Показать ссылку / QR")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            _user_list()
        elif choice == "2":
            _user_add()
        elif choice == "3":
            _user_delete()
        elif choice == "4":
            _user_show_link()
        elif choice == "0":
            return
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _user_list() -> None:
    from installer.services.users import list_users
    _title("Список пользователей")
    users = list_users()
    if not users:
        info("Пользователи не найдены")
    else:
        print(f"  {'#':<4} {'Email':<30} {'UUID':<38} {'Flow'}")
        print("  " + "─" * 80)
        for i, u in enumerate(users, 1):
            print(f"  {i:<4} {u.get('email','—'):<30} {u.get('id','—'):<38} {u.get('flow','—')}")
    _prompt_enter()


def _user_add() -> None:
    from installer.services.users import add_user, get_user_link, save_user_link
    from installer.config_builders.client_links import print_qr

    _title("Добавить пользователя")

    while True:
        email = _prompt("Email/имя пользователя").strip()
        if email and ' ' not in email:
            break
        warn("Имя не может быть пустым или содержать пробелы")

    uuid_inp = _prompt("UUID (Enter = автогенерация)").strip()
    new_uuid = add_user(email, uuid_str=uuid_inp or None)
    if not new_uuid:
        _prompt_enter()
        return

    success(f"Пользователь '{email}' добавлен (UUID: {new_uuid})")
    link = get_user_link(email)
    if link:
        print(f"\n\033[1;36m{link}\033[0m")
        print_qr(link, label=email)
        save_user_link(email, link)
    _prompt_enter()


def _user_delete() -> None:
    from installer.services.users import delete_user

    _user_list()
    target = _prompt("Email или UUID для удаления").strip()
    if not target:
        return
    if delete_user(target):
        success(f"Пользователь '{target}' удалён")
    _prompt_enter()


def _user_show_link() -> None:
    from installer.services.users import get_user_link
    from installer.config_builders.client_links import print_qr

    _user_list()
    target = _prompt("Email или UUID").strip()
    if not target:
        return
    link = get_user_link(target)
    if link:
        print(f"\n\033[1;36m{link}\033[0m")
        print_qr(link, label=target)
    else:
        warn(f"Пользователь '{target}' не найден или ссылку получить не удалось")
    _prompt_enter()


def _show_client_info(state: InstallerState) -> None:
    from installer.config_builders.client_links import generate_client_links, print_qr

    if not state.xray.uuid:
        warn("Установка ещё не выполнена — нет клиентских данных")
        _prompt_enter()
        return

    _title("Клиентские данные")
    links = generate_client_links(state)
    if not links:
        warn("Нет данных для генерации ссылок")
        _prompt_enter()
        return

    for link in links:
        print(f"\n\033[1;36m{link}\033[0m")
        print_qr(link)
    _prompt_enter()


# ─────────────────────────────────────────────────────────────────────────────
# СЕТЬ
# ─────────────────────────────────────────────────────────────────────────────

def _menu_network(state: InstallerState) -> None:
    while True:
        _title("Сеть")
        print("  1)  WARP (Cloudflare)")
        print("  2)  DNSCrypt")
        print("  3)  Split Tunneling (раздельное туннелирование)")
        print("  4)  AS-маршрутизация (ASN routing)")
        print("  5)  Обновить Geo-файлы")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            _menu_warp(state)
        elif choice == "2":
            _menu_dnscrypt(state)
        elif choice == "3":
            _menu_split_tunnel(state)
        elif choice == "4":
            _menu_asn(state)
        elif choice == "5":
            _update_geo_files()
        elif choice == "0":
            return
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _menu_warp(state: InstallerState) -> None:
    from installer.services.warp import install_warp, connect_warp, get_warp_status

    while True:
        _title("WARP (Cloudflare)")
        ws = get_warp_status()
        info(f"Статус: {'установлен' if ws.get('installed') else 'не установлен'}")
        if ws.get("installed"):
            info(f"Подключение: {'активно' if ws.get('connected') else 'нет'}")
            info(f"Состояние:   {ws.get('status', '—')}")
        print()
        print("  1)  Установить WARP")
        print("  2)  Подключить WARP")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            ok = install_warp()
            if ok:
                success("WARP установлен")
                state.warp.installed = True
                state.save(STATE_FILE)
            _prompt_enter()
        elif choice == "2":
            ok = connect_warp()
            if ok:
                success("WARP подключён")
                state.warp.connected = True
                state.save(STATE_FILE)
            _prompt_enter()
        elif choice == "0":
            return


def _menu_dnscrypt(state: InstallerState) -> None:
    from installer.services.dnscrypt import install_dnscrypt, get_dnscrypt_actual_port
    from installer.core.shell import service_is_active

    while True:
        _title("DNSCrypt-proxy")
        active = service_is_active("dnscrypt-proxy")
        _status_line("dnscrypt-proxy", active)
        if state.dnscrypt_installed:
            info(f"Порт: {get_dnscrypt_actual_port()}")
        print()
        print("  1)  Установить DNSCrypt")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            ok = install_dnscrypt(state.pkg_mgr or "apt-get")
            if ok:
                success("DNSCrypt установлен")
                state.dnscrypt_installed = True
                state.use_dnscrypt = True
                state.save(STATE_FILE)
            _prompt_enter()
        elif choice == "0":
            return


def _menu_split_tunnel(state: InstallerState) -> None:
    from installer.config_builders.split_tunnel import (
        load_split_tunnel_custom, save_split_tunnel_custom,
        download_geo_files, build_split_tunnel_routing_rules,
    )

    while True:
        _title("Split Tunneling")
        domains, ips = load_split_tunnel_custom()
        info(f"Статус:  {'включено' if state.split_tunnel.enabled else 'выключено'}")
        info(f"Доменов: {len(domains)}")
        info(f"IP:      {len(ips)}")
        print()
        print("  1)  Включить split tunneling")
        print("  2)  Выключить split tunneling")
        print("  3)  Добавить домен")
        print("  4)  Добавить IP/CIDR")
        print("  5)  Показать текущий список")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            ok = download_geo_files()
            if ok:
                state.split_tunnel.enabled = True
                state.save(STATE_FILE)
                success("Split tunneling включён — перезапустите Xray для применения")
            _prompt_enter()
        elif choice == "2":
            state.split_tunnel.enabled = False
            state.save(STATE_FILE)
            success("Split tunneling выключен")
            _prompt_enter()
        elif choice == "3":
            d = _prompt("Домен (например: ok.ru)").strip()
            if d:
                domains.append(d)
                save_split_tunnel_custom(domains, ips)
                state.split_tunnel.extra_domains = domains
                state.save(STATE_FILE)
                success(f"Домен добавлен: {d}")
            _prompt_enter()
        elif choice == "4":
            ip = _prompt("IP или CIDR (например: 1.2.3.0/24)").strip()
            if ip:
                ips.append(ip)
                save_split_tunnel_custom(domains, ips)
                state.split_tunnel.extra_ips = ips
                state.save(STATE_FILE)
                success(f"IP добавлен: {ip}")
            _prompt_enter()
        elif choice == "5":
            _title("Split Tunneling: текущий список")
            if domains:
                info("Домены:"); [print(f"  - {d}") for d in domains]
            if ips:
                info("IP/CIDR:"); [print(f"  - {i}") for i in ips]
            if not domains and not ips:
                info("Список пуст")
            _prompt_enter()
        elif choice == "0":
            return


def _menu_asn(state: InstallerState) -> None:
    from installer.services.asn_routing import (
        load_asn_list, add_or_update_asn_route, remove_asn_route,
        show_cache_table, parse_asn_input,
    )
    from installer.core.constants import ASN_ACTION_DIRECT, ASN_ACTION_PROXY, ASN_ACTIONS

    while True:
        _title("AS-маршрутизация (ASN Routing)")
        routes = load_asn_list()
        if routes:
            print(f"  {'ASN':<8} {'Действие':<10} {'IPv4':<8} {'IPv6':<8} Описание")
            print("  " + "─" * 60)
            for r in routes:
                print(f"  {r.get('asn',''):<8} {r.get('action',''):<10} "
                      f"{r.get('ipv4_count',0):<8} {r.get('ipv6_count',0):<8} "
                      f"{r.get('description','')}")
        else:
            info("Нет настроенных AS-маршрутов")
        print()
        print("  1)  Добавить AS-маршрут (direct/proxy/block)")
        print("  2)  Удалить AS-маршрут")
        print("  3)  Показать кэш префиксов")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            raw = _prompt("Номер AS (например: 8359 или AS8359)").strip()
            asn = parse_asn_input(raw)
            if not asn:
                warn("Неверный номер AS")
                _prompt_enter()
                continue
            action = _prompt(f"Действие ({'/'.join(ASN_ACTIONS)})", default=ASN_ACTION_DIRECT).strip()
            if action not in ASN_ACTIONS:
                warn(f"Неизвестное действие: {action}")
                _prompt_enter()
                continue
            desc = _prompt("Описание (необязательно)", default="").strip()
            ok = add_or_update_asn_route(asn, action, desc)
            if ok:
                success(f"AS{asn} → {action}")
            _prompt_enter()
        elif choice == "2":
            raw = _prompt("Номер AS для удаления").strip()
            asn = parse_asn_input(raw)
            if asn and remove_asn_route(asn):
                success(f"AS{asn} удалён")
            _prompt_enter()
        elif choice == "3":
            show_cache_table()
            _prompt_enter()
        elif choice == "0":
            return


def _update_geo_files() -> None:
    from installer.services.xray_update import update_geo_files
    _title("Обновление Geo-файлов")
    ok = update_geo_files()
    if ok:
        success("Geo-файлы обновлены. Перезапустите Xray для применения.")
    _prompt_enter()


# ─────────────────────────────────────────────────────────────────────────────
# БЕЗОПАСНОСТЬ
# ─────────────────────────────────────────────────────────────────────────────

def _menu_security(state: InstallerState) -> None:
    while True:
        _title("Безопасность")
        print("  1)  Fail2ban (защита от брутфорса)")
        print("  2)  Nginx rate limiting")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            _setup_fail2ban(state)
        elif choice == "2":
            _setup_nginx_rate_limit()
        elif choice == "0":
            return
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _setup_fail2ban(state: InstallerState) -> None:
    from installer.services.fail2ban import setup_fail2ban
    from installer.core.shell import service_is_active

    _title("Fail2ban")
    active = service_is_active("fail2ban")
    _status_line("fail2ban", active)
    print()
    ans = _prompt("Установить/перенастроить fail2ban?", default="y").strip()
    if ans.lower() in ("y", "yes", "да"):
        setup_fail2ban(state.server_port)
    _prompt_enter()


def _setup_nginx_rate_limit() -> None:
    from installer.services.fail2ban import setup_nginx_rate_limit
    _title("Nginx Rate Limit")
    setup_nginx_rate_limit()
    _prompt_enter()


# ─────────────────────────────────────────────────────────────────────────────
# ОБСЛУЖИВАНИЕ
# ─────────────────────────────────────────────────────────────────────────────

def _menu_maintenance(state: InstallerState) -> None:
    while True:
        _title("Обслуживание")
        print("  1)  Обновить Xray-core")
        print("  2)  Управление logrotate")
        print("  3)  Плановый backup")
        print("  4)  Обновить geo-файлы (runetfreedom)")
        print("  5)  Удалить установку (Uninstall)")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            _do_xray_update()
        elif choice == "2":
            _menu_logrotate()
        elif choice == "3":
            _menu_scheduled_backup(state)
        elif choice == "4":
            _do_geo_update()
        elif choice == "5":
            _do_uninstall(state)
        elif choice == "0":
            return
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _do_xray_update() -> None:
    from installer.services.xray_update import (
        get_current_version, get_release_info, _version_norm,
        upgrade, restart_all_services, rollback_binary,
    )
    from installer.core.paths import XRAY_BACKUP_DIR

    _title("Обновление Xray-core")
    current = get_current_version()
    info(f"Текущая версия: {current}")
    info("Получение информации о релизах...")

    latest_info = get_release_info(prerelease=False)
    latest_tag  = latest_info.get("tag_name", "") if latest_info else ""
    pre_info    = get_release_info(prerelease=True)
    pre_tag     = pre_info.get("tag_name",  "") if pre_info else ""
    is_pre      = pre_info.get("prerelease", False) if pre_info else False

    cur_norm    = _version_norm(current)
    latest_norm = _version_norm(latest_tag) if latest_tag else cur_norm
    pre_norm    = _version_norm(pre_tag)    if pre_tag    else cur_norm

    has_latest = bool(latest_tag and latest_norm > cur_norm)
    has_pre    = bool(pre_tag and is_pre and pre_norm > cur_norm and pre_tag != latest_tag)

    if latest_tag:
        marker = " ← доступно" if has_latest else " (актуально)"
        info(f"Stable:     {latest_tag}{marker}")
    if pre_tag and is_pre:
        marker = " ← доступна prerelease" if has_pre else " (не новее)"
        info(f"Prerelease: {pre_tag}{marker}")

    if not has_latest and not has_pre:
        success("Xray актуален — обновлений нет")
        _prompt_enter()
        return

    choices = []
    if has_latest:
        choices.append(("1", f"Обновить до stable {latest_tag}", latest_tag, False))
    if has_pre:
        choices.append(("2" if has_latest else "1", f"Обновить до prerelease {pre_tag}", pre_tag, True))

    print()
    for key, label, _, _ in choices:
        print(f"  {key}) {label}")
    print("  0) Отмена")

    ch = _prompt("Выбор", default="0").strip()
    target_tag, target_pre = None, False
    for key, _, t, p in choices:
        if ch == key:
            target_tag, target_pre = t, p
            break

    if not target_tag:
        return

    if target_pre:
        warn("Внимание: prerelease версия может быть нестабильной!")
        if _prompt("Продолжить?", default="n").strip().lower() not in ("y", "yes"):
            return

    backups_before = set(XRAY_BACKUP_DIR.glob("xray_*")) if XRAY_BACKUP_DIR.exists() else set()

    ok = upgrade(target_tag, is_prerelease=target_pre)
    if not ok:
        warn("Обновление завершилось с ошибкой")
        _prompt_enter()
        return

    xray_started = restart_all_services()
    new_ver = get_current_version()

    if xray_started:
        success(f"Xray обновлён: {current} → {new_ver}")
        _prompt_enter()
        return

    warn("Xray не запустился после обновления!")
    all_backups  = sorted(XRAY_BACKUP_DIR.glob("xray_*")) if XRAY_BACKUP_DIR.exists() else []
    new_backups  = [b for b in all_backups if b not in backups_before]
    rollback_src = new_backups[-1] if new_backups else (all_backups[-1] if all_backups else None)

    if rollback_src:
        info(f"Доступен откат: {rollback_src.name}")
        if _prompt("Откатиться?", default="y").strip().lower() in ("y", "yes", ""):
            if rollback_binary(rollback_src):
                restart_all_services()
                success(f"Откат выполнен. Версия: {get_current_version()}")
    else:
        warn("Бэкап не найден — откат невозможен")
    _prompt_enter()


def _do_geo_update() -> None:
    from installer.services.xray_update import (
        geo_is_runetfreedom, update_geo_files,
    )
    from installer.core.shell import run as _run
    from installer.core.constants import XRAY_SERVICE_NAME

    _title("Обновление geo-файлов (runetfreedom)")

    if geo_is_runetfreedom():
        info("Обнаружены geo-файлы runetfreedom — обновляем до актуальных...")
    else:
        info("Стандартные geo-файлы. Будут заменены на runetfreedom...")
        ans = _prompt("Продолжить?", default="y").strip().lower()
        if ans not in ("y", "yes", "да", ""):
            return

    ok = update_geo_files()
    if ok:
        success("Geo-файлы успешно обновлены")
        info("Перезапускаем Xray для применения новых баз...")
        _run(["systemctl", "restart", XRAY_SERVICE_NAME], check=False, quiet=True)
    else:
        warn("Не удалось обновить один или несколько geo-файлов")
    _prompt_enter()


def _menu_logrotate() -> None:
    from installer.services.logrotate import (
        get_logrotate_status, configure_logrotate, force_rotate_now, show_logrotate_conf,
        apply_default_logrotate,
    )
    from installer.core.constants import LOGROTATE_DEFAULT_FREQ, LOGROTATE_DEFAULT_KEEP

    while True:
        _title("Logrotate")
        st = get_logrotate_status()
        info(f"Статус:    {'настроен' if st.get('configured') else 'не настроен'}")
        if st.get("configured"):
            info(f"Частота:   {st.get('frequency', '—')}")
            info(f"Хранить:   {st.get('keep_days', '—')} дней")
        print()
        print("  1)  Установить / перенастроить logrotate")
        print("  2)  Принудительная ротация сейчас")
        print("  3)  Показать текущий конфиг")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            freq = _prompt("Частота (daily/weekly/monthly)", default=LOGROTATE_DEFAULT_FREQ).strip()
            try:
                keep = int(_prompt("Хранить файлов", default=str(LOGROTATE_DEFAULT_KEEP)).strip())
            except ValueError:
                keep = LOGROTATE_DEFAULT_KEEP
            configure_logrotate(freq, keep)
            _prompt_enter()
        elif choice == "2":
            force_rotate_now()
            _prompt_enter()
        elif choice == "3":
            show_logrotate_conf()
            _prompt_enter()
        elif choice == "0":
            return


def _menu_scheduled_backup(state: InstallerState) -> None:
    from installer.core.backup import (
        create_scheduled_backup, setup_scheduled_backup_cron,
        list_backups,
    )

    _title("Плановый Backup")
    info(f"Автобэкап: {'включён' if state.scheduled_backup.enabled else 'выключен'}")
    info(f"Интервал:  {state.scheduled_backup.interval_days} дней")
    info(f"Хранить:   {state.scheduled_backup.keep_last} архивов")
    print()
    print("  1)  Создать backup сейчас")
    print("  2)  Включить автоматический backup")
    print("  3)  Список архивов")
    print("  0)  Назад")
    choice = _prompt("Выбор", default="0").strip()

    if choice == "1":
        p = create_scheduled_backup(keep_last=state.scheduled_backup.keep_last)
        if p:
            success(f"Backup создан: {p}")
        _prompt_enter()
    elif choice == "2":
        days = int(_prompt("Интервал (дней)", default=str(state.scheduled_backup.interval_days)).strip() or "1")
        state.scheduled_backup.enabled = True
        state.scheduled_backup.interval_days = days
        state.save(STATE_FILE)
        setup_scheduled_backup_cron(
            interval_days=days,
            hour=state.scheduled_backup.hour,
            minute=state.scheduled_backup.minute,
            keep_last=state.scheduled_backup.keep_last,
        )
        success("Автобэкап настроен")
        _prompt_enter()
    elif choice == "3":
        backups = list_backups()
        for b in backups:
            print(f"  {b}")
        if not backups:
            info("Архивы не найдены")
        _prompt_enter()


def _do_uninstall(state: InstallerState) -> None:
    from installer.core.shell import run as _run
    from installer.core.paths import XRAY_BIN, XRAY_CONFIG_DIR, XRAY_LOG_DIR, XRAY_SERVICE_FILE

    _title("Удаление VLESS Ultimate")
    warn("Будут удалены: Xray, конфиги, правила UFW, логи.")
    ans = _prompt("Введите 'yes' для подтверждения").strip()
    if ans.lower() != "yes":
        info("Отменено")
        return

    for svc in ("xray", "nginx", "dnscrypt-proxy"):
        _run(["systemctl", "stop",    svc], check=False, quiet=True)
        _run(["systemctl", "disable", svc], check=False, quiet=True)

    _run(["systemctl", "daemon-reload"], check=False, quiet=True)

    import shutil, tempfile
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    r = _run(["curl", "-fsSL", "--connect-timeout", "10",
               "https://github.com/XTLS/Xray-install/raw/main/install-release.sh",
               "-o", str(tmp_path)], check=False, quiet=True)
    if r.returncode == 0 and tmp_path.stat().st_size > 0:
        _run(["bash", str(tmp_path), "remove"], check=False, quiet=True)
    tmp_path.unlink(missing_ok=True)

    for d in (XRAY_CONFIG_DIR, XRAY_LOG_DIR, Path("/usr/local/etc/xray"),
              Path("/var/lib/xray")):
        shutil.rmtree(d, ignore_errors=True)
    XRAY_BIN.unlink(missing_ok=True)
    XRAY_SERVICE_FILE.unlink(missing_ok=True)
    XRAY_LOCK_FILE.unlink(missing_ok=True)

    state.progress.completed = False
    state.save(STATE_FILE)
    success("Удаление завершено")
    _prompt_enter()


# ─────────────────────────────────────────────────────────────────────────────
# AMNEZIAWG
# ─────────────────────────────────────────────────────────────────────────────

def _manage_awg(state: InstallerState) -> None:
    while True:
        _title("AmneziaWG 2.0")
        _show_awg_status(state)
        print()
        print("  1)  Включить/настроить AWG")
        print("  2)  Проверить туннель")
        print("  3)  Выключить AWG")
        print("  0)  Назад")
        choice = _prompt("Выбор", default="0").strip()

        if choice == "1":
            if _configure_awg_for_mode_b(state):
                success("AWG настроен")
            _prompt_enter()
        elif choice == "2":
            _verify_awg_tunnel(state)
            _prompt_enter()
        elif choice == "3":
            _disable_awg(state)
            _prompt_enter()
        elif choice == "0":
            return
        else:
            warn(f"Неизвестный выбор: {choice!r}")


def _show_awg_status(state: InstallerState) -> None:
    if state.awg.enabled:
        info(f"Статус: включён ({state.awg.interface})")
        info(f"Exit:   {state.awg.exit_host}:{state.awg.exit_port}")
        info(f"Client: {state.awg.client_ip}, {state.awg.client_ipv6}")
    else:
        info("Статус: выключен")


def _configure_awg_for_mode_b(state: InstallerState) -> bool:
    from installer.core.shell import command_exists, run
    from installer.services.awg import (
        is_awg_available, generate_awg_keys, build_client_config, apply_policy_routing,
    )

    if not is_awg_available() and not command_exists("wg"):
        warn("Не найден awg/wg. Установите AmneziaWG или wireguard-tools.")
        return False

    exit_host = _prompt("IP/домен зарубежного AWG-сервера", default=state.awg.exit_host or "").strip()
    if not exit_host:
        warn("AWG: адрес exit-сервера обязателен")
        return False

    try:
        exit_port = int(_prompt("UDP порт AWG-сервера", default=str(state.awg.exit_port or 51820)).strip())
    except ValueError:
        warn("AWG: порт должен быть числом")
        return False

    ssh_ip = _prompt("IP SSH-клиента для исключения из policy routing",
                     default=state.awg.ssh_client_ip or "").strip()

    state.awg.exit_host     = exit_host
    state.awg.exit_port     = exit_port
    state.awg.ssh_client_ip = ssh_ip

    if not (state.awg.client_privkey and state.awg.server_pubkey):
        info("Генерация AWG ключей...")
        try:
            srv_priv, srv_pub, cli_priv, cli_pub, psk = generate_awg_keys()
            state.awg.server_privkey = srv_priv
            state.awg.server_pubkey  = srv_pub
            state.awg.client_privkey = cli_priv
            state.awg.client_pubkey  = cli_pub
            state.awg.preshared_key  = psk
        except Exception as exc:
            warn(f"AWG: ошибка генерации ключей: {exc}")
            return False

    cfg_text = build_client_config(state.awg)
    AWG_CONF_DIR.mkdir(parents=True, exist_ok=True)
    AWG_CONF_FILE.write_text(cfg_text)
    AWG_CONF_FILE.chmod(0o600)

    quick = ("awg-quick" if command_exists("awg-quick")
             else "wg-quick" if command_exists("wg-quick") else "")
    if quick:
        run([quick, "down", state.awg.interface], check=False, quiet=True)
        up = run([quick, "up", str(AWG_CONF_FILE)], check=False, quiet=True)
        if up.returncode != 0:
            warn("Профиль сохранён, но интерфейс не поднялся автоматически")
    else:
        warn("Не найден awg-quick/wg-quick: профиль сохранён, поднимите вручную")

    apply_policy_routing(
        client_ip=state.awg.client_ip,
        interface=state.awg.interface,
        fwmark=state.awg.fwmark,
        route_table=state.awg.route_table,
        ssh_client_ip=state.awg.ssh_client_ip,
    )

    state.awg.enabled   = True
    state.awg.installed = True
    state.save(STATE_FILE)
    return True


def _verify_awg_tunnel(state: InstallerState) -> None:
    from installer.services.awg import verify_tunnel
    if not state.awg.enabled:
        warn("AWG выключен")
        return
    target = state.awg.server_ip.split("/")[0] if state.awg.server_ip else "10.66.66.1"
    verify_tunnel(server_ip=target, interface=state.awg.interface)


def _disable_awg(state: InstallerState) -> None:
    from installer.core.shell import command_exists, run
    quick = ("awg-quick" if command_exists("awg-quick")
             else "wg-quick" if command_exists("wg-quick") else "")
    if quick:
        run([quick, "down", state.awg.interface], check=False, quiet=True)
    state.awg.enabled = False
    state.save(STATE_FILE)
    success("AWG выключен")


# ─────────────────────────────────────────────────────────────────────────────
# ЗАВИСИМОСТИ ПРИ СТАРТЕ
# ─────────────────────────────────────────────────────────────────────────────

def ensure_startup_dependencies(pkg_mgr: str) -> None:
    """
    Проверяет базовые зависимости через shutil.which() и устанавливает
    только отсутствующие. Не вызывает apt при каждом старте.
    """
    from installer.core.shell import command_exists, run
    from installer.core.system import wait_apt_lock

    checks = {
        "curl":    "curl",
        "unzip":   "unzip",
        "openssl": "openssl",
        "dig":     "dnsutils",
        "jq":      "jq",
    }

    missing = {pkg for cmd, pkg in checks.items() if not command_exists(cmd)}
    present = {pkg for cmd, pkg in checks.items() if command_exists(cmd)}

    if present:
        log_to_file("INFO", f"Зависимости уже установлены: {', '.join(sorted(present))}")

    if not missing:
        info("Все базовые зависимости уже установлены")
        return

    info(f"Отсутствуют: {', '.join(sorted(missing))} — устанавливаю...")
    if pkg_mgr in ("apt-get", "apt"):
        wait_apt_lock()
        run(
            ["apt-get", "install", "-y", "-q", "--no-install-recommends"] + list(missing),
            env={"DEBIAN_FRONTEND": "noninteractive"},
            check=False, quiet=True,
        )
    elif pkg_mgr == "dnf":
        run(["dnf", "install", "-y"] + list(missing), check=False, quiet=True)

    installed_now = {pkg for cmd, pkg in checks.items() if command_exists(cmd) and pkg in missing}
    still_missing = missing - installed_now
    if installed_now:
        success(f"Установлено: {', '.join(sorted(installed_now))}")
    if still_missing:
        warn(f"Не удалось установить: {', '.join(sorted(still_missing))}")


# ─────────────────────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _prompt(msg: str, default: Optional[str] = None) -> str:
    prompt_str = f"  {msg} [{default}]: " if default is not None else f"  {msg}: "
    try:
        val = input(prompt_str).strip()
        return val if val else (default or "")
    except (EOFError, KeyboardInterrupt):
        raise


def _prompt_enter() -> None:
    try:
        input("\n  [Enter для продолжения] ")
    except (EOFError, KeyboardInterrupt):
        pass


def _status_line(name: str, active: bool, extra: str = "") -> None:
    status = "\033[0;32m● активен\033[0m" if active else "\033[0;31m○ неактивен\033[0m"
    suffix = f"  {extra}" if extra else ""
    print(f"  {name:<14} {status}{suffix}")


def _hr() -> None:
    print("  " + "─" * 50)


def _title(text: str) -> None:
    print()
    print(f"  \033[1;36m{'─' * 4} {text} {'─' * 4}\033[0m")
    print()

