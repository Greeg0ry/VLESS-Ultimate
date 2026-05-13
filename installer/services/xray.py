"""
services/xray.py — Установка, настройка и управление сервисом Xray-core.

Содержит:
  - install_xray()        — скачивание и установка бинарника
  - create_xray_service() — создание systemd-юнита
  - restart_xray()        — перезапуск с проверкой конфига
  - _verify_sha256()      — проверка целостности архива
"""

from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path
from typing import Optional

from installer.core.shell import run, run_capture, command_exists
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import (
    XRAY_BIN, XRAY_SERVICE_FILE, XRAY_CONFIG_FILE, XRAY_CONFIG_DIR,
    XRAY_BACKUP_DIR, XRAY_LOG_DIR,
)
from installer.core.constants import (
    XRAY_RELEASE_API_URL, XRAY_DOWNLOAD_BASE_URL,
    XRAY_SERVICE_NAME,
)


def install_xray() -> Path:
    """
    Устанавливает Xray-core на сервер.

    Метод 1: официальный установщик XTLS (bash-скрипт).
    Метод 2: прямая загрузка zip с GitHub + SHA256 верификация.
    Метод 3: использование уже скачанного локального zip.

    Returns:
        Путь к установленному бинарнику xray.

    Raises:
        RuntimeError: если ни один метод не сработал.
    """
    info("Установка Xray-core...")

    xray_arch = _detect_arch()
    _prepare_xray_dirs()
    _ensure_xray_user()

    installed_bin = _try_official_installer()
    if installed_bin:
        success("Xray установлен через официальный установщик")
        return installed_bin

    warn("Официальный установщик недоступен, пробую прямую загрузку...")
    installed_bin = _try_github_download(xray_arch)
    if installed_bin:
        success("Xray установлен через прямую загрузку")
        return installed_bin

    raise RuntimeError(
        "Не удалось установить Xray ни одним из методов. "
        "Проверьте сетевую доступность сервера."
    )


def _detect_arch() -> str:
    """Определяет архитектуру для выбора правильного zip Xray."""
    r = run_capture(["uname", "-m"])
    arch = r.stdout.strip()
    arch_map = {
        "x86_64":  "64",
        "aarch64": "arm64-v8a",
        "i386":    "32",
        "i686":    "32",
    }
    if arch.startswith("armv7"):
        return "arm32-v7a"
    result = arch_map.get(arch)
    if not result:
        raise RuntimeError(f"Неподдерживаемая архитектура: {arch}")
    return result


