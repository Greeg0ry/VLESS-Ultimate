"""
services/asn_routing.py — Модуль AS-маршрутизации.

Позволяет управлять трафиком на уровне автономных систем (ASN):
  - загружает актуальные IPv4/IPv6 префиксы из RIPE NCC Stat API
  - применяет правила в /etc/xray/config.json (direct / proxy / block)
  - кэширует префиксы локально (SQLite + txt-файлы)
  - устанавливает systemd timer для ежесуточного автообновления
  - поддерживает пакетный ввод нескольких ASN/IP/доменов

Расположение в меню:
  Главное меню → 5. Безопасность → 2. 🛡️ GeoIP Block → [6] AS-маршрутизация

Правила:
  - Никаких побочных эффектов при импорте модуля.
  - Все изменения config.json проходят через xray_safe_apply_config().
  - При ошибке валидации конфига — автоматический откат.
"""

from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from installer.core.constants import (
    RIPE_STAT_PREFIXES_URL,
    IPINFO_ASN_URL,
    ASN_XRAY_CIDR_BATCH,
    ASN_RESERVED_0, ASN_RESERVED_TRANS, ASN_MAX,
    ASN_ACTION_DIRECT, ASN_ACTION_PROXY, ASN_ACTION_BLOCK, ASN_ACTIONS,
    ASN_TIMER_NAME, ASN_SERVICE_NAME,
    ASN_UPDATE_INTERVAL_DAYS,
    CHANGE_LOG_LABEL,
)
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import (
    XRAY_CONFIG_FILE, XRAY_CONFIG_DIR,
    ASN_LIST_FILE, ASN_PREFIX_CACHE_DB, asn_prefix_file,
)
from installer.core.shell import run, run_capture


def parse_asn_input(raw: str) -> Optional[int]:
    """
    Нормализует ввод ASN из любого формата (AS8359, 8359, as12345).
    Возвращает int ASN или None если формат некорректный.
    """
    raw = raw.strip().upper().lstrip("AS")
    if not raw.isdigit():
        return None
    asn = int(raw)
    if asn < 1 or asn > ASN_MAX:
        return None
    return asn


def validate_asn(asn: int) -> tuple[bool, str]:
    """
    Проверяет, что ASN допустим для использования.

    Returns:
        (ok, warning_message). warning_message пустой если всё хорошо.
    """
    if asn == ASN_RESERVED_0:
        return False, "AS0 зарезервирован и не может использоваться"
    if asn == ASN_RESERVED_TRANS:
        return True, f"AS{asn} (AS_TRANS) — служебный, используется для BGP-переходов"
    if asn > 4200000000:
        return True, f"AS{asn} — приватный диапазон (RFC 6996)"
    return True, ""


def resolve_to_ip(host: str) -> Optional[str]:
    """Возвращает IP-адрес для домена или сам IP, если уже IP."""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    r = run_capture(["getent", "hosts", host])
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.split()[0]
    return None


def lookup_asn_by_ip(ip: str) -> Optional[int]:
    """
    Определяет ASN по IP через ipinfo.io API.
    Возвращает int ASN или None если не удалось определить.
    """
    try:
        url = IPINFO_ASN_URL.format(ip=ip)
        r = run_capture(["curl", "-fsSL", "--connect-timeout", "10", url])
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        org = data.get("org", "")
        if org.startswith("AS"):
            return parse_asn_input(org.split()[0])
    except Exception as e:
        log_to_file("WARN", f"lookup_asn_by_ip({ip}) error: {e}")
    return None


def get_server_asn() -> Optional[int]:
    """
    Определяет ASN текущего VPS по его публичному IP.
    Используется для предложения добавить хостера в direct.
    """
    r = run_capture(["curl", "-fsSL", "--connect-timeout", "5",
                     "https://ipinfo.io/ip"])
    if r.returncode != 0:
        return None
    ip = r.stdout.strip()
    return lookup_asn_by_ip(ip)


