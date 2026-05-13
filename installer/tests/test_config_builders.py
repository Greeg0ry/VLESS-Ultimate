"""
tests/test_config_builders.py — Тесты для сборщиков конфигов Xray.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from installer.config_builders.xray_config import (
    build_log_block, build_dns_block, build_sockopt,
    build_stats_blocks, apply_stats_to_config,
    build_reality_config,
)
from installer.core.state import InstallerState, XrayParams
from installer.core.constants import XRAY_STATS_API_PORT


def test_log_block():
    log = build_log_block()
    assert log["loglevel"] == "info"
    assert "access" in log
    assert "error" in log


def test_dns_block_ipv4():
    dns = build_dns_block(is_ipv6=False, query_strategy="UseIPv4")
    assert dns["queryStrategy"] == "UseIPv4"
    servers = dns["servers"]
    # IPv4-режим: только IPv4-серверы
    for s in servers:
        addr = s["address"]
        assert ":" not in addr, f"IPv6-адрес в IPv4-режиме: {addr}"


def test_dns_block_ipv6():
    dns = build_dns_block(is_ipv6=True, query_strategy="UseIPv6v4")
    assert dns["queryStrategy"] == "UseIPv6v4"
    servers = dns["servers"]
    # IPv6-режим: должны быть IPv6-адреса
    has_ipv6 = any(":" in s["address"] for s in servers)
    assert has_ipv6, "В IPv6-режиме должны быть IPv6 DNS-серверы"


def test_dns_block_dnscrypt():
    dns = build_dns_block(
        is_ipv6=False, query_strategy="UseIPv4",
        use_dnscrypt=True, dnscrypt_host="127.0.0.1", dnscrypt_port=5300,
    )
    first_server = dns["servers"][0]
    assert first_server["address"] == "127.0.0.1"
    assert first_server["port"] == 5300


def test_sockopt_empty():
    opt = build_sockopt()
    assert opt == {}


def test_sockopt_nodelay():
    opt = build_sockopt(tcp_no_delay=True)
    assert opt["tcpNoDelay"] is True


def test_stats_blocks():
    blocks = build_stats_blocks()
    assert "stats" in blocks
    assert "api" in blocks
    assert "policy" in blocks
    assert "_stats_inbound" in blocks
    assert blocks["_stats_inbound"]["port"] == XRAY_STATS_API_PORT


def test_apply_stats_idempotent():
    config = {"inbounds": [], "outbounds": [], "routing": {"rules": []}}
    apply_stats_to_config(config)
    apply_stats_to_config(config)  # Повторный вызов не должен дублировать блоки

    inbounds_with_tag = [ib for ib in config["inbounds"] if ib.get("tag") == "xray-stats-api"]
    assert len(inbounds_with_tag) == 1, "Дублирование stats inbound"

    outbounds_with_tag = [ob for ob in config["outbounds"] if ob.get("tag") == "xray-stats-api"]
    assert len(outbounds_with_tag) == 1, "Дублирование stats outbound"

    api_rules = [r for r in config["routing"]["rules"]
                 if r.get("inboundTag") == ["xray-stats-api"]]
    assert len(api_rules) == 1, "Дублирование stats routing rule"


def test_reality_config_structure():
    state = InstallerState()
    state.xray = XrayParams(
        uuid="550e8400-e29b-41d4-a716-446655440000",
        domain="example.com",
        short_id="abcdef12",
        public_key="test-pubkey",
        private_key="test-privkey",
        spiderx="/test",
        socket_path="/dev/shm/xray.sock",
    )
    state.server_port = 443
    state.xtls_flow = "xtls-rprx-vision"

    config = build_reality_config(state, "/etc/xray")

    assert "log" in config
    assert "dns" in config
    assert "inbounds" in config
    assert "outbounds" in config
    assert "routing" in config
    assert "stats" in config  # Stats API применён

    inbound = config["inbounds"][0]
    assert inbound["port"] == 443
    assert inbound["protocol"] == "vless"

    # Проверяем REALITY settings
    real = inbound["streamSettings"]["realitySettings"]
    assert real["privateKey"] == "test-privkey"
    assert real["publicKey"] == "test-pubkey"
    assert "abcdef12" in real["shortIds"]

    # Routing: catch-all должен быть последним
    rules = config["routing"]["rules"]
    last = rules[-1]
    assert last.get("outboundTag") == "direct"


if __name__ == "__main__":
    import traceback
    tests = [
        test_log_block, test_dns_block_ipv4, test_dns_block_ipv6,
        test_dns_block_dnscrypt, test_sockopt_empty, test_sockopt_nodelay,
        test_stats_blocks, test_apply_stats_idempotent,
        test_reality_config_structure,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗  {t.__name__}: {traceback.format_exc()}")
            failed += 1
    print(f"\n  Результат: {passed} прошло / {failed} упало")
    sys.exit(0 if failed == 0 else 1)