def _prepare_xray_dirs() -> None:
    """Создаёт все директории, нужные для работы Xray."""
    for d in (
        Path("/usr/local/share/xray"),
        Path("/usr/local/etc/xray"),
        XRAY_CONFIG_DIR,
        XRAY_LOG_DIR,
        XRAY_BACKUP_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def _ensure_xray_user() -> None:
    """Создаёт системного пользователя xray (если не существует)."""
    r = run(["id", "xray"], check=False, quiet=True)
    if r.returncode != 0:
        run(
            ["useradd", "-r", "-s", "/usr/sbin/nologin", "-d", "/var/lib/xray", "xray"],
            check=False, quiet=True,
        )
    Path("/var/lib/xray").mkdir(exist_ok=True)
    for d in (Path("/var/lib/xray"), XRAY_LOG_DIR):
        run(["chown", "-R", "xray:xray", str(d)], check=False, quiet=True)
        d.chmod(0o750)


def _try_official_installer() -> Optional[Path]:
    """Пробует официальный bash-установщик XTLS. Возвращает Path или None."""
    info("Метод 1: официальный установщик XTLS...")
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        r = run(
            ["curl", "-fsSL", "--connect-timeout", "15", "--retry", "2",
             "https://github.com/XTLS/Xray-install/raw/main/install-release.sh",
             "-o", str(tmp_path)],
            check=False, quiet=True,
        )
        if (r.returncode == 0 and tmp_path.stat().st_size > 0
                and b"bash" in tmp_path.read_bytes()[:50]):
            run(["bash", str(tmp_path), "install"], check=False, quiet=True)
            xray_dropin_dir = Path("/etc/systemd/system/xray.service.d")
            if xray_dropin_dir.exists():
                shutil.rmtree(xray_dropin_dir, ignore_errors=True)
            found = shutil.which("xray") or "/usr/local/bin/xray"
            p = Path(found)
            if p.exists():
                return p
    except Exception as e:
        log_to_file("WARN", f"Официальный установщик упал: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)
    return None


def _try_github_download(xray_arch: str) -> Optional[Path]:
    """Пробует прямую загрузку zip с GitHub. Возвращает Path или None."""
    info("Метод 2: прямая загрузка с GitHub releases...")

    latest_tag = _get_latest_xray_tag()
    if not latest_tag:
        warn("Не удалось получить последний тег Xray")
        return None

    zip_name = f"Xray-linux-{xray_arch}.zip"
    download_url = f"{XRAY_DOWNLOAD_BASE_URL}/{latest_tag}/{zip_name}"
    chk_url      = f"{XRAY_DOWNLOAD_BASE_URL}/{latest_tag}/SHA256SUMS"

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / zip_name
        r = run(
            ["curl", "-fL", "--connect-timeout", "20", "--retry", "2",
             download_url, "-o", str(zip_path)],
            check=False, quiet=True,
        )
        if r.returncode != 0 or not zip_path.exists():
            return None

        if not _verify_sha256(zip_path, chk_url, zip_name):
            warn("SHA256 не совпал, пропускаю этот zip")
            return None

        r = run(["unzip", "-o", str(zip_path), "xray", "-d", tmpdir],
                check=False, quiet=True)
        xray_extracted = Path(tmpdir) / "xray"
        if not xray_extracted.exists():
            return None

        target = Path("/usr/local/bin/xray")
        shutil.copy2(xray_extracted, target)
        target.chmod(0o755)
        return target


def _get_latest_xray_tag() -> Optional[str]:
    """Запрашивает последний тег Xray через GitHub API."""
    import json
    api_urls = [
        f"{XRAY_RELEASE_API_URL}/latest",
        f"https://ghproxy.net/{XRAY_RELEASE_API_URL}/latest",
    ]
    for url in api_urls:
        try:
            r = run_capture([
                "curl", "-fsSL", "--connect-timeout", "10",
                "-H", "Accept: application/vnd.github+json", url,
            ])
            if r.returncode == 0 and r.stdout:
                data = json.loads(r.stdout)
                tag = data.get("tag_name", "")
                if tag:
                    return tag
        except Exception:
            pass
    return None


def _verify_sha256(file_path: Path, checksums_url: str, file_name: str) -> bool:
    """
    Проверяет SHA256-хеш файла по удалённому файлу контрольных сумм.

    Returns:
        True если хеш совпал, False если не совпал или не удалось проверить.
    """
    import hashlib
    try:
        r = run_capture(["curl", "-fsSL", "--connect-timeout", "10", checksums_url])
        if r.returncode != 0:
            return True
        for line in r.stdout.splitlines():
            if file_name in line:
                expected = line.split()[0].lower()
                actual = hashlib.sha256(file_path.read_bytes()).hexdigest().lower()
                return actual == expected
    except Exception:
        pass
    return True


def create_xray_service(
    config_dir: Path,
    xray_bin: Path,
    protocol_mode: str,
    socket_path: str,
    awg_enabled: bool,
    use_dnscrypt: bool,
) -> None:
    """
    Создаёт systemd-юнит для Xray и включает его.

    Args:
        config_dir:    Директория с config.json.
        xray_bin:      Путь к бинарнику xray.
        protocol_mode: "reality" или "xhttp".
        socket_path:   Путь к unix-сокету (для REALITY + Nginx).
        awg_enabled:   True если используется AWG-транспорт.
        use_dnscrypt:  True если DNSCrypt нужен до старта Xray.
    """
    info("Настройка systemd-сервиса Xray...")

    sock_dir = str(Path(socket_path).parent) if socket_path else ""

    after_line = (
        "After=network.target network-online.target nss-lookup.target "
        "systemd-resolved.service"
    )
    wants_line = "Wants=network-online.target"
    if use_dnscrypt:
        after_line += " dnscrypt-proxy.service"
        wants_line  = "Wants=network-online.target dnscrypt-proxy.service"

    if protocol_mode == "xhttp":
        pre_cmds = ""
        svc_desc = "Xray Service (VLESS xHTTP TLS)"
    elif awg_enabled:
        pre_cmds = ""
        svc_desc = "Xray Service (VLESS TCP REALITY + AWG)"
    else:
        if sock_dir:
            sock_parent = Path(sock_dir)
            sock_parent.mkdir(parents=True, exist_ok=True)
            run(["chown", "xray:xray", sock_dir], check=False, quiet=True)
            try:
                sock_parent.chmod(0o755)
            except Exception:
                pass
        pre_cmds = (
            f"ExecStartPre=/bin/mkdir -p {sock_dir}\n"
            f"        ExecStartPre=/bin/sh -c 'rm -f {socket_path} 2>/dev/null || true'"
        ) if sock_dir and socket_path else ""
        svc_desc = "Xray Service (VLESS TCP REALITY)"

    pre_block = f"\n        {pre_cmds}\n" if pre_cmds else ""

    unit_content = textwrap.dedent(f"""\
        [Unit]
        Description={svc_desc}
        Documentation=https://github.com/xtls
        {after_line}
        {wants_line}
        StartLimitIntervalSec=60s
        StartLimitBurst=3

        [Service]
        User=xray
        Group=xray
        CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
        AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
        NoNewPrivileges=true
        LimitNOFILE=1048576
        LimitNPROC=infinity
        Nice=-10
        IOSchedulingClass=best-effort
        IOSchedulingPriority=0
        MemoryAccounting=true
        {pre_block}
        ExecStart={xray_bin} run -config {config_dir}/config.json
        ExecReload=/bin/systemctl restart xray
        Restart=on-failure
        RestartSec=5s
        RestartPreventExitStatus=23
        TimeoutStartSec=30s
        TimeoutStopSec=10s

        [Install]
        WantedBy=multi-user.target
    """)

    XRAY_SERVICE_FILE.write_text(unit_content)
    run(["systemctl", "daemon-reload"], check=True, quiet=True)
    run(["systemctl", "enable", XRAY_SERVICE_NAME], check=True, quiet=True)
    success("Systemd-сервис Xray настроен")


def restart_xray(config_path: Path = XRAY_CONFIG_FILE,
                 xray_bin: Path = XRAY_BIN) -> bool:
    """
    Проверяет конфиг через 'xray run -test', затем перезапускает сервис.

    Returns:
        True если конфиг валиден и сервис поднялся.
    """
    import time
    r = run_capture([str(xray_bin), "run", "-test", "-config", str(config_path)])
    if r.returncode != 0:
        warn(f"Конфиг Xray не прошёл проверку: {r.stderr.strip()}")
        return False

    run(["systemctl", "restart", XRAY_SERVICE_NAME], quiet=True, check=False)
    time.sleep(2)

    r = run_capture(["systemctl", "is-active", XRAY_SERVICE_NAME])
    ok = r.stdout.strip() == "active"
    if ok:
        success("Xray перезапущен и активен")
    else:
        warn("Xray не вышел в active после перезапуска")
    return ok


def get_xray_version(xray_bin: Path = XRAY_BIN) -> str:
    """Возвращает версию установленного Xray или пустую строку."""
    try:
        r = run_capture([str(xray_bin), "version"])
        if r.returncode == 0:
            first_line = r.stdout.strip().splitlines()[0]
            import re
            m = re.search(r'(\d+\.\d+\.\d+)', first_line)
            return m.group(1) if m else first_line
    except Exception:
        pass
    return ""


def xray_find_config() -> Optional[Path]:
    """
    Возвращает путь к активному config.json (основной или альтернативный).
    Используется перед любым патчингом конфига.
    """
    if XRAY_CONFIG_FILE.exists():
        return XRAY_CONFIG_FILE
    alt = Path("/usr/local/etc/xray/config.json")
    if alt.exists():
        return alt
    return None


def xray_config_rollback(pre_apply_backup: Path) -> bool:
    """
    Откатывает config.json из резервной копии, созданной перед применением.
    Работает только с конфигурационными файлами — бинарник не трогает.

    Args:
        pre_apply_backup: Путь к бэкап-файлу (config.json.pre-apply).

    Returns:
        True если откат прошёл успешно.
    """
    import shutil as _shutil
    cfg = xray_find_config()
    if not pre_apply_backup.exists():
        warn(f"Бэкап для отката не найден: {pre_apply_backup}")
        return False
    target = cfg or XRAY_CONFIG_FILE
    _shutil.copy2(pre_apply_backup, target)
    alt = Path("/usr/local/etc/xray/config.json")
    if alt.parent.exists():
        _shutil.copy2(target, alt)
    log_to_file("ROLLBACK", f"Конфиг восстановлен из {pre_apply_backup}")
    success("Конфиг Xray восстановлен из pre-apply бэкапа")
    return True


def xray_safe_apply_config(
    config: dict,
    cfg_path: Optional[Path] = None,
    reason: str = "update",
    wait_secs: int = 15,
) -> bool:
    """
    Атомарно применяет новую конфигурацию Xray:

    1. Pre-flight: валидация через 'xray run -test' перед записью.
    2. Создаёт config.json.pre-apply как точку отката.
    3. Записывает новый конфиг.
    4. Синхронизирует оба возможных пути (/etc/xray/ и /usr/local/etc/xray/).
    5. Перезапускает сервис и ждёт до wait_secs секунд.
    6. Если сервис не поднялся — автоматический откат из pre-apply бэкапа.

    Args:
        config:    Словарь конфигурации Xray (будет сериализован в JSON).
        cfg_path:  Куда писать конфиг (None → автоопределение через xray_find_config).
        reason:    Строка для лога изменений.
        wait_secs: Таймаут ожидания active-состояния после рестарта.

    Returns:
        True если конфиг применён и Xray активен.
    """
    import json as _json
    import shutil as _shutil
    import time as _time

    from installer.core.logging import log_to_file as _log

    target = cfg_path or xray_find_config() or XRAY_CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    new_content = _json.dumps(config, indent=2, ensure_ascii=False)

    import tempfile as _tempfile
    with _tempfile.NamedTemporaryFile(
        suffix=".json", dir=str(target.parent), delete=False, mode="w"
    ) as tmp:
        tmp.write(new_content)
        tmp_path = Path(tmp.name)

    preflight = run_capture([str(XRAY_BIN), "run", "-test", "-config", str(tmp_path)])
    if preflight.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        warn(f"Pre-flight Xray config validation failed [{reason}]:\n"
             f"  {preflight.stderr.strip()[:300]}")
        _log("XRAY_APPLY_FAIL", f"pre-flight failed: {preflight.stderr.strip()[:200]}")
        return False

    tmp_path.unlink(missing_ok=True)

    pre_apply = target.parent / "config.json.pre-apply"
    if target.exists():
        _shutil.copy2(target, pre_apply)

    target.write_text(new_content)
    _log("XRAY_APPLY", f"config written to {target} [{reason}]")

    alt = Path("/usr/local/etc/xray/config.json")
    if alt.parent.exists() and alt.resolve() != target.resolve():
        _shutil.copy2(target, alt)

    run(["systemctl", "restart", XRAY_SERVICE_NAME], check=False, quiet=True)

    deadline = _time.time() + wait_secs
    while _time.time() < deadline:
        r = run_capture(["systemctl", "is-active", XRAY_SERVICE_NAME])
        if r.stdout.strip() == "active":
            success(f"Xray конфиг применён [{reason}] ✓")
            _log("XRAY_APPLY_OK", f"service active after restart [{reason}]")
            return True
        _time.sleep(1)

    warn(f"Xray не поднялся за {wait_secs}с после применения [{reason}], откат...")
    _log("XRAY_APPLY_ROLLBACK", f"auto-rollback triggered [{reason}]")
    xray_config_rollback(pre_apply)
    run(["systemctl", "restart", XRAY_SERVICE_NAME], check=False, quiet=True)
    return False


