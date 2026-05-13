"""
core/system.py — Системные утилиты: инициализация среды, пакетный менеджер, ресурсы.

Содержит функции, которые выполняют реальные системные операции:
  - создание директорий (ensure_dirs)
  - определение пакетного менеджера
  - установка пакетов
  - проверка ресурсов (RAM, CPU)
  - получение IP сервера

Эти функции НЕ вызываются при импорте — только из main-флоу.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Optional

from installer.core.shell import run, run_capture, command_exists
from installer.core.logging import info, warn, log_to_file
from installer.core.paths import all_dirs_to_create, LOG_FILE


def ensure_dirs() -> None:
    """
    Создаёт все служебные директории установщика.
    Вызывается один раз в самом начале main.py, до любых других операций.
    """
    for d in all_dirs_to_create():
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_to_file("WARN", f"Не удалось создать {d}: {e}")

    try:
        LOG_FILE.touch()
        LOG_FILE.chmod(0o600)
    except Exception:
        pass


def get_total_ram_mb() -> int:
    """Возвращает полный объём RAM в МБ. При ошибке — 1024."""
    try:
        result = subprocess.run(["free", "-m"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if line.startswith("Mem:"):
                return int(line.split()[1])
    except Exception:
        pass
    return 1024


def get_total_cpu() -> int:
    """Возвращает количество CPU-ядер. При ошибке — 1."""
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def get_adaptive_sysctl(param: str, ram_mb: int) -> str:
    """
    Возвращает адаптивное значение sysctl-параметра в зависимости от объёма RAM.

    Используется при генерации /etc/sysctl.d/99-vless-performance.conf.
    """
    if ram_mb < 512:
        mapping: dict[str, str] = {
            "overcommit": "0", "swappiness": "1",
            "conntrack": "262144", "file_max": "524288",
        }
    elif ram_mb < 1024:
        mapping = {
            "overcommit": "0", "swappiness": "5",
            "conntrack": "524288", "file_max": "1048576",
        }
    else:
        mapping = {
            "overcommit": "1", "swappiness": "10",
            "conntrack": "2000000", "file_max": "2097152",
        }
    return mapping.get(param, "")


def detect_pkg_mgr() -> str:
    """
    Определяет пакетный менеджер системы.
    Возвращает "apt" или "dnf" или "yum" или "" если не найден.
    """
    for mgr in ("apt-get", "apt", "dnf", "yum"):
        if command_exists(mgr):
            return mgr
    return ""


def pkg_update(pkg_mgr: str) -> None:
    """Обновляет индекс пакетов."""
    if pkg_mgr in ("apt-get", "apt"):
        run(["apt-get", "update", "-y"], quiet=True, check=False)
    elif pkg_mgr == "dnf":
        run(["dnf", "check-update"], quiet=True, check=False)


def pkg_install(pkg_mgr: str, *packages: str) -> None:
    """
    Устанавливает пакеты.

    Аргументы пакетов могут быть несколькими:
        pkg_install("apt-get", "curl", "wget", "jq")
    """
    if not packages:
        return
    if pkg_mgr in ("apt-get", "apt"):
        run(
            ["apt-get", "install", "-y", "--no-install-recommends"] + list(packages),
            quiet=True,
        )
    elif pkg_mgr == "dnf":
        run(["dnf", "install", "-y"] + list(packages), quiet=True)
    elif pkg_mgr == "yum":
        run(["yum", "install", "-y"] + list(packages), quiet=True)
    else:
        raise RuntimeError(f"Неизвестный пакетный менеджер: {pkg_mgr}")


def wait_apt_lock(max_wait: int = 120) -> None:
    """
    Ждёт освобождения apt-lock.
    Важно: apt падает с ошибкой если /var/lib/dpkg/lock-frontend занят
    (например, автообновления). Без ожидания установка прерывается.
    """
    import time
    lock_files = [
        "/var/lib/dpkg/lock-frontend",
        "/var/lib/apt/lists/lock",
        "/var/cache/apt/archives/lock",
    ]
    for _ in range(max_wait):
        locked = False
        for lf in lock_files:
            try:
                r = run_capture(["fuser", lf])
                if r.stdout.strip():
                    locked = True
                    break
            except Exception:
                pass
        if not locked:
            return
        time.sleep(1)
    warn("apt-lock не освободился за 120 секунд, продолжаем...")


def get_server_ip(ip_type: str = "4") -> str:
    """
    Определяет публичный IP сервера.

    Пробует несколько методов:
      1. curl к api ipify.org
      2. ip route get 8.8.8.8 (fallback без интернета)

    Args:
        ip_type: "4" — IPv4, "6" — IPv6.
    """
    if ip_type == "6":
        urls = ["https://api64.ipify.org"]
        flag = "-6"
    else:
        urls = ["https://api4.ipify.org"]
        flag = "-4"

    for url in urls:
        try:
            r = run_capture(["curl", "-s", flag, "-m", "5", url])
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass

    if ip_type == "4":
        try:
            r2 = run_capture(["ip", "route", "get", "8.8.8.8"])
            if r2.returncode == 0:
                for i, token in enumerate(r2.stdout.split()):
                    if token == "src" and i + 1 < len(r2.stdout.split()):
                        candidate = r2.stdout.split()[i + 1]
                        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", candidate):
                            return candidate
        except Exception:
            pass

    return ""


def country_flag_emoji(country_code: str) -> str:
    """
    Возвращает эмодзи флага страны по ISO 3166-1 alpha-2.
    Принцип: буквы A-Z маппируются на региональные индикаторы Unicode (U+1F1E6..U+1F1FF).
    """
    cc = country_code.upper().strip()
    if len(cc) != 2 or not cc.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in cc)


def get_server_country() -> tuple[str, str, str]:
    """
    Определяет страну сервера через ip-api.com.
    Возвращает (country_code, country_name, flag_emoji).
    """
    from installer.core.constants import GEO_API_URL
    try:
        r = run_capture(["curl", "-s", "--max-time", "8", GEO_API_URL])
        if r.returncode == 0 and r.stdout.strip():
            import json
            data = json.loads(r.stdout.strip())
            if data.get("status") == "success":
                cc   = data.get("countryCode", "??")
                name = data.get("country", "Unknown")
                return cc, name, country_flag_emoji(cc)
    except Exception:
        pass
    return "??", "Unknown", "🌐"


def check_ipv6_available() -> tuple[bool, str, bool]:
    """
    Проверяет доступность IPv6 на сервере.
    Возвращает (is_available, preflight_info, route_ok).
    """
    try:
        r = run_capture(["ip", "-6", "addr", "show", "scope", "global"])
        if r.returncode == 0 and r.stdout.strip():
            r2 = run_capture(["ip", "-6", "route", "show", "default"])
            route_ok = r2.returncode == 0 and r2.stdout.strip()
            return True, r.stdout.strip(), bool(route_ok)
    except Exception:
        pass
    return False, "", False


def set_config_owner(path: Path) -> None:
    """
    Устанавливает права 640 root:xray на файл конфига Xray.
    Xray-сервис запускается под User=xray, без правильных прав он падает с кодом 23.
    Использует числовой GID — не зависит от наличия chown в PATH.
    """
    import grp
    try:
        xray_gid = grp.getgrnam("xray").gr_gid
        os.chown(str(path), 0, xray_gid)
        os.chmod(str(path), 0o640)
    except KeyError:
        try:
            os.chmod(str(path), 0o644)
        except Exception:
            pass
    except Exception:
        pass


def generate_self_signed_cert(domain: str) -> None:
    """
    Генерирует самоподписанный TLS-сертификат для домена.
    Используется как fallback если certbot не смог получить сертификат.
    """
    from installer.core.paths import le_cert_dir
    le_path = le_cert_dir(domain)
    info(f"Генерация самоподписанного сертификата для {domain}...")
    le_path.mkdir(parents=True, exist_ok=True)
    run([
        "openssl", "req", "-x509", "-nodes", "-days", "365",
        "-newkey", "rsa:2048",
        "-keyout", str(le_path / "privkey.pem"),
        "-out",    str(le_path / "fullchain.pem"),
        "-subj",   f"/CN={domain}/O=SelfSigned/C=US",
        "-addext", f"subjectAltName=DNS:{domain}",
    ], quiet=True, check=False)
    try:
        (le_path / "privkey.pem").chmod(0o600)
        (le_path / "fullchain.pem").chmod(0o644)
    except Exception:
        pass
    from installer.core.logging import success
    success("Самоподписанный сертификат создан")

