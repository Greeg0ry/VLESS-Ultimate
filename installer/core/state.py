"""
core/state.py — Dataclass-модели состояния установщика.

Заменяет ~50 глобальных переменных в оригинальном скрипте.
Состояние хранится в единственном экземпляре InstallerState,
который передаётся через функции, а не через global.

Правило: этот модуль не производит никакого I/O при импорте.
Сохранение/загрузка состояния — через методы save()/load() класса.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from installer.core.constants import (
    PROTOCOL_REALITY, XTLS_FLOW_VISION,
    XHTTP_MODE_STREAMUP,
    DEFAULT_SERVER_PORT,
    AWG_DEFAULT_PORT, AWG_DEFAULT_MTU, AWG_DEFAULT_SUBNET,
    AWG_DEFAULT_CLIENT_IP, AWG_DEFAULT_SERVER_IP,
    AWG_DEFAULT_SUBNET_V6, AWG_DEFAULT_CLIENT_IPv6, AWG_DEFAULT_SERVER_IPv6,
    AWG_DEFAULT_JC, AWG_DEFAULT_JMIN, AWG_DEFAULT_JMAX,
    AWG_DEFAULT_S1, AWG_DEFAULT_S2,
    AWG_DEFAULT_H1, AWG_DEFAULT_H2, AWG_DEFAULT_H3, AWG_DEFAULT_H4,
    AWG_FWMARK, AWG_ROUTE_TABLE,
    BALANCER_ROUND_ROBIN,
    INSTALL_MODE_A,
    WARP_MODE_FULL,
    ASN_ACTION_DIRECT,
    SCHEDULED_BACKUP_DEFAULT_DAYS, SCHEDULED_BACKUP_KEEP_LAST,
)


@dataclass
class XrayParams:
    """Параметры, специфичные для Xray/VLESS конфигурации."""
    uuid:            str = ""
    domain:          str = ""
    short_id:        str = ""
    public_key:      str = ""
    private_key:     str = ""
    email:           str = ""
    spiderx:         str = ""
    socket_path:     str = ""
    reality_dest:    str = ""
    domain_strategy: str = ""
    site_template:   str = ""
    private_key_mode: str = "auto"


@dataclass
class XhttpParams:
    """Параметры xHTTP-транспорта."""
    mode:                      str  = XHTTP_MODE_STREAMUP
    path:                      str  = ""
    perf_preset:               str  = "auto"
    mode_supported:            bool = False
    padding_bytes:             str  = "100-1000"
    no_sse_header:             bool = False
    sc_stream_up_server_secs:  str  = "20-80"
    sc_max_each_post_bytes:    str  = "1000000"
    sc_max_buffered_posts:     int  = 30
    host:                      str  = ""
    no_grpc_header:            bool = False
    sc_min_posts_interval_ms:  str  = "30"
    xmux_enabled:              bool = False
    xmux_max_concurrency:      str  = "16-32"
    xmux_max_connections:      int  = 0
    xmux_c_max_reuse_times:    str  = "0"
    xmux_h_max_request_times:  str  = "600-900"
    xmux_h_max_reusable_secs:  str  = "1800-3000"
    xmux_h_keep_alive_period:  int  = 0
    enable_session_resumption: bool = False
    tcp_no_delay:              bool = False


@dataclass
class NginxParams:
    """Параметры Nginx."""
    domain:       str = ""
    web_root:     str = ""
    site_template: str = ""


@dataclass
class AwgConfig:
    """Конфигурация AmneziaWG-туннеля."""
    enabled:       bool = False
    exit_host:     str  = ""
    exit_port:     int  = AWG_DEFAULT_PORT
    interface:     str  = "awg0"
    subnet:        str  = AWG_DEFAULT_SUBNET
    client_ip:     str  = AWG_DEFAULT_CLIENT_IP
    server_ip:     str  = AWG_DEFAULT_SERVER_IP
    subnet_v6:     str  = AWG_DEFAULT_SUBNET_V6
    client_ipv6:   str  = AWG_DEFAULT_CLIENT_IPv6
    server_ipv6:   str  = AWG_DEFAULT_SERVER_IPv6
    mtu:           int  = AWG_DEFAULT_MTU
    installed:     bool = False
    server_privkey: str = ""
    server_pubkey:  str = ""
    client_privkey: str = ""
    client_pubkey:  str = ""
    preshared_key:  str = ""
    jc:   int = AWG_DEFAULT_JC
    jmin: int = AWG_DEFAULT_JMIN
    jmax: int = AWG_DEFAULT_JMAX
    s1:   int = AWG_DEFAULT_S1
    s2:   int = AWG_DEFAULT_S2
    h1:   int = AWG_DEFAULT_H1
    h2:   int = AWG_DEFAULT_H2
    h3:   int = AWG_DEFAULT_H3
    h4:   int = AWG_DEFAULT_H4
    fwmark:      int = AWG_FWMARK
    route_table: int = AWG_ROUTE_TABLE
    nodes:             list = field(default_factory=list)
    active_node_index: int  = 0
    prefer_index:      int  = 0
    ssh_client_ip:     str  = ""


@dataclass
class WarpConfig:
    """Конфигурация Cloudflare WARP."""
    installed:      bool      = False
    connected:      bool      = False
    mode:           str       = WARP_MODE_FULL
    ssh_client_ip:  str       = ""
    custom_ips:     list[str] = field(default_factory=list)
    custom_domains: list[str] = field(default_factory=list)


@dataclass
class SplitTunnelConfig:
    """Конфигурация раздельного туннелирования."""
    enabled:        bool      = False
    extra_domains:  list[str] = field(default_factory=list)
    extra_ips:      list[str] = field(default_factory=list)


@dataclass
class ChainParams:
    """Параметры каскадного прокси (Режим B)."""
    exit_host:    str       = ""
    exit_port:    int       = 443
    exit_uuid:    str       = ""
    exit_pubkey:  str       = ""
    exit_shortid: str       = ""
    exit_sni:     str       = ""
    exit_fp:      str       = "chrome"
    nodes:        list[dict] = field(default_factory=list)
    balancer_strategy:  str = BALANCER_ROUND_ROBIN
    pinned_node_index:  int = -1


@dataclass
class InstallProgress:
    started:    bool = False
    ufw_done:   bool = False
    xray_done:  bool = False
    nginx_done: bool = False
    completed:  bool = False


@dataclass
class AsnRoute:
    """Один AS-маршрут: номер AS, действие, кэш префиксов."""
    asn:         int       = 0
    action:      str       = ASN_ACTION_DIRECT
    description: str       = ""
    ipv4_count:  int       = 0
    ipv6_count:  int       = 0
    last_updated: str      = ""


@dataclass
class AsnRoutingConfig:
    """Конфигурация модуля AS-маршрутизации."""
    routes:            list = field(default_factory=list)
    auto_update_enabled: bool = False
    host_asn:          int  = 0


@dataclass
class ScheduledBackupConfig:
    """Конфигурация планировщика автоматического backup."""
    enabled:        bool = False
    interval_days:  int  = SCHEDULED_BACKUP_DEFAULT_DAYS
    hour:           int  = 3
    minute:         int  = 0
    keep_last:      int  = SCHEDULED_BACKUP_KEEP_LAST


@dataclass
class InstallerState:
    """
    Единая модель состояния установщика.

    Заменяет ~50 глобальных переменных оригинального скрипта.
    Передаётся явно через аргументы функций.
    Сериализуется в STATE_FILE для персистентности между запусками.
    """
    install_mode:   str = INSTALL_MODE_A
    protocol_mode:  str = PROTOCOL_REALITY
    server_port:    int = DEFAULT_SERVER_PORT
    xtls_flow:      str = XTLS_FLOW_VISION

    xray:         XrayParams       = field(default_factory=XrayParams)
    xhttp:        XhttpParams      = field(default_factory=XhttpParams)
    nginx:        NginxParams      = field(default_factory=NginxParams)
    awg:          AwgConfig        = field(default_factory=AwgConfig)
    warp:         WarpConfig       = field(default_factory=WarpConfig)
    split_tunnel: SplitTunnelConfig = field(default_factory=SplitTunnelConfig)
    chain:        ChainParams      = field(default_factory=ChainParams)
    progress:     InstallProgress  = field(default_factory=InstallProgress)
    asn_routing:  AsnRoutingConfig = field(default_factory=AsnRoutingConfig)
    scheduled_backup: ScheduledBackupConfig = field(default_factory=ScheduledBackupConfig)

    total_ram_mb: int  = 1024
    total_cpu:    int  = 1
    is_ipv6:      bool = False
    ipv6_route_ok: bool = False
    pkg_mgr:      str  = ""

    rollback_available: bool = False
    backup_timestamp:   str  = ""

    dnscrypt_installed: bool = False
    use_dnscrypt:       bool = False

    def to_dict(self) -> dict:
        """Сериализует состояние в словарь для JSON-записи."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "InstallerState":
        """
        Восстанавливает состояние из словаря (например, прочитанного из STATE_FILE).
        Отказоустойчив: неизвестные ключи игнорируются, отсутствующие — заполняются
        значениями по умолчанию.
        """
        state = cls()

        def _safe_set(obj, d: dict) -> None:
            """Присваивает поля dataclass из словаря, игнорируя неизвестные ключи."""
            for f_name in obj.__dataclass_fields__:
                if f_name in d:
                    current = getattr(obj, f_name)
                    val = d[f_name]
                    if hasattr(current, '__dataclass_fields__'):
                        _safe_set(current, val if isinstance(val, dict) else {})
                    else:
                        setattr(obj, f_name, val)

        _safe_set(state, data)
        return state

    def save(self, path: Path) -> None:
        """Записывает состояние в JSON-файл."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        except Exception:
            pass

    @classmethod
    def load(cls, path: Path) -> "InstallerState":
        """
        Загружает состояние из JSON-файла.
        Если файл отсутствует или повреждён — возвращает пустой InstallerState.
        """
        try:
            if path.exists():
                data = json.loads(path.read_text())
                return cls.from_dict(data)
        except Exception:
            pass
        return cls()

