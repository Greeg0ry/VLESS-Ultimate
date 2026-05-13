"""
services/nginx.py — Установка и настройка Nginx для работы с Xray.

Поддерживаемые режимы:
  - REALITY:  Nginx проксирует fallback-трафик через unix-сокет (proxy_protocol)
  - xHTTP:    Nginx — только HTTP→HTTPS редирект (Xray сам владеет :443)
  - AWG:      Nginx — только HTTP→HTTPS редирект

Правило: перед изменением конфига Nginx всегда вызывать backup.create_backup().
"""

from __future__ import annotations

import re
import socket
import textwrap
from pathlib import Path

from installer.core.shell import run, run_capture, find_binary
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import (
    NGINX_CONF_DIR, NGINX_ENABLED_DIR, NGINX_RATE_LIMIT,
    nginx_site_conf, nginx_site_enabled, le_cert_dir,
)
from installer.core.constants import NGINX_SERVICE_NAME


def find_nginx_bin() -> str | None:
    """Возвращает путь к бинарнику nginx или None."""
    return find_binary("nginx", "/usr/sbin/nginx", "/usr/local/sbin/nginx")


def get_nginx_version() -> tuple[int, int, str]:
    """
    Возвращает (major, minor, version_string) установленного Nginx.
    По умолчанию (1, 18, "1.18.0") если определить не удалось.
    """
    nginx_bin = find_nginx_bin()
    if not nginx_bin:
        return 1, 18, "1.18.0"
    try:
        r = run_capture([nginx_bin, "-v"])
        m = re.search(r'(\d+)\.(\d+)\.(\d+)', r.stderr)
        if m:
            maj, minor = int(m.group(1)), int(m.group(2))
            return maj, minor, f"{maj}.{minor}.{m.group(3)}"
    except Exception:
        pass
    return 1, 18, "1.18.0"


def setup_nginx_temp(domain: str, web_root: Path) -> None:
    """
    Создаёт минимальный HTTP-конфиг Nginx для прохождения ACME-challenge certbot.

    После получения сертификата вызывай setup_nginx_final().
    """
    info("Настройка Nginx для certbot (временный конфиг)...")

    nginx_bin = find_nginx_bin()
    if not nginx_bin:
        info("  nginx не найден — устанавливаю...")
        run(["apt-get", "install", "-y", "-q", "nginx"],
            env={"DEBIAN_FRONTEND": "noninteractive"},
            check=False, quiet=True)
        nginx_bin = find_nginx_bin() or "/usr/sbin/nginx"

    _fix_nginx_symlink(nginx_bin)

    web_root.mkdir(parents=True, exist_ok=True)
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
    NGINX_ENABLED_DIR.mkdir(parents=True, exist_ok=True)

    cfg = nginx_site_conf(domain)
    cfg.write_text(textwrap.dedent(f"""\
        server {{
            listen 80;
            listen [::]:80;
            server_name {domain};
            root {web_root};
            index index.html;
            location /.well-known/acme-challenge/ {{ root {web_root}; }}
            location / {{ return 301 https://$host$request_uri; }}
        }}
    """))

    link = nginx_site_enabled(domain)
    link.unlink(missing_ok=True)
    link.symlink_to(cfg)
    (NGINX_ENABLED_DIR / "default").unlink(missing_ok=True)

    r = run_capture([nginx_bin, "-t"])
    if r.returncode == 0:
        run(["systemctl", "reload", NGINX_SERVICE_NAME], check=False, quiet=True)
    else:
        run(["systemctl", "restart", NGINX_SERVICE_NAME], check=False, quiet=True)
    success("Nginx запущен для certbot")


def setup_nginx_final(
    domain: str,
    web_root: Path,
    socket_path: str,
    server_port: int,
    protocol_mode: str,
    awg_enabled: bool,
) -> None:
    """
    Создаёт финальный конфиг Nginx после получения сертификата.

    Args:
        domain:        Домен сайта.
        web_root:      Директория статики.
        socket_path:   Путь к unix-сокету (только для REALITY).
        server_port:   Порт Xray (для xHTTP/AWG — комментарий в конфиге).
        protocol_mode: "reality", "xhttp" или другое.
        awg_enabled:   True если используется AWG.
    """
    info("Настройка финального конфига Nginx...")

    web_root.mkdir(parents=True, exist_ok=True)
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
    NGINX_ENABLED_DIR.mkdir(parents=True, exist_ok=True)

    if protocol_mode == "xhttp":
        _setup_redirect_only(domain, web_root, server_port, "xHTTP TLS")
        return

    if awg_enabled:
        _setup_redirect_only(domain, web_root, server_port, "AWG 2.0")
        return

    _setup_reality_full(domain, web_root, socket_path)


