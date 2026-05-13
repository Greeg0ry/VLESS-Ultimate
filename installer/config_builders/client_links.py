"""
config_builders/client_links.py — Генерация VLESS-ссылок и QR-кодов для клиентов.

Функции генерируют URI вида:
  vless://UUID@HOST:PORT?security=reality&pbk=...&sid=...&fp=...&spx=...#label
"""

from __future__ import annotations

import random
import string
import uuid
import re
from typing import Optional
from urllib.parse import quote

from installer.core.state import InstallerState
from installer.core.constants import PROTOCOL_REALITY, PROTOCOL_XHTTP


def gen_uuid() -> str:
    """Генерирует новый UUID v4."""
    return str(uuid.uuid4())


def gen_hex(n: int = 8) -> str:
    """
    Генерирует случайную hex-строку длиной n байт (2n символов).
    Использует openssl rand если доступен, иначе random.choices.
    """
    import subprocess
    try:
        r = subprocess.run(["openssl", "rand", "-hex", str(n)],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ''.join(random.choices('0123456789abcdef', k=n * 2))


def gen_spiderx() -> str:
    """Генерирует случайный spiderX путь для REALITY (вида /randomstring)."""
    chars = string.ascii_lowercase + string.digits
    length = random.randint(6, 15)
    return '/' + ''.join(random.choices(chars, k=length))


def gen_vless_link(
    host: str,
    uuid_str: str,
    pbk: str,
    short_id: str,
    sni: str,
    spiderx: str,
    port: int = 443,
    fp: str = "chrome",
    flow: str = "xtls-rprx-vision",
    protocol_mode: str = PROTOCOL_REALITY,
    xhttp_path: str = "",
    label: str = "",
) -> str:
    """
    Формирует VLESS URI для импорта в клиент (v2rayNG, NekoBox, Hiddify и т.д.).

    Args:
        host:          IP или домен сервера.
        uuid_str:      UUID пользователя.
        pbk:           Public key (только для REALITY).
        short_id:      Short ID (только для REALITY).
        sni:           SNI (домен для маскировки).
        spiderx:       SpiderX path (только для REALITY).
        port:          Порт сервера.
        fp:            Fingerprint (chrome, firefox, safari, ...).
        flow:          XTLS flow (xtls-rprx-vision или пусто).
        protocol_mode: "reality" или "xhttp".
        xhttp_path:    HTTP path для xHTTP (только для xhttp).
        label:         Метка соединения (#label в конце URI).

    Returns:
        Строка URI вида vless://...
    """
    if protocol_mode == PROTOCOL_XHTTP:
        path_enc = quote(xhttp_path or "/", safe="/")
        params = (
            f"type=xhttp"
            f"&security=tls"
            f"&sni={sni}"
            f"&fp={fp}"
            f"&path={path_enc}"
        )
    else:
        params = (
            f"type=tcp"
            f"&security=reality"
            f"&pbk={pbk}"
            f"&sid={short_id}"
            f"&sni={sni}"
            f"&fp={fp}"
            f"&spx={quote(spiderx, safe='/')}"
        )
        if flow:
            params += f"&flow={flow}"

    lbl = label or f"VLESS-{host}"
    return f"vless://{uuid_str}@{host}:{port}?{params}#{quote(lbl, safe='')}"


def generate_client_links(state: InstallerState) -> list[str]:
    """
    Генерирует список VLESS-ссылок для всех вариантов подключения:
      - IPv4
      - IPv6 (если доступен)
      - домен

    Args:
        state: Текущее состояние установщика.

    Returns:
        Список VLESS URI.
    """
    from installer.core.system import get_server_ip

    xr  = state.xray
    links: list[str] = []

    common = dict(
        uuid_str=xr.uuid,
        pbk=xr.public_key,
        short_id=xr.short_id,
        sni=xr.domain,
        spiderx=xr.spiderx,
        port=state.server_port,
        fp="chrome",
        flow=state.xtls_flow,
        protocol_mode=state.protocol_mode,
        xhttp_path=state.xhttp.path,
    )

    ipv4 = get_server_ip("4")
    if ipv4:
        links.append(gen_vless_link(host=ipv4, label=f"VLESS-IPv4-{ipv4}", **common))

    if state.is_ipv6:
        ipv6 = get_server_ip("6")
        if ipv6:
            links.append(gen_vless_link(host=f"[{ipv6}]", label=f"VLESS-IPv6", **common))

    if xr.domain:
        links.append(gen_vless_link(host=xr.domain, label=f"VLESS-{xr.domain}", **common))

    return links


def print_qr(link: str, label: str = "") -> None:
    """
    Выводит QR-код для VLESS-ссылки в терминал.
    Требует установленного qrencode или пакета qrcode.
    """
    import subprocess
    import sys

    if label:
        print(f"\n  📱 {label}")

    try:
        r = subprocess.run(
            ["qrencode", "-t", "UTF8", "-m", "2", link],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            print(r.stdout)
            return
    except Exception:
        pass

    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(link)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        return
    except ImportError:
        pass

    print(f"  {link}")
    print(f"  (установи qrencode для QR-кода: apt install qrencode)")


def parse_vless_link(link: str) -> Optional[dict]:
    """
    Парсит VLESS URI и возвращает словарь параметров.
    Возвращает None если URI невалиден.

    Поддерживает REALITY и xHTTP.
    """
    from urllib.parse import urlparse, parse_qs, unquote

    link = link.strip()
    if not link.startswith("vless://"):
        return None

    try:
        parsed = urlparse(link)
        uuid_str = parsed.username or ""
        host = parsed.hostname or ""
        port = parsed.port or 443
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        fragment = unquote(parsed.fragment)

        host = host.strip("[]")

        return {
            "uuid":      uuid_str,
            "host":      host,
            "port":      port,
            "security":  params.get("security", ""),
            "type":      params.get("type", "tcp"),
            "pbk":       params.get("pbk", ""),
            "sid":       params.get("sid", ""),
            "sni":       params.get("sni", ""),
            "fp":        params.get("fp", "chrome"),
            "spx":       params.get("spx", ""),
            "flow":      params.get("flow", ""),
            "path":      params.get("path", ""),
            "label":     fragment,
        }
    except Exception:
        return None


def export_clash_config(state: "InstallerState", output_dir: Optional[str] = None) -> Optional[str]:
    """
    Генерирует готовый конфиг Clash Meta (YAML) для клиента.

    Args:
        state:      Текущее состояние установщика.
        output_dir: Директория для сохранения (по умолчанию /root/xray-client-configs/).

    Returns:
        Путь к созданному файлу или None при ошибке.
    """
    import yaml

    from installer.core.system import get_server_ip
    from installer.core.constants import PROTOCOL_REALITY, CLIENT_CONFIGS_DIR

    xr = state.xray
    host = xr.domain or get_server_ip("4") or "YOUR_SERVER_IP"
    out_dir = Path(output_dir or CLIENT_CONFIGS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "clash-meta.yaml"

    if state.protocol_mode == PROTOCOL_REALITY:
        proxy = {
            "name":           f"VLESS-REALITY-{host}",
            "type":           "vless",
            "server":         host,
            "port":           state.server_port,
            "uuid":           xr.uuid,
            "network":        "tcp",
            "tls":            True,
            "udp":            True,
            "flow":           state.xtls_flow or "",
            "reality-opts": {
                "public-key": xr.public_key,
                "short-id":   xr.short_id,
            },
            "client-fingerprint": "chrome",
            "servername":    xr.domain,
        }
    else:
        proxy = {
            "name":           f"VLESS-TLS-{host}",
            "type":           "vless",
            "server":         host,
            "port":           state.server_port,
            "uuid":           xr.uuid,
            "network":        "xhttp",
            "tls":            True,
            "udp":            True,
            "servername":     xr.domain,
            "xhttp-opts": {
                "path": state.xhttp.path or "/",
                "mode": state.xhttp.mode,
            },
            "client-fingerprint": "chrome",
        }

    config = {
        "proxies": [proxy],
        "proxy-groups": [{
            "name":    "🚀 Proxy",
            "type":    "select",
            "proxies": [proxy["name"]],
        }],
        "rules": ["MATCH,🚀 Proxy"],
    }

    try:
        out_path.write_text(yaml.dump(config, allow_unicode=True, sort_keys=False))
        return str(out_path)
    except Exception as e:
        import json
        fallback = out_path.with_suffix(".json")
        fallback.write_text(json.dumps(config, indent=2, ensure_ascii=False))
        return str(fallback)


def export_singbox_config(state: "InstallerState", output_dir: Optional[str] = None) -> Optional[str]:
    """
    Генерирует готовый конфиг Sing-box (JSON) для клиента.

    Args:
        state:      Текущее состояние установщика.
        output_dir: Директория для сохранения.

    Returns:
        Путь к созданному файлу или None при ошибке.
    """
    import json

    from installer.core.system import get_server_ip
    from installer.core.constants import PROTOCOL_REALITY, CLIENT_CONFIGS_DIR

    xr = state.xray
    host = xr.domain or get_server_ip("4") or "YOUR_SERVER_IP"
    out_dir = Path(output_dir or CLIENT_CONFIGS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sing-box.json"

    if state.protocol_mode == PROTOCOL_REALITY:
        outbound = {
            "type":    "vless",
            "tag":     "proxy-out",
            "server":  host,
            "server_port": state.server_port,
            "uuid":    xr.uuid,
            "flow":    state.xtls_flow or "",
            "tls": {
                "enabled":    True,
                "server_name": xr.domain,
                "utls": {"enabled": True, "fingerprint": "chrome"},
                "reality": {
                    "enabled":    True,
                    "public_key": xr.public_key,
                    "short_id":   xr.short_id,
                },
            },
        }
    else:
        outbound = {
            "type":    "vless",
            "tag":     "proxy-out",
            "server":  host,
            "server_port": state.server_port,
            "uuid":    xr.uuid,
            "transport": {
                "type": "xhttp",
                "path": state.xhttp.path or "/",
            },
            "tls": {
                "enabled":     True,
                "server_name": xr.domain,
                "utls": {"enabled": True, "fingerprint": "chrome"},
            },
        }

    config = {
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct-out"},
        ],
        "route": {
            "rules": [],
            "final": "proxy-out",
        },
    }

    out_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    return str(out_path)


def export_client_configs(state: "InstallerState", output_dir: Optional[str] = None,
                          remote_host: Optional[str] = None) -> list[str]:
    """
    Генерирует все клиентские конфиги (Clash Meta + Sing-box) и выводит команды scp.

    Args:
        state:       Текущее состояние установщика.
        output_dir:  Директория для сохранения.
        remote_host: Если указан — предлагает команду sftp для передачи.

    Returns:
        Список путей к созданным файлам.
    """
    from installer.core.constants import CLIENT_CONFIGS_DIR
    out_dir = output_dir or CLIENT_CONFIGS_DIR
    paths = []

    clash_path = export_clash_config(state, out_dir)
    if clash_path:
        paths.append(clash_path)
        print(f"\n  📦 Clash Meta: {clash_path}")
        print(f"     scp root@{state.xray.domain or 'YOUR_IP'}:{clash_path} .")

    singbox_path = export_singbox_config(state, out_dir)
    if singbox_path:
        paths.append(singbox_path)
        print(f"\n  📦 Sing-box:   {singbox_path}")
        print(f"     scp root@{state.xray.domain or 'YOUR_IP'}:{singbox_path} .")

    if remote_host and paths:
        print(f"\n  📡 Передача на {remote_host}:")
        print(f"     sftp {remote_host} <<'EOF'")
        for p in paths:
            print(f"     put {p}")
        print("     EOF")

    return paths
    """
    Парсит VLESS URI и возвращает словарь параметров.
    Возвращает None если URI невалиден.

    Поддерживает REALITY и xHTTP.
    """
    from urllib.parse import urlparse, parse_qs, unquote

    link = link.strip()
    if not link.startswith("vless://"):
        return None

    try:
        parsed = urlparse(link)
        uuid_str = parsed.username or ""
        host = parsed.hostname or ""
        port = parsed.port or 443
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        fragment = unquote(parsed.fragment)

        host = host.strip("[]")

        return {
            "uuid":      uuid_str,
            "host":      host,
            "port":      port,
            "security":  params.get("security", ""),
            "type":      params.get("type", "tcp"),
            "pbk":       params.get("pbk", ""),
            "sid":       params.get("sid", ""),
            "sni":       params.get("sni", ""),
            "fp":        params.get("fp", "chrome"),
            "spx":       params.get("spx", ""),
            "flow":      params.get("flow", ""),
            "path":      params.get("path", ""),
            "label":     fragment,
        }
    except Exception:
        return None


