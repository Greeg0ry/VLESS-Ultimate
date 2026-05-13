"""
services/users.py — Управление пользователями Xray (VLESS clients).

CRUD-операции над секцией inbounds[0].settings.clients в config.json.
Все изменения применяются через xray_safe_apply_config — с pre-flight
тестом и авторотационным rollback.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Optional

from installer.core.logging import info, success, warn, log_to_file
from installer.core.shell import run_capture
from installer.core.paths import XRAY_CONFIG_FILE, XRAY_ALT_CONFIG


def get_config_path() -> Optional[Path]:
    """Возвращает путь к активному config.json или None."""
    for p in (XRAY_CONFIG_FILE, XRAY_ALT_CONFIG):
        if p.exists():
            return p
    return None


def read_config(cfg: Path) -> dict:
    """Читает config.json и возвращает dict."""
    return json.loads(cfg.read_text())


def write_and_apply_config(cfg: Path, data: dict) -> bool:
    """
    Записывает изменённый конфиг и применяет его через xray_safe_apply_config.
    Возвращает True если Xray поднялся после применения.
    """
    from installer.services.xray import xray_safe_apply_config
    return xray_safe_apply_config(data, cfg_path=cfg, reason="user-management")


def list_users(cfg: Optional[Path] = None) -> list[dict]:
    """Возвращает список клиентов из первого inbound."""
    cfg = cfg or get_config_path()
    if not cfg:
        return []
    try:
        data = read_config(cfg)
        return data.get("inbounds", [{}])[0].get("settings", {}).get("clients", [])
    except Exception as e:
        warn(f"Не удалось прочитать конфиг: {e}")
        return []


def add_user(email: str, uuid_str: Optional[str] = None,
             flow: Optional[str] = None) -> Optional[str]:
    """
    Добавляет нового клиента.

    Args:
        email:    Имя/email пользователя (уникальное).
        uuid_str: UUID (генерируется автоматически если не передан).
        flow:     XTLS flow (берётся из конфига если не передан).

    Returns:
        UUID созданного пользователя или None при ошибке.
    """
    cfg = get_config_path()
    if not cfg:
        warn("Xray не установлен — config.json не найден")
        return None

    new_uuid = uuid_str or str(uuid.uuid4())

    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
                    new_uuid, re.IGNORECASE):
        warn(f"Неверный формат UUID: {new_uuid}")
        return None

    try:
        data = read_config(cfg)
        clients = data["inbounds"][0]["settings"]["clients"]

        if any(c.get("email") == email for c in clients):
            warn(f"Пользователь '{email}' уже существует")
            return None

        net = data["inbounds"][0].get("streamSettings", {}).get("network", "tcp")
        client: dict = {"id": new_uuid, "email": email}

        if flow is None and net != "xhttp":
            existing_flow = clients[0].get("flow", "") if clients else ""
            flow = existing_flow or ""
        if flow:
            client["flow"] = flow

        clients.append(client)
        write_and_apply_config(cfg, data)
        log_to_file("USER_ADD", f"email={email} uuid={new_uuid}")
        return new_uuid

    except Exception as e:
        warn(f"Ошибка добавления пользователя: {e}")
        return None


def delete_user(target: str) -> bool:
    """
    Удаляет пользователя по email или UUID.
    Не позволяет удалить последнего пользователя.

    Returns:
        True если пользователь удалён.
    """
    cfg = get_config_path()
    if not cfg:
        warn("Xray не установлен")
        return False

    try:
        data = read_config(cfg)
        clients = data["inbounds"][0]["settings"]["clients"]
        matched = [c for c in clients if c.get("email") == target or c.get("id") == target]

        if not matched:
            warn(f"Пользователь '{target}' не найден")
            return False
        if len(clients) == 1:
            warn("Нельзя удалить последнего пользователя")
            return False

        new_clients = [c for c in clients
                       if c.get("email") != target and c.get("id") != target]
        data["inbounds"][0]["settings"]["clients"] = new_clients
        write_and_apply_config(cfg, data)

        email = matched[0].get("email", target)
        log_to_file("USER_DEL", f"email={email}")
        for p in (f"/root/vless_link_{email}.txt", f"/root/vless_qr_{email}.png"):
            Path(p).unlink(missing_ok=True)
        return True

    except Exception as e:
        warn(f"Ошибка удаления пользователя: {e}")
        return False


def get_user_link(target: str) -> str:
    """
    Генерирует VLESS-ссылку для пользователя по email или UUID.
    Читает параметры из активного config.json.

    Returns:
        VLESS URI или пустую строку при ошибке.
    """
    from urllib.parse import quote
    from installer.core.system import get_server_ip

    cfg = get_config_path()
    if not cfg:
        return ""

    try:
        data = read_config(cfg)
        clients = data["inbounds"][0]["settings"]["clients"]
        found = next((c for c in clients
                      if c.get("email") == target or c.get("id") == target), None)
        if not found:
            return ""

        uuid_str = found["id"]
        email = found.get("email", uuid_str)
        inb = data["inbounds"][0]
        ss  = inb.get("streamSettings", {})
        net = ss.get("network", "tcp")
        port = inb.get("port", 443)

        label = quote(email, safe="")
        host  = get_server_ip("4") or ""

        if net == "xhttp":
            tls = ss.get("tlsSettings", {})
            xh  = ss.get("xhttpSettings", {})
            domain = tls.get("serverName", host)
            path = quote(xh.get("path", "/"), safe="/")
            return (f"vless://{uuid_str}@{domain}:{port}"
                    f"?type=xhttp&security=tls&sni={domain}"
                    f"&path={path}&fp=chrome#{label}")
        else:
            rs   = ss.get("realitySettings", {})
            sni  = (rs.get("serverNames") or [""])[0]
            pbk  = rs.get("publicKey", "")
            sid  = (rs.get("shortIds") or [""])[0]
            host = host or sni
            return (f"vless://{uuid_str}@{host}:{port}"
                    f"?type=tcp&security=reality&pbk={pbk}"
                    f"&fp=chrome&sni={sni}&sid={sid}"
                    f"&flow=xtls-rprx-vision#{label}")

    except Exception as e:
        warn(f"Ошибка генерации ссылки: {e}")
        return ""


def save_user_link(email: str, link: str) -> None:
    """Сохраняет VLESS-ссылку в файл /root/vless_link_<email>.txt."""
    if not link:
        return
    p = Path(f"/root/vless_link_{email}.txt")
    try:
        p.write_text(link)
        p.chmod(0o600)
        success(f"Ссылка сохранена: {p}")
    except Exception as e:
        warn(f"Не удалось сохранить ссылку: {e}")