def fetch_prefixes_from_ripe(asn: int) -> tuple[list[str], list[str]]:
    """
    Загружает IPv4 и IPv6 префиксы для указанного AS из RIPE NCC Stat API.

    Returns:
        (ipv4_prefixes, ipv6_prefixes) — списки валидных CIDR-строк.

    Raises:
        RuntimeError: если API недоступен и локальный кэш тоже пуст.
    """
    url = f"{RIPE_STAT_PREFIXES_URL}?resource=AS{asn}"
    info(f"Загрузка префиксов AS{asn} из RIPE NCC...")

    r = run_capture(["curl", "-fsSL", "--connect-timeout", "20",
                     "--retry", "2", url])
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"RIPE API недоступен для AS{asn}")

    try:
        data = json.loads(r.stdout)
        raw_prefixes: list[str] = [
            p["prefix"] for p in data.get("data", {}).get("prefixes", [])
            if "prefix" in p
        ]
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Ошибка парсинга ответа RIPE: {e}")

    ipv4, ipv6 = [], []
    for cidr in raw_prefixes:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            if net.version == 4:
                ipv4.append(str(net))
            else:
                ipv6.append(str(net))
        except ValueError:
            pass

    info(f"AS{asn}: получено {len(ipv4)} IPv4 и {len(ipv6)} IPv6 префиксов")
    return ipv4, ipv6


