"""
services/xray_update.py — Обновление Xray-core до новой версии.

Полный update flow:
  1. Получение информации о релизах (latest + prerelease)
  2. Скачивание zip + SHA256 верификация
  3. Pre-flight тест конфига новым бинарником
  4. Бэкап старого бинарника
  5. Замена бинарника
  6. Перезапуск сервисов + ожидание active
  7. Автоматический rollback если Xray не поднялся
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from installer.core.shell import run, run_capture
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import XRAY_BIN, XRAY_BACKUP_DIR
from installer.core.constants import (
    XRAY_RELEASE_API_URL, XRAY_DOWNLOAD_BASE_URL,
    GEOSITE_URL, GEOIP_URL,
    XRAY_SERVICE_NAME,
)


def get_current_version() -> str:
    """Возвращает версию установленного Xray (vX.Y.Z) или 'v0.0.0'."""
    try:
        r = run_capture([str(XRAY_BIN), "version"])
        m = re.search(r'[0-9]+\.[0-9]+\.[0-9]+', r.stdout)
        if m:
            return "v" + m.group(0)
    except Exception:
        pass
    return "v0.0.0"


def get_release_info(prerelease: bool = False) -> Optional[dict]:
    """
    Запрашивает информацию о последнем релизе GitHub.

    Args:
        prerelease: True — искать в том числе prerelease-теги.

    Returns:
        Словарь с tag_name, prerelease и т.д. или None.
    """
    if prerelease:
        url = f"{XRAY_RELEASE_API_URL}?per_page=5"
    else:
        url = f"{XRAY_RELEASE_API_URL}/latest"

    try:
        r = run_capture([
            "curl", "-fsSL", "--connect-timeout", "10",
            "-H", "Accept: application/vnd.github+json", url,
        ])
        if r.returncode != 0 or not r.stdout.strip():
            return None
        data = json.loads(r.stdout)
        if prerelease and isinstance(data, list):
            for item in data:
                if item.get("prerelease") and item.get("tag_name"):
                    return item
            return None
        return data
    except Exception:
        return None


def _version_norm(ver: str) -> tuple[int, int, int]:
    """Нормализует строку версии в кортеж (major, minor, patch)."""
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', ver)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (0, 0, 0)


def _detect_arch() -> str:
    """Определяет суффикс архитектуры для скачиваемого zip Xray."""
    r = run_capture(["uname", "-m"])
    m = r.stdout.strip()
    return {"x86_64": "64", "aarch64": "arm64-v8a"}.get(m,
           "arm32-v7a" if m.startswith("armv7") else "64")


def geo_is_runetfreedom() -> bool:
    """Проверяет, что установлены geo-файлы из runetfreedom."""
    for d in (Path("/etc/xray"), Path("/usr/local/share/xray"), Path("/usr/local/etc/xray")):
        p = d / "geosite.dat"
        if not p.exists():
            continue
        try:
            r = subprocess.run(
                ["grep", "-qaF", "ru-available-only-inside", str(p)],
                capture_output=True,
            )
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return False


def update_geo_files() -> bool:
    """Скачивает geosite.dat и geoip.dat из runetfreedom."""
    targets = [Path("/etc/xray"), Path("/usr/local/share/xray")]
    ok = True
    for dat_name, url in (("geosite.dat", GEOSITE_URL), ("geoip.dat", GEOIP_URL)):
        info(f"Загрузка {dat_name}...")
        for dest_dir in targets:
            if not dest_dir.exists():
                continue
            dest = dest_dir / dat_name
            r = run([
                "curl", "-fsSL", "--connect-timeout", "30", "--retry", "2",
                url, "-o", str(dest),
            ], check=False, quiet=True)
            if r.returncode == 0 and dest.exists() and dest.stat().st_size > 100_000:
                success(f"{dat_name} → {dest}")
                break
        else:
            warn(f"Не удалось скачать {dat_name}")
            ok = False
    return ok


def upgrade(tag: str, is_prerelease: bool = False) -> bool:
    """
    Скачивает, верифицирует и устанавливает Xray версии tag.

    Returns:
        True если бинарник успешно заменён и тест конфига прошёл.
    """
    from installer.services.xray import _verify_sha256

    current = get_current_version()
    arch = _detect_arch()
    zip_name = f"Xray-linux-{arch}.zip"
    zip_url  = f"{XRAY_DOWNLOAD_BASE_URL}/{tag}/{zip_name}"
    chk_url  = f"{XRAY_DOWNLOAD_BASE_URL}/{tag}/SHA256SUMS"

    info(f"Загрузка Xray {tag} ({'prerelease' if is_prerelease else 'stable'})...")
    zip_tmp = Path("/tmp/xray_update.zip")
    r = run([
        "curl", "-fsSL", "--connect-timeout", "30", "--retry", "3",
        zip_url, "-o", str(zip_tmp),
    ], check=False, quiet=True)
    if r.returncode != 0:
        warn(f"Ошибка загрузки: {zip_url}")
        return False

    if not _verify_sha256(zip_tmp, chk_url, zip_name):
        zip_tmp.unlink(missing_ok=True)
        warn("SHA256 верификация провалилась")
        return False
    info("SHA256: OK")

    with tempfile.TemporaryDirectory(prefix="xray_upd.") as ext_dir:
        run(["unzip", "-o", str(zip_tmp), "xray", "-d", ext_dir], check=False, quiet=True)
        zip_tmp.unlink(missing_ok=True)
        new_bin = Path(ext_dir) / "xray"
        if not new_bin.exists():
            warn("xray не найден в архиве")
            return False

        if not geo_is_runetfreedom():
            info("Обновление geo-файлов (runetfreedom)...")
            if not update_geo_files():
                warn("Не удалось обновить geo-файлы — обновление Xray отменено")
                return False

        cfg_path = None
        for cp in (Path("/etc/xray/config.json"), Path("/usr/local/etc/xray/config.json")):
            if cp.exists():
                cfg_path = cp
                break

        if cfg_path:
            info("Тест конфига новым бинарником...")
            _copy_geo_to_tmpdir(ext_dir)
            rt = run_capture([str(new_bin), "run", "-test", "-config", str(cfg_path)])
            if rt.returncode != 0:
                warn(f"Тест конфига не прошёл:\n{(rt.stderr or rt.stdout).strip()[:300]}")
                return False
            info("Тест конфига: OK")

        XRAY_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = XRAY_BACKUP_DIR / f"xray_{current}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            shutil.copy2(XRAY_BIN, backup)
            for old in sorted(XRAY_BACKUP_DIR.glob("xray_*"))[:-5]:
                old.unlink(missing_ok=True)
            info(f"Бэкап: {backup}")
        except Exception as e:
            warn(f"Бэкап бинарника не создан: {e}")

        try:
            XRAY_BIN.unlink(missing_ok=True)
        except Exception:
            pass
        shutil.copy2(new_bin, XRAY_BIN)
        XRAY_BIN.chmod(0o755)

    log_to_file("XRAY_UPDATE", f"{current} → {tag}")
    return True


def _copy_geo_to_tmpdir(tmpdir: str) -> None:
    """Копирует runetfreedom geo-файлы в tmpdir для теста нового бинарника."""
    for dat in ("geosite.dat", "geoip.dat"):
        for src_dir in (Path("/etc/xray"), Path("/usr/local/share/xray")):
            src = src_dir / dat
            if src.exists() and src.stat().st_size > 3_000_000:
                try:
                    shutil.copy2(src, Path(tmpdir) / dat)
                except Exception:
                    pass
                break


def restart_all_services(wait_secs: int = 15) -> bool:
    """Перезапускает xray (и nginx если активен). Возвращает True если xray active."""
    import time
    run(["systemctl", "restart", XRAY_SERVICE_NAME], check=False, quiet=True)
    deadline = time.time() + wait_secs
    while time.time() < deadline:
        r = run_capture(["systemctl", "is-active", XRAY_SERVICE_NAME])
        if r.stdout.strip() == "active":
            from installer.core.shell import service_is_active
            if service_is_active("nginx"):
                run(["systemctl", "restart", "nginx"], check=False, quiet=True)
            return True
        time.sleep(1)
    return False


def rollback_binary(backup_path: Path) -> bool:
    """Восстанавливает бинарник из бэкапа."""
    if not backup_path.exists():
        warn(f"Бэкап не найден: {backup_path}")
        return False
    try:
        XRAY_BIN.unlink(missing_ok=True)
        shutil.copy2(backup_path, XRAY_BIN)
        XRAY_BIN.chmod(0o755)
        success(f"Бинарник восстановлен из {backup_path.name}")
        return True
    except Exception as e:
        warn(f"Ошибка rollback: {e}")
        return False

