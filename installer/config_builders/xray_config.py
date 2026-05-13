"""
config_builders/xray_config.py — Сборка JSON-конфигов для Xray-core.

Функции здесь являются чистыми builder-функциями:
  - принимают параметры явно (не читают global)
  - возвращают dict, который потом записывается в config.json
  - не выполняют никаких системных операций

Финальная запись конфига — в services/xray.py::write_xray_config().

Структура конфига Xray:
  log → dns → inbounds → outbounds → routing → stats → api → policy
"""

from __future__ import annotations

from typing import Any, Optional

from installer.core.state import InstallerState
from installer.core.constants import (
    XRAY_STATS_API_PORT,
    PROTOCOL_REALITY, PROTOCOL_XHTTP,
    AWG_FWMARK,
)


def build_log_block() -> dict:
    """
    Секция 'log' конфига Xray.
    loglevel=info нужен чтобы Xray писал трафик в access.log —
    это позволяет диагностике считать байты по тегам (метод 2).
    """
    return {
        "loglevel": "info",
        "access":   "/var/log/xray/access.log",
        "error":    "/var/log/xray/error.log",
    }


def build_dns_block(
    is_ipv6: bool,
    query_strategy: str,
    dnscrypt_host: str = "",
    dnscrypt_port: int = 5300,
    use_dnscrypt: bool = False,
) -> dict:
    """
    Секция 'dns' конфига Xray.

    Args:
        is_ipv6:        True если сервер имеет IPv6-связность.
        query_strategy: "UseIPv4", "UseIPv6v4" и т.д.
        use_dnscrypt:   True — DNS через локальный DNSCrypt-proxy.
    """
    if use_dnscrypt:
        servers: list = [
            {"address": dnscrypt_host or "127.0.0.1", "port": dnscrypt_port,
             "network": "udp", "skipFallback": False},
            {"address": "1.1.1.1", "port": 53, "network": "udp", "skipFallback": True},
            {"address": "8.8.8.8", "port": 53, "network": "udp", "skipFallback": True},
        ]
    elif is_ipv6:
        servers = [
            {"address": "2a10:50c0::1:ff",     "port": 53, "network": "udp", "skipFallback": False},
            {"address": "2a10:50c0::2:ff",      "port": 53, "network": "udp", "skipFallback": False},
            {"address": "2606:4700:4700::1111", "port": 53, "network": "udp", "skipFallback": False},
            {"address": "2606:4700:4700::1001", "port": 53, "network": "udp", "skipFallback": False},
            {"address": "2001:4860:4860::8888", "port": 53, "network": "udp", "skipFallback": True},
            {"address": "1.1.1.1",              "port": 53, "network": "udp", "skipFallback": True},
            {"address": "8.8.8.8",              "port": 53, "network": "udp", "skipFallback": True},
        ]
    else:
        servers = [
            {"address": "1.1.1.1", "port": 53, "network": "udp", "skipFallback": False},
            {"address": "8.8.8.8", "port": 53, "network": "udp", "skipFallback": False},
            {"address": "9.9.9.9", "port": 53, "network": "udp", "skipFallback": True},
        ]

    return {
        "servers": servers,
        "hosts": {
            "dns.google":         "8.8.8.8",
            "dns.cloudflare.com": "1.1.1.1",
            "localhost":          "127.0.0.1",
        },
        "disableCache":           False,
        "queryStrategy":          query_strategy,
        "disableFallback":        False,
        "disableFallbackIfMatch": True,
    }


def build_sockopt(tcp_no_delay: Optional[bool] = None) -> dict:
    """
    Секция sockopt для streamSettings.
    tcp_no_delay=True снижает задержку за счёт отключения алгоритма Nagle.
    """
    opt: dict = {}
    if tcp_no_delay is not None:
        opt["tcpNoDelay"] = tcp_no_delay
    return opt


def build_stats_blocks() -> dict:
    """
    Секции stats, api, policy и inbound для Stats API.

    Stats API позволяет диагностике получать точные накопленные байты
    по каждому outbound-тегу через 'xray api statsquery'.
    """
    return {
        "stats": {},
        "api": {
            "tag":      "xray-stats-api",
            "services": ["StatsService", "HandlerService"],
        },
        "policy": {
            "system": {
                "statsOutboundUplink":   True,
                "statsOutboundDownlink": True,
                "statsUserUplink":       True,
                "statsUserDownlink":     True,
            },
        },
        "_stats_inbound": {
            "listen":   "127.0.0.1",
            "port":     XRAY_STATS_API_PORT,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
            "tag":      "xray-stats-api",
        },
    }


