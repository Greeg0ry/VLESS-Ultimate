"""
config_builders/split_tunnel.py — Генерация правил раздельного туннелирования.

Split tunneling позволяет:
  - заблокированный в РФ трафик направлять через proxy
  - остальной трафик пускать напрямую (direct)

Используются geo-файлы runetfreedom:
  geosite.dat — домены (заблокированные в РФ сайты)
  geoip.dat   — IP-диапазоны (заблокированные в РФ сети)

Файлы скачиваются в /etc/xray/ и указываются в geoDataBasePath конфига.
"""

from __future__ import annotations

from typing import Optional

from installer.core.state import SplitTunnelConfig
from installer.core.constants import GEOSITE_URL, GEOIP_URL
from installer.core.paths import GEOSITE_DAT, GEOIP_DAT, XRAY_CONFIG_DIR


def build_split_tunnel_routing_rules(
    cfg: SplitTunnelConfig,
    proxy_tag: str = "direct",
    direct_tag: str = "direct",
    extra_domains: Optional[list[str]] = None,
    extra_ips: Optional[list[str]] = None,
) -> list[dict]:
    """
    Генерирует список правил маршрутизации Xray для split tunneling.

    Принцип работы:
      1. Правила для заблокированных ресурсов → proxy_tag (прокси)
      2. Правила для локальных/доверенных → direct_tag (напрямую)
      3. Catch-all → direct_tag (весь прочий трафик напрямую)

    В Режиме A (одиночный сервер) proxy_tag == direct_tag == "direct",
    так как трафик уже идёт через сервер.

    В Режиме B (каскад) proxy_tag указывает на outbound к зарубежному VPS.

    Args:
        cfg:           Конфиг split tunneling из InstallerState.
        proxy_tag:     Outbound-тег для проксируемого трафика.
        direct_tag:    Outbound-тег для прямого трафика.
        extra_domains: Дополнительные домены (сверх geo-файлов).
        extra_ips:     Дополнительные IP/CIDR.

    Returns:
        Список routing rules (dict) для вставки в config["routing"]["rules"].
    """
    if not cfg.enabled:
        return []

    rules: list[dict] = []

    if GEOSITE_DAT.exists():
        rules.append({
            "type":        "field",
            "domain":      ["geosite:category-ru-blocked", "geosite:antizapret"],
            "outboundTag": proxy_tag,
        })

    if GEOIP_DAT.exists():
        rules.append({
            "type":        "field",
            "ip":          ["geoip:ru-blocked"],
            "outboundTag": proxy_tag,
        })

    all_extra_domains = list(cfg.extra_domains) + (extra_domains or [])
    if all_extra_domains:
        rules.append({
            "type":        "field",
            "domain":      all_extra_domains,
            "outboundTag": proxy_tag,
        })

    all_extra_ips = list(cfg.extra_ips) + (extra_ips or [])
    if all_extra_ips:
        rules.append({
            "type":        "field",
            "ip":          all_extra_ips,
            "outboundTag": proxy_tag,
        })

    return rules


def download_geo_files(force: bool = False) -> bool:
    """
    Скачивает актуальные geo-файлы runetfreedom.

    Args:
        force: True — перезаписать даже если файлы уже есть.

    Returns:
        True если скачивание прошло успешно.
    """
    from installer.core.shell import run
    from installer.core.logging import info, success, warn

    info("Скачивание geo-файлов runetfreedom...")
    XRAY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    ok = True
    for url, path in [(GEOSITE_URL, GEOSITE_DAT), (GEOIP_URL, GEOIP_DAT)]:
        if path.exists() and not force:
            info(f"  {path.name}: уже существует (пропускаем)")
            continue
        r = run(
            ["curl", "-fsSL", "--connect-timeout", "15", "--retry", "2",
             url, "-o", str(path)],
            check=False, quiet=True,
        )
        if r.returncode == 0 and path.exists() and path.stat().st_size > 0:
            info(f"  {path.name}: скачан ({path.stat().st_size // 1024} КБ)")
        else:
            warn(f"  {path.name}: не удалось скачать")
            ok = False

    if ok:
        success("Geo-файлы готовы")
    return ok


def load_split_tunnel_custom() -> tuple[list[str], list[str]]:
    """
    Загружает пользовательские домены/IP из файла split_tunnel_custom.json.

    Returns:
        (domains, ips) — списки строк.
    """
    import json
    from installer.core.paths import SPLIT_TUNNEL_CUSTOM_FILE

    if not SPLIT_TUNNEL_CUSTOM_FILE.exists():
        return [], []
    try:
        data = json.loads(SPLIT_TUNNEL_CUSTOM_FILE.read_text())
        return data.get("domains", []), data.get("ips", [])
    except Exception:
        return [], []


def save_split_tunnel_custom(domains: list[str], ips: list[str]) -> None:
    """Сохраняет пользовательские домены/IP в файл."""
    import json
    from installer.core.paths import SPLIT_TUNNEL_CUSTOM_FILE

    SPLIT_TUNNEL_CUSTOM_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPLIT_TUNNEL_CUSTOM_FILE.write_text(
        json.dumps({"domains": domains, "ips": ips}, indent=2, ensure_ascii=False)
    )

