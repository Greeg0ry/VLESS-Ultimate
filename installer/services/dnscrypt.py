"""
services/dnscrypt.py — Установка и настройка DNSCrypt-proxy.

DNSCrypt шифрует DNS-запросы, предотвращая перехват и подмену.
Xray использует DNSCrypt как upstream DNS, если он установлен.

Логика выбора DNS в конфиге Xray:
  - DNSCrypt установлен и активен → 127.0.0.1:DNSCRYPT_PORT (первичный)
  - DNSCrypt не установлен, IPv6 доступен → IPv6-серверы AdGuard/CF/Google
  - Иначе → IPv4-серверы 1.1.1.1 / 8.8.8.8 / 9.9.9.9
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Optional

from installer.core.shell import run, run_capture, command_exists
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import DNSCRYPT_BIN, DNSCRYPT_CONF_DIR, DNSCRYPT_CONF, DNSCRYPT_SERVICE
from installer.core.constants import DNSCRYPT_SERVICE_NAME, DNSCRYPT_LISTEN_ADDR, DNSCRYPT_LISTEN_PORT


def install_dnscrypt(pkg_mgr: str = "apt-get") -> bool:
    """
    Устанавливает DNSCrypt-proxy.

    Метод 1: Из системного репозитория (apt).
    Метод 2: Прямая загрузка бинарника с GitHub (если apt-версия устарела).

    Returns:
        True если установка прошла успешно.
    """
    info("Установка DNSCrypt-proxy...")

    if pkg_mgr in ("apt-get", "apt"):
        run(["apt-get", "install", "-y", "-q", "dnscrypt-proxy"],
            env={"DEBIAN_FRONTEND": "noninteractive"},
            check=False, quiet=True)

    if DNSCRYPT_BIN.exists() or command_exists("dnscrypt-proxy"):
        success("DNSCrypt-proxy установлен из репозитория")
        _configure_dnscrypt()
        return True

    info("Пробую прямую загрузку DNSCrypt...")
    installed = _try_download_dnscrypt()
    if installed:
        _configure_dnscrypt()
        return True

    warn("Не удалось установить DNSCrypt-proxy")
    return False


def _configure_dnscrypt() -> None:
    """Создаёт конфиг DNSCrypt-proxy и настраивает systemd-сервис."""
    DNSCRYPT_CONF_DIR.mkdir(parents=True, exist_ok=True)

    config_text = textwrap.dedent(f"""\
        # DNSCrypt-proxy configuration
        # Генерируется VLESS Ultimate Installer

        listen_addresses = ['{DNSCRYPT_LISTEN_ADDR}:{DNSCRYPT_LISTEN_PORT}']
        max_clients = 250

        ipv4_servers = true
        ipv6_servers = false
        dnscrypt_servers = true
        doh_servers = true

        require_dnssec = false
        require_nolog = true
        require_nofilter = true

        server_names = ['cloudflare', 'google', 'adguard']

        [sources]
          [sources.public-resolvers]
          urls = ['https://raw.githubusercontent.com/DNSCrypt/dnscrypt-resolvers/master/v3/public-resolvers.md',
                  'https://download.dnscrypt.info/resolvers-list/v3/public-resolvers.md']
          cache_file = '{DNSCRYPT_CONF_DIR}/public-resolvers.md'
          minisign_key = 'RWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3'
          refresh_delay = 72
    """)
    DNSCRYPT_CONF.write_text(config_text)

    if not Path("/lib/systemd/system/dnscrypt-proxy.service").exists():
        _create_dnscrypt_service()

    run(["systemctl", "daemon-reload"], quiet=True, check=False)
    run(["systemctl", "enable", DNSCRYPT_SERVICE_NAME], check=False, quiet=True)
    run(["systemctl", "restart", DNSCRYPT_SERVICE_NAME], check=False, quiet=True)
    success("DNSCrypt-proxy настроен")


def _create_dnscrypt_service() -> None:
    """Создаёт systemd-юнит для DNSCrypt-proxy."""
    bin_path = DNSCRYPT_BIN if DNSCRYPT_BIN.exists() else Path("/usr/sbin/dnscrypt-proxy")
    DNSCRYPT_SERVICE.write_text(textwrap.dedent(f"""\
        [Unit]
        Description=DNSCrypt-proxy client
        Documentation=https://github.com/DNSCrypt/dnscrypt-proxy
        After=network.target

        [Service]
        ExecStart={bin_path} -config {DNSCRYPT_CONF}
        Restart=on-failure
        RestartSec=5s

        [Install]
        WantedBy=multi-user.target
    """))


def _try_download_dnscrypt() -> bool:
    """Пробует скачать DNSCrypt-proxy с GitHub. Возвращает True при успехе."""
    import json, tempfile, shutil
    api_url = "https://api.github.com/repos/DNSCrypt/dnscrypt-proxy/releases/latest"
    try:
        r = run_capture(["curl", "-fsSL", "--max-time", "10", api_url])
        if r.returncode != 0:
            return False
        data = json.loads(r.stdout)
        asset = next(
            (a for a in data.get("assets", []) if "linux_x86_64" in a["name"]),
            None
        )
        if not asset:
            return False

        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "dnscrypt.tar.gz"
            r2 = run(["curl", "-fsSL", asset["browser_download_url"], "-o", str(archive)],
                     check=False, quiet=True)
            if r2.returncode != 0:
                return False
            run(["tar", "-xzf", str(archive), "-C", tmpdir], check=False, quiet=True)
            for f in Path(tmpdir).rglob("dnscrypt-proxy"):
                if f.is_file():
                    shutil.copy2(f, DNSCRYPT_BIN)
                    DNSCRYPT_BIN.chmod(0o755)
                    return True
    except Exception as e:
        log_to_file("WARN", f"Ошибка загрузки DNSCrypt: {e}")
    return False


def get_dnscrypt_actual_port() -> int:
    """
    Определяет реальный порт, на котором слушает DNSCrypt-proxy.
    Использует ss -ulnp, затем парсит конфиг-файл.
    Возвращает DNSCRYPT_LISTEN_PORT по умолчанию.
    """
    try:
        r = run_capture(["ss", "-ulnp"])
        for line in r.stdout.splitlines():
            if "dnscrypt" in line.lower():
                m = re.search(r':(\d+)\s', line)
                if m:
                    return int(m.group(1))
    except Exception:
        pass

    if DNSCRYPT_CONF.exists():
        try:
            content = DNSCRYPT_CONF.read_text()
            m = re.search(r'listen_addresses\s*=.*?:(\d+)', content, re.MULTILINE)
            if m:
                return int(m.group(1))
        except Exception:
            pass

    return DNSCRYPT_LISTEN_PORT