def apply_stats_to_config(config: dict) -> None:
    """
    Встраивает Stats API в уже собранный dict конфига.
    Идемпотентен: повторный вызов не дублирует блоки.
    """
    blocks = build_stats_blocks()

    config.setdefault("stats", blocks["stats"])
    config.setdefault("api",   blocks["api"])

    policy_sys = config.setdefault("policy", {}).setdefault("system", {})
    policy_sys["statsOutboundUplink"]   = True
    policy_sys["statsOutboundDownlink"] = True
    policy_sys["statsUserUplink"]       = True
    policy_sys["statsUserDownlink"]     = True

    inbound = blocks["_stats_inbound"]
    inbounds = config.setdefault("inbounds", [])
    if not any(ib.get("tag") == "xray-stats-api" for ib in inbounds):
        inbounds.append(inbound)

    routing = config.setdefault("routing", {})
    rules   = routing.setdefault("rules", [])
    api_rule = {
        "type":        "field",
        "inboundTag":  ["xray-stats-api"],
        "outboundTag": "xray-stats-api",
    }
    if not any(r.get("inboundTag") == ["xray-stats-api"] for r in rules):
        rules.insert(0, api_rule)

    outbounds = config.setdefault("outbounds", [])
    if not any(ob.get("tag") == "xray-stats-api" for ob in outbounds):
        outbounds.append({"protocol": "freedom", "tag": "xray-stats-api"})


def build_reality_config(state: InstallerState, config_dir: str) -> dict:
    """
    Собирает полный конфиг Xray для VLESS + TCP + REALITY (Режим A).

    Args:
        state:      Текущее состояние установщика.
        config_dir: Путь к директории конфигов (/etc/xray).

    Returns:
        Словарь конфига, готовый для json.dumps().
    """
    xr = state.xray
    awg_on = state.awg.enabled

    query_strategy = "UseIPv6v4" if state.is_ipv6 else "UseIPv4"
    if xr.domain_strategy:
        query_strategy = xr.domain_strategy

    inbound: dict[str, Any] = {
        "tag":      "inbound-vless",
        "port":     state.server_port,
        "listen":   "::",
        "protocol": "vless",
        "settings": {
            "clients": [{
                "id":    xr.uuid,
                "email": f"user@{xr.domain}",
                **({"flow": state.xtls_flow} if state.xtls_flow else {}),
            }],
            "decryption": "none",
        },
        "sniffing": {
            "enabled":      True,
            "destOverride": ["http", "tls", "quic"],
            "metadataOnly": True,
            "routeOnly":    True,
        },
        "streamSettings": {
            "network":  "tcp",
            "sockopt":  build_sockopt(),
            "security": "reality",
            "realitySettings": {
                "show":        False,
                "dest":   (xr.reality_dest + ":443") if awg_on else xr.socket_path,
                "xver":        0 if awg_on else 1,
                "spiderX":     xr.spiderx,
                "serverNames": [xr.reality_dest if awg_on else xr.domain],
                "privateKey":  xr.private_key,
                "publicKey":   xr.public_key,
                "shortIds":    [xr.short_id],
            },
        },
    }

    outbounds: list = [
        {
            "protocol": "freedom",
            "tag":      "direct",
            "settings": {"domainStrategy": "UseIPv6v4"},
            **({"streamSettings": {"sockopt": {"mark": AWG_FWMARK}}} if awg_on else {}),
        },
        {"protocol": "blackhole", "tag": "BLOCK"},
    ]

    routing_rules: list = [
        {"type": "field", "ip": ["127.0.0.1/32", "::1/128"], "outboundTag": "direct"},
        {"type": "field", "protocol": ["bittorrent"], "outboundTag": "BLOCK"},
        {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
    ]

    config: dict[str, Any] = {
        "log": build_log_block(),
        "dns": build_dns_block(
            is_ipv6=state.is_ipv6,
            query_strategy=query_strategy,
            use_dnscrypt=state.use_dnscrypt,
            dnscrypt_host="127.0.0.1",
            dnscrypt_port=5300,
        ),
        "inbounds": [inbound],
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": routing_rules,
        },
    }

    apply_stats_to_config(config)
    return config


