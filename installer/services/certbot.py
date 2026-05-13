"""
services/certbot.py — Получение и обновление TLS-сертификатов Let's Encrypt.

Правило: перед вызовом certbot убедись, что Nginx запущен и домен резолвится
в IP сервера (DNS-проверка). Иначе certbot упадёт с ошибкой ACME challenge.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from installer.core.shell import run, run_capture, find_binary
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import le_fullchain, le_privkey, le_cert_dir
from installer.core.system import get_server_ip, generate_self_signed_cert


def find_certbot() -> Optional[str]:
    """Возвращает путь к certbot (/snap/bin/certbot или /usr/bin/certbot)."""
    return find_binary("/snap/bin/certbot", "/usr/bin/certbot", "certbot")


def check_dns_resolves(domain: str) -> bool:
    """
    Проверяет, что домен резолвится в публичный IPv4 сервера.
    Возвращает True если совпадает, False если нет или проверить не удалось.
    """
    server_ip = get_server_ip("4")
    if not server_ip:
        return True
    try:
        r = run_capture(["dig", "+short", domain])
        if r.returncode == 0 and server_ip in r.stdout.strip().split():
            return True
    except Exception:
        pass
    return False


def get_cert_days_left(domain: str) -> int:
    """
    Возвращает количество дней до истечения сертификата.
    -1 если сертификат не найден или не удалось определить.
    """
    cert = le_fullchain(domain)
    if not cert.exists():
        return -1
    try:
        r = run_capture(["openssl", "x509", "-enddate", "-noout", "-in", str(cert)])
        expiry = r.stdout.strip().split("=", 1)[1]
        r2 = run_capture(["date", "-d", expiry, "+%s"])
        expiry_epoch = int(r2.stdout.strip())
        return (expiry_epoch - int(time.time())) // 86400
    except Exception:
        return -1


def obtain_ssl_cert(
    domain: str,
    email: str,
    web_root: Path,
    force_renew: bool = True,
) -> bool:
    """
    Получает TLS-сертификат Let's Encrypt через webroot-метод.

    Если certbot не справился — генерирует самоподписанный сертификат
    (fallback, чтобы Nginx не падал).

    Args:
        domain:      FQDN, для которого нужен сертификат.
        email:       Email для уведомлений LE.
        web_root:    Директория для ACME-challenge файлов.
        force_renew: True — принудительный перевыпуск даже если сертификат ещё валиден.

    Returns:
        True если сертификат получен (или уже существует), False если только самоподпись.
    """
    info(f"Получение SSL-сертификата для {domain}...")

    certbot = find_certbot()
    if not certbot:
        warn("certbot не установлен — генерируем самоподписанный сертификат")
        generate_self_signed_cert(domain)
        return False

    web_root.mkdir(parents=True, exist_ok=True)
    (web_root / "index.html").write_text("<h1>ACME Verification</h1>")

    cmd = [
        certbot, "certonly", "--webroot",
        "--webroot-path", str(web_root),
        "--non-interactive", "--agree-tos",
        "--email", email,
        "-d", domain,
    ]
    if force_renew:
        cmd.append("--force-renewal")

    r = run(cmd, capture=True, check=False)
    if r.returncode == 0:
        success("Сертификат Let's Encrypt успешно выпущен")
        return True

    log_to_file("WARN", f"certbot завершился с кодом {r.returncode}: {r.stderr.strip()}")
    warn("Не удалось получить сертификат LE — генерируем самоподписанный")
    generate_self_signed_cert(domain)
    return False


def fix_letsencrypt_permissions(domain: str) -> None:
    """
    Выставляет права на файлы сертификата так, чтобы пользователь xray мог их читать.

    Xray читает сертификаты напрямую (в режиме xHTTP TLS).
    Без этого Xray падает с ошибкой 'permission denied on privkey.pem'.
    """
    import grp
    import os as _os

    archive_dir     = Path(f"/etc/letsencrypt/archive/{domain}")
    live_domain_dir = le_cert_dir(domain)

    if not archive_dir.exists():
        warn(f"fix_letsencrypt_permissions: {archive_dir} не найден — пропускаем")
        return

    for d in (
        Path("/etc/letsencrypt/live"),
        live_domain_dir,
        Path("/etc/letsencrypt/archive"),
        archive_dir,
    ):
        try:
            if d.exists():
                d.chmod(0o755)
        except Exception as e:
            warn(f"Ошибка установки прав на {d}: {e}")

    try:
        xray_gid = grp.getgrnam('xray').gr_gid
        has_xray = True
    except KeyError:
        has_xray = False

    for f_path in archive_dir.glob("privkey*.pem"):
        try:
            if has_xray:
                _os.chown(str(f_path), 0, xray_gid)
            _os.chmod(str(f_path), 0o640)
        except Exception as e:
            warn(f"Не удалось исправить права для {f_path}: {e}")

    for pattern in ("fullchain*.pem", "chain*.pem", "cert*.pem"):
        for f_path in archive_dir.glob(pattern):
            try:
                _os.chmod(str(f_path), 0o644)
            except Exception as e:
                warn(f"Не удалось исправить права для {f_path}: {e}")

    success(
        f"Права на сертификаты для {domain} обновлены "
        f"({'root:xray 640/644' if has_xray else '644 для всех'})"
    )


def setup_cert_renewal(domain: str) -> None:
    """
    Настраивает автоматическое обновление сертификата через systemd timer.
    """
    info("Настройка автообновления сертификата...")
    certbot = find_certbot()
    if not certbot:
        warn("certbot не найден — автообновление не настроено")
        return

    r = run_capture(["systemctl", "is-enabled", "snap.certbot.renew.timer"])
    if r.returncode == 0:
        success("Автообновление certbot (snap) уже активно")
        return

    r = run_capture(["systemctl", "is-active", "certbot.timer"])
    if r.stdout.strip() == "active":
        success("certbot.timer уже активен")
        return

    _ensure_cert_fix_hook(domain)
    success("Автообновление сертификата настроено")


def _ensure_cert_fix_hook(domain: str) -> None:
    """Создаёт post-hook certbot для исправления прав после обновления."""
    hook_dir = Path("/etc/letsencrypt/renewal-hooks/post")
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook = hook_dir / f"fix-xray-cert-{domain}.sh"
    hook.write_text(f"""\
#!/bin/bash
# Исправляет права на сертификат после обновления certbot.
# Нужно потому что certbot создаёт privkey с правами 600 root:root —
# пользователь xray не может его читать.
python3 -c "
import sys; sys.path.insert(0, '/opt/vless-ultimate')
from installer.services.certbot import fix_letsencrypt_permissions
fix_letsencrypt_permissions('{domain}')
"
systemctl reload xray 2>/dev/null || true
""")
    hook.chmod(0o755)