def _db_connect() -> sqlite3.Connection:
    """Открывает SQLite-кэш, создаёт таблицу при необходимости."""
    ASN_PREFIX_CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ASN_PREFIX_CACHE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS asn_cache (
            key       TEXT PRIMARY KEY,
            data      TEXT NOT NULL,
            updated   REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _cache_key(asn: int, family: int) -> str:
    return f"AS{asn}_v{family}"


def save_prefixes_to_cache(asn: int, ipv4: list[str], ipv6: list[str]) -> None:
    """Сохраняет префиксы в SQLite-кэш и txt-файлы."""
    now = time.time()

    with _db_connect() as conn:
        for family, prefixes in ((4, ipv4), (6, ipv6)):
            conn.execute(
                "INSERT OR REPLACE INTO asn_cache(key, data, updated) VALUES (?,?,?)",
                (_cache_key(asn, family), json.dumps(prefixes), now),
            )
        conn.commit()

    txt_path = asn_prefix_file(asn)
    all_prefixes = ipv4 + ipv6
    txt_path.write_text("\n".join(all_prefixes))
    log_to_file("ASN_CACHE", f"AS{asn}: {len(all_prefixes)} префиксов сохранено в {txt_path}")


def load_prefixes_from_cache(asn: int) -> tuple[list[str], list[str]]:
    """
    Загружает префиксы из SQLite-кэша.
    Возвращает ([], []) если кэш пуст или устарел (> 30 дней).
    """
    max_age = 30 * 86400
    try:
        with _db_connect() as conn:
            ipv4, ipv6 = [], []
            for family in (4, 6):
                row = conn.execute(
                    "SELECT data, updated FROM asn_cache WHERE key=?",
                    (_cache_key(asn, family),),
                ).fetchone()
                if row:
                    age = time.time() - row[1]
                    if age < max_age:
                        (ipv4 if family == 4 else ipv6).extend(json.loads(row[0]))
            return ipv4, ipv6
    except Exception:
        return [], []


def get_prefixes(asn: int, force_refresh: bool = False) -> tuple[list[str], list[str]]:
    """
    Получает префиксы для AS: из кэша или RIPE API.
    При force_refresh=True — всегда обращается к RIPE.
    """
    if not force_refresh:
        ipv4, ipv6 = load_prefixes_from_cache(asn)
        if ipv4 or ipv6:
            info(f"AS{asn}: используется кэш ({len(ipv4)} IPv4, {len(ipv6)} IPv6)")
            return ipv4, ipv6

    ipv4, ipv6 = fetch_prefixes_from_ripe(asn)
    save_prefixes_to_cache(asn, ipv4, ipv6)
    return ipv4, ipv6


def load_asn_list() -> list[dict]:
    """Загружает список активных AS-маршрутов из JSON-файла."""
    if not ASN_LIST_FILE.exists():
        return []
    try:
        return json.loads(ASN_LIST_FILE.read_text())
    except Exception:
        return []


def save_asn_list(routes: list[dict]) -> None:
    """Сохраняет список AS-маршрутов в JSON-файл."""
    XRAY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ASN_LIST_FILE.write_text(json.dumps(routes, indent=2, ensure_ascii=False))


def find_route(routes: list[dict], asn: int) -> Optional[dict]:
    """Находит маршрут по ASN."""
    for r in routes:
        if r.get("asn") == asn:
            return r
    return None


def _make_cidr_rules(prefixes: list[str], action: str, proxy_tag: str) -> list[dict]:
    """
    Разбивает список CIDR на батчи и создаёт правила Xray routing.
    action: direct | proxy | block
    """
    outbound_map = {
        ASN_ACTION_DIRECT: "direct",
        ASN_ACTION_BLOCK:  "blackhole",
        ASN_ACTION_PROXY:  proxy_tag,
    }
    tag = outbound_map.get(action, "direct")
    rules = []
    for i in range(0, len(prefixes), ASN_XRAY_CIDR_BATCH):
        batch = prefixes[i:i + ASN_XRAY_CIDR_BATCH]
        rules.append({
            "type":        "field",
            "ip":          batch,
            "outboundTag": tag,
        })
    return rules


def _get_proxy_outbound_tag(config: dict) -> str:
    """Определяет тег основного proxy-аутбаунда из конфига Xray."""
    for ob in config.get("outbounds", []):
        prot = ob.get("protocol", "")
        if prot in ("vless", "vmess", "trojan", "shadowsocks"):
            return ob.get("tag", "proxy")
    return "proxy"


def _remove_asn_rules(rules: list[dict], asn: int) -> list[dict]:
    """
    Удаляет из списка правил все правила, помеченные тегом _asn_{asn}.
    Тег добавляется при патчинге для идемпотентности.
    """
    marker = f"_asn_{asn}_"
    return [r for r in rules if marker not in str(r.get("_comment", ""))]


def patch_xray_config_with_asn(asn: int, action: str) -> bool:
    """
    Применяет AS-правила в config.json Xray.

    Алгоритм:
    1. Загружает или обновляет префиксы из RIPE/кэша.
    2. Удаляет старые правила для этого ASN (идемпотентность).
    3. Вставляет новые батч-правила в начало routing.rules (после split-tunnel, перед geoip).
    4. Вызывает xray_safe_apply_config() для атомарного применения.

    Returns:
        True если применено успешно.
    """
    from installer.services.xray import xray_safe_apply_config

    cfg_path = _find_active_config()
    if not cfg_path:
        warn("Не найден активный config.json Xray")
        return False

    try:
        config = json.loads(cfg_path.read_text())
    except Exception as e:
        warn(f"Ошибка чтения config.json: {e}")
        return False

    ipv4, ipv6 = get_prefixes(asn)
    if not ipv4 and not ipv6:
        warn(f"AS{asn}: нет префиксов для применения")
        return False

    proxy_tag = _get_proxy_outbound_tag(config)
    all_prefixes = ipv4 + ipv6
    new_rules = _make_cidr_rules(all_prefixes, action, proxy_tag)

    for r in new_rules:
        r["_comment"] = f"_asn_{asn}_auto"

    existing_rules = config.setdefault("routing", {}).setdefault("rules", [])
    cleaned = _remove_asn_rules(existing_rules, asn)

    config["routing"]["rules"] = new_rules + cleaned

    return xray_safe_apply_config(config, cfg_path, reason=f"AS{asn} → {action}")


def remove_asn_route(asn: int) -> bool:
    """
    Удаляет все правила для AS из config.json и из as_direct_list.json.
    """
    from installer.services.xray import xray_safe_apply_config

    cfg_path = _find_active_config()
    if not cfg_path:
        return False
    try:
        config = json.loads(cfg_path.read_text())
    except Exception:
        return False

    existing = config.get("routing", {}).get("rules", [])
    cleaned = _remove_asn_rules(existing, asn)
    if len(cleaned) == len(existing):
        info(f"AS{asn}: правила не найдены в config.json")
    else:
        config["routing"]["rules"] = cleaned
        xray_safe_apply_config(config, cfg_path, reason=f"Remove AS{asn}")

    routes = [r for r in load_asn_list() if r.get("asn") != asn]
    save_asn_list(routes)
    log_to_file(CHANGE_LOG_LABEL, f"AS{asn}: маршрут удалён")
    return True


def add_or_update_asn_route(asn: int, action: str, description: str = "") -> bool:
    """
    Добавляет или обновляет AS-маршрут: обновляет конфиг Xray + список.

    Args:
        asn:         Номер AS.
        action:      "direct" | "proxy" | "block".
        description: Произвольное описание (имя провайдера и т.д.).

    Returns:
        True если успешно.
    """
    if action not in ASN_ACTIONS:
        warn(f"Неизвестное действие: {action}. Допустимые: {ASN_ACTIONS}")
        return False

    ok, warning = validate_asn(asn)
    if not ok:
        warn(warning)
        return False
    if warning:
        info(f"Предупреждение: {warning}")

    success_apply = patch_xray_config_with_asn(asn, action)
    if not success_apply:
        return False

    routes = load_asn_list()
    ipv4, ipv6 = load_prefixes_from_cache(asn)
    new_entry = {
        "asn":         asn,
        "action":      action,
        "description": description,
        "ipv4_count":  len(ipv4),
        "ipv6_count":  len(ipv6),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    routes = [r for r in routes if r.get("asn") != asn]
    routes.append(new_entry)
    save_asn_list(routes)

    log_to_file(CHANGE_LOG_LABEL,
                f"AS{asn} ({description}) → {action}, "
                f"IPv4: {len(ipv4)}, IPv6: {len(ipv6)}")
    success(f"AS{asn}: маршрут '{action}' применён ✓")
    return True


def batch_add_asn_routes(inputs: list[str], action: str) -> dict[str, bool]:
    """
    Пакетная обработка нескольких ASN / IP / доменов.

    Args:
        inputs: Список строк (ASN, IP или домен).
        action: Действие для всех ("direct" / "proxy" / "block").

    Returns:
        Словарь {ввод → True/False}.
    """
    results: dict[str, bool] = {}
    for raw in inputs:
        raw = raw.strip()
        if not raw:
            continue
        asn = parse_asn_input(raw)
        if asn is None:
            ip = resolve_to_ip(raw)
            if ip:
                asn = lookup_asn_by_ip(ip)
            if asn is None:
                warn(f"Не удалось определить ASN для '{raw}'")
                results[raw] = False
                continue

        results[raw] = add_or_update_asn_route(asn, action, description=raw)
    return results


def install_asn_auto_update_timer() -> None:
    """
    Устанавливает systemd timer для ежесуточного обновления AS-префиксов.
    """
    service_content = textwrap.dedent("""
        [Unit]
        Description=VLESS Xray AS-prefix auto-update
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=oneshot
        ExecStart=/usr/bin/python3 -m installer.main --update-asn-prefixes
        StandardOutput=journal
        StandardError=journal
    """).strip()

    timer_content = textwrap.dedent(f"""
        [Unit]
        Description=Daily update of Xray AS-prefix lists
        Requires={ASN_SERVICE_NAME}

        [Timer]
        OnCalendar=*-*-* 04:00:00
        RandomizedDelaySec=3600
        Persistent=true

        [Install]
        WantedBy=timers.target
    """).strip()

    svc_path = Path(f"/etc/systemd/system/{ASN_SERVICE_NAME}")
    tmr_path = Path(f"/etc/systemd/system/{ASN_TIMER_NAME}")

    svc_path.write_text(service_content + "\n")
    tmr_path.write_text(timer_content + "\n")

    run(["systemctl", "daemon-reload"], check=False, quiet=True)
    run(["systemctl", "enable", "--now", ASN_TIMER_NAME], check=False, quiet=True)
    success(f"Таймер автообновления AS-префиксов установлен ({ASN_TIMER_NAME})")


def update_all_asn_prefixes() -> None:
    """
    Обновляет префиксы всех активных AS из RIPE и перезаписывает правила в конфиге.
    Вызывается автоматически из systemd timer или вручную из меню.
    """
    routes = load_asn_list()
    if not routes:
        info("Нет активных AS-маршрутов для обновления")
        return

    info(f"Обновление префиксов для {len(routes)} AS...")
    for entry in routes:
        asn = entry.get("asn")
        action = entry.get("action", ASN_ACTION_DIRECT)
        description = entry.get("description", "")
        if asn:
            try:
                ipv4, ipv6 = fetch_prefixes_from_ripe(asn)
                save_prefixes_to_cache(asn, ipv4, ipv6)
                patch_xray_config_with_asn(asn, action)
                info(f"AS{asn}: обновлено ({len(ipv4)} IPv4, {len(ipv6)} IPv6)")
            except Exception as e:
                warn(f"AS{asn}: ошибка обновления — {e}, используется кэш")

    success("Обновление AS-префиксов завершено")


def _find_active_config() -> Optional[Path]:
    """Ищет активный config.json (основной или альтернативный путь)."""
    from installer.core.paths import XRAY_CONFIG_FILE, XRAY_ALT_CONFIG
    if XRAY_CONFIG_FILE.exists():
        return XRAY_CONFIG_FILE
    if XRAY_ALT_CONFIG.exists():
        return XRAY_ALT_CONFIG
    return None


def show_cache_table() -> None:
    """
    Выводит таблицу состояния SQLite-кэша ASN.
    Записи старше 30 дней выделяются предупреждением.
    """
    from installer.core.logging import info
    try:
        with _db_connect() as conn:
            rows = conn.execute(
                "SELECT key, data, updated FROM asn_cache ORDER BY updated DESC"
            ).fetchall()
        if not rows:
            info("Кэш ASN пуст")
            return
        print(f"\n  {'ASN':<15} {'Префиксов':<12} {'Обновлён':<22} {'Возраст'}")
        print("  " + "─" * 65)
        now = time.time()
        for key, data, updated in rows:
            count = len(json.loads(data))
            age_days = (now - updated) / 86400
            upd_str = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M")
            age_str = f"{age_days:.0f}д"
            flag = " ⚠️" if age_days > 30 else ""
            print(f"  {key:<15} {count:<12} {upd_str:<22} {age_str}{flag}")
        print()
    except Exception as e:
        warn(f"Ошибка чтения кэша: {e}")


def clear_asn_cache(target: Optional[str] = None) -> None:
    """
    Очищает SQLite-кэш ASN.

    Args:
        target: None — полный сброс; "AS12345" — конкретный ASN; "ru" — кэш подсетей РФ.
    """
    try:
        with _db_connect() as conn:
            if target is None:
                conn.execute("DELETE FROM asn_cache")
                info("Кэш ASN полностью очищен")
            elif target.upper().startswith("AS") or target.isdigit():
                asn = parse_asn_input(target)
                if asn:
                    conn.execute("DELETE FROM asn_cache WHERE key LIKE ?", (f"AS{asn}_%",))
                    info(f"Кэш AS{asn} удалён")
            elif target.lower() == "ru":
                conn.execute("DELETE FROM asn_cache WHERE key LIKE 'AS%_ru_%'")
                info("Кэш подсетей РФ очищен")
            conn.commit()
    except Exception as e:
        warn(f"Ошибка очистки кэша: {e}")