def build_xhttp_config(state: InstallerState, config_dir: str) -> dict:
    """
    Собирает полный конфиг Xray для VLESS + xHTTP + TLS (Режим A).
    Xray самостоятельно терминирует TLS на server_port.
    """
    xr   = state.xray
    xh   = state.xhttp
    cert = f"/etc/letsencrypt/live/{xr.domain}/fullchain.pem"
    key  = f"/etc/letsencrypt/live/{xr.domain}/privkey.pem"

    xhttp_settings = _build_xhttp_settings(xh)

    inbound: dict[str, Any] = {
        "tag":      "inbound-vless",
        "port":     state.server_port,
        "listen":   "::",
        "protocol": "vless",
        "settings": {
            "clients": [{"id": xr.uuid, "email": f"user@{xr.domain}"}],
            "decryption": "none",
        },
        "sniffing": {
            "enabled":      True,
            "destOverride": ["http", "tls", "quic"],
            "metadataOnly": True,
            "routeOnly":    True,
        },
        "streamSettings": {
            "network":     "xhttp",
            "security":    "tls",
            "xhttpSettings": xhttp_settings,
            "tlsSettings": {
                "serverName":  xr.domain,
                "certificates": [{
                    "certificateFile": cert,
                    "keyFile":         key,
                }],
                "minVersion": "1.2",
                "alpn": ["h2", "http/1.1"],
            },
            "sockopt": build_sockopt(tcp_no_delay=xh.tcp_no_delay),
        },
    }

    outbounds: list = [
        {"protocol": "freedom", "tag": "direct", "settings": {"domainStrategy": "UseIPv6v4"}},
        {"protocol": "blackhole", "tag": "BLOCK"},
    ]

    routing_rules: list = [
        {"type": "field", "ip": ["127.0.0.1/32", "::1/128"], "outboundTag": "direct"},
        {"type": "field", "protocol": ["bittorrent"], "outboundTag": "BLOCK"},
        {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
    ]

    config: dict[str, Any] = {
        "log": build_log_block(),
        "dns": build_dns_block(
            is_ipv6=state.is_ipv6,
            query_strategy="UseIPv6v4" if state.is_ipv6 else "UseIPv4",
            use_dnscrypt=state.use_dnscrypt,
        ),
        "inbounds": [inbound],
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": routing_rules,
        },
    }

    apply_stats_to_config(config)
    return config


def _build_xhttp_settings(xh: "XhttpParams") -> dict:
    """Формирует блок xhttpSettings из параметров xHTTP."""
    from installer.core.state import XhttpParams
    settings: dict[str, Any] = {
        "mode": xh.mode,
        "path": xh.path or "/",
    }
    if xh.padding_bytes:
        settings["xPaddingBytes"] = xh.padding_bytes
    if xh.no_sse_header:
        settings["noSSEHeader"] = True
    if xh.sc_stream_up_server_secs and xh.mode == "streamup":
        settings["scStreamUpServerSecs"] = xh.sc_stream_up_server_secs
    if xh.xmux_enabled:
        settings["xmux"] = {
            "maxConcurrency":     xh.xmux_max_concurrency,
            "maxConnections":     xh.xmux_max_connections,
            "cMaxReuseTimes":     xh.xmux_c_max_reuse_times,
            "hMaxRequestTimes":   xh.xmux_h_max_request_times,
            "hMaxReusableSecs":   xh.xmux_h_max_reusable_secs,
            "hKeepAlivePeriod":   xh.xmux_h_keep_alive_period,
        }
    return settings


def write_config(config: dict, config_path: "Path") -> None:
    """
    Записывает конфиг в файл и создаёт симлинк /usr/local/etc/xray/config.json.
    Устанавливает права root:xray 640.
    """
    import json
    import os
    import grp
    from pathlib import Path as _Path

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))

    try:
        xray_gid = grp.getgrnam("xray").gr_gid
        os.chown(str(config_path), 0, xray_gid)
        os.chmod(str(config_path), 0o640)
    except Exception:
        try:
            os.chmod(str(config_path), 0o600)
        except Exception:
            pass

    alt_dir = _Path("/usr/local/etc/xray")
    if alt_dir.exists():
        alt_cfg = alt_dir / "config.json"
        alt_cfg.unlink(missing_ok=True)
        try:
            alt_cfg.symlink_to(config_path)
        except Exception:
            pass