def _setup_redirect_only(domain: str, web_root: Path, port: int, mode_label: str) -> None:
    """Nginx как HTTP→HTTPS редирект (Xray владеет HTTPS-портом)."""
    nginx_bin = find_nginx_bin() or "/usr/sbin/nginx"
    cfg = nginx_site_conf(domain)
    cfg.write_text(textwrap.dedent(f"""\
        # HTTP → HTTPS redirect ({mode_label} — Xray слушает :{port} напрямую)
        server {{
            listen 80;
            listen [::]:80;
            server_name {domain};
            root {web_root};
            index index.html;
            location /.well-known/acme-challenge/ {{ root {web_root}; }}
            location / {{ return 301 https://$host$request_uri; }}
        }}
    """))
    link = nginx_site_enabled(domain)
    link.unlink(missing_ok=True)
    link.symlink_to(cfg)

    r = run_capture([nginx_bin, "-t"])
    if r.returncode == 0:
        run(["systemctl", "reload", NGINX_SERVICE_NAME], check=False, quiet=True)
    else:
        run(["systemctl", "restart", NGINX_SERVICE_NAME], check=False, quiet=True)
    success(f"Nginx настроен ({mode_label}: только HTTP→HTTPS редирект)")


def _setup_reality_full(domain: str, web_root: Path, socket_path: str) -> None:
    """Полный конфиг REALITY: HTTPS через unix-сокет с proxy_protocol."""
    nginx_bin = find_nginx_bin() or "/usr/sbin/nginx"
    maj, minor, ver = get_nginx_version()

    if maj > 1 or (maj == 1 and minor >= 25):
        listen_main    = f"listen unix:{socket_path} ssl proxy_protocol;"
        listen_default = f"listen unix:{socket_path} ssl proxy_protocol default_server;"
        http2_line     = "    http2 on;"
        info(f"Nginx {ver}: директива 'http2 on'")
    else:
        listen_main    = f"listen unix:{socket_path} ssl http2 proxy_protocol;"
        listen_default = f"listen unix:{socket_path} ssl http2 proxy_protocol default_server;"
        http2_line     = ""
        info(f"Nginx {ver}: http2 в строке listen")

    rate_limit = ""
    if NGINX_RATE_LIMIT.exists():
        rate_limit = (
            "    limit_req zone=general burst=20 nodelay;\n"
            "    limit_conn conn_limit 10;"
        )

    cfg = nginx_site_conf(domain)
    cfg.write_text(textwrap.dedent(f"""\
        # HTTP → HTTPS redirect
        server {{
            listen 80;
            listen [::]:80;
            server_name {domain};
            return 301 https://$host$request_uri;
        }}

        # Main server: VLESS fallback via Unix socket
        server {{
            server_name {domain};

            {listen_main}
        {http2_line}

            ssl_certificate     /etc/letsencrypt/live/{domain}/fullchain.pem;
            ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
            ssl_protocols TLSv1.2 TLSv1.3;
            ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
            ssl_prefer_server_ciphers on;

            real_ip_header proxy_protocol;
            set_real_ip_from unix:;

            root {web_root};
            index index.html;

            add_header X-Robots-Tag "noindex, nofollow" always;
        {rate_limit}

            location / {{
                try_files $uri $uri/ =404;
            }}
        }}

        # Default server: reject all other SNI
        server {{
            {listen_default}
            server_name _;
            ssl_reject_handshake on;
            return 444;
        }}
    """))

    _create_temp_socket(socket_path)

    link = nginx_site_enabled(domain)
    link.unlink(missing_ok=True)
    link.symlink_to(cfg)

    r = run_capture([nginx_bin, "-t"])
    log_to_file("INFO", r.stderr)

    if r.returncode == 0:
        r_active = run_capture(["systemctl", "is-active", NGINX_SERVICE_NAME])
        if r_active.stdout.strip() == "active":
            run(["systemctl", "reload", NGINX_SERVICE_NAME], check=False, quiet=True)
        success(f"Nginx финально настроен (Nginx {ver})")
    else:
        for line in r.stderr.splitlines()[-5:]:
            warn(f"  {line}")
        info("Nginx запустится вместе с Xray (финальный шаг установки)")

    Path(socket_path).unlink(missing_ok=True)
    run(["systemctl", "stop", NGINX_SERVICE_NAME], check=False, quiet=True)


def setup_nginx_systemd_override() -> None:
    """
    Добавляет drop-in для Nginx: After=xray.service.
    Гарантирует, что Nginx стартует после Xray (unix-сокет уже готов).
    """
    info("Настройка зависимости Nginx → Xray в systemd...")
    override_dir = Path("/etc/systemd/system/nginx.service.d")
    override_dir.mkdir(parents=True, exist_ok=True)
    override_file = override_dir / "xray-dependency.conf"
    override_file.write_text(textwrap.dedent("""\
        [Unit]
        After=xray.service
        Wants=xray.service
    """))
    run(["systemctl", "daemon-reload"], quiet=True, check=False)
    success("Зависимость Nginx → Xray настроена")


def _fix_nginx_symlink(nginx_bin: str) -> None:
    """Исправляет битый симлинк /usr/local/bin/nginx → реальный бинарник."""
    nginx_lbin = Path("/usr/local/bin/nginx")
    if nginx_lbin.is_symlink() and not nginx_lbin.exists():
        nginx_lbin.unlink()
    if nginx_bin and not nginx_lbin.exists():
        try:
            nginx_lbin.symlink_to(nginx_bin)
        except Exception:
            pass


def _create_temp_socket(socket_path: str) -> None:
    """
    Создаёт временный unix-сокет чтобы nginx -t прошёл проверку.
    Xray ещё не запущен, поэтому сокета нет — без него nginx -t упадёт с ошибкой.
    """
    p = Path(socket_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(str(p))
            s.close()
        except Exception:
            pass

