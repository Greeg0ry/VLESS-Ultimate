"""
core/paths.py — Все файловые пути, используемые установщиком.

Правило: только Path-объекты и функции их вычисления.
Никакого I/O при импорте, никакого создания директорий здесь.
Создание директорий — только в core/system.py::ensure_dirs().
"""

from pathlib import Path

XRAY_BIN          = Path("/usr/local/bin/xray")
XRAY_SERVICE_FILE = Path("/etc/systemd/system/xray.service")
XRAY_CONFIG_DIR   = Path("/etc/xray")
XRAY_CONFIG_FILE  = XRAY_CONFIG_DIR / "config.json"
XRAY_ALT_CONFIG   = Path("/usr/local/etc/xray/config.json")
XRAY_LOG_DIR      = Path("/var/log/xray")
XRAY_ACCESS_LOG   = XRAY_LOG_DIR / "access.log"
XRAY_ERROR_LOG    = XRAY_LOG_DIR / "error.log"
XRAY_LOCK_FILE    = XRAY_CONFIG_DIR / ".vless_installed"

BACKUP_DIR        = Path("/var/backups/xray")
XRAY_BACKUP_DIR   = BACKUP_DIR / "binaries"
STATE_DIR         = Path("/var/lib/xray-installer")
STATE_FILE        = STATE_DIR / "state.json"
HEALTH_CHECK_FILE = STATE_DIR / "health.status"
CHECKPOINT_FILE   = STATE_DIR / "checkpoint.json"
UFW_MARK_FILE     = STATE_DIR / "ufw-rules"

LOG_FILE             = Path("/var/log/vless-install.log")
CHANGE_LOG_FILE      = Path("/var/log/xray-changes.log")
AUTO_FALLBACK_LOG    = Path("/var/log/xray-auto-fallback.log")

NGINX_CONF_DIR      = Path("/etc/nginx/sites-available")
NGINX_ENABLED_DIR   = Path("/etc/nginx/sites-enabled")
NGINX_CONF_D_DIR    = Path("/etc/nginx/conf.d")
NGINX_RATE_LIMIT    = NGINX_CONF_D_DIR / "rate-limit.conf"

LETSENCRYPT_DIR     = Path("/etc/letsencrypt/live")

def le_cert_dir(domain: str) -> Path:
    """Путь к директории сертификата Let's Encrypt для домена."""
    return LETSENCRYPT_DIR / domain

def le_fullchain(domain: str) -> Path:
    return le_cert_dir(domain) / "fullchain.pem"

def le_privkey(domain: str) -> Path:
    return le_cert_dir(domain) / "privkey.pem"

FAIL2BAN_JAIL_CONF = Path("/etc/fail2ban/jail.d/xray-reality.conf")

SYSCTL_CONF    = Path("/etc/sysctl.d/99-vless-performance.conf")
LIMITS_CONF    = Path("/etc/security/limits.d/99-vless-limits.conf")
SYSTEMD_CONF   = Path("/etc/systemd/system.conf.d/99-vless-limits.conf")

DNSCRYPT_BIN      = Path("/usr/local/bin/dnscrypt-proxy")
DNSCRYPT_CONF_DIR = Path("/etc/dnscrypt-proxy")
DNSCRYPT_CONF     = DNSCRYPT_CONF_DIR / "dnscrypt-proxy.toml"
DNSCRYPT_SERVICE  = Path("/etc/systemd/system/dnscrypt-proxy.service")

WARP_MDM_FILE = Path("/var/lib/cloudflare-warp/mdm.xml")

SPLIT_TUNNEL_CUSTOM_FILE = XRAY_CONFIG_DIR / "split_tunnel_custom.json"
GEOSITE_DAT              = XRAY_CONFIG_DIR / "geosite.dat"
GEOIP_DAT                = XRAY_CONFIG_DIR / "geoip.dat"

AWG_CONF_DIR     = Path("/etc/amneziawg")
AWG_CONF_FILE    = AWG_CONF_DIR / "awg0.conf"

ASN_LIST_FILE        = XRAY_CONFIG_DIR / "as_direct_list.json"
ASN_PREFIX_CACHE_DB  = STATE_DIR / "asn_prefix_cache.sqlite3"

def asn_prefix_file(asn: int) -> Path:
    """Путь к локальному кэшу префиксов конкретного AS."""
    return XRAY_CONFIG_DIR / f"as_direct_{asn}.txt"

CLIENT_CONFIGS_DIR = Path("/root/xray-client-configs")

SCHEDULED_BACKUP_LOG = Path("/var/log/xray-scheduled-backup.log")


def nginx_site_conf(domain: str) -> Path:
    """Путь к конфигу Nginx для домена в sites-available."""
    return NGINX_CONF_DIR / domain

def nginx_site_enabled(domain: str) -> Path:
    """Путь к симлинку конфига Nginx в sites-enabled."""
    return NGINX_ENABLED_DIR / domain

def cert_fix_script(domain: str) -> Path:
    """Путь к скрипту исправления прав на сертификат."""
    return Path(f"/usr/local/bin/fix-cert-{domain}.sh")

def all_dirs_to_create() -> list[Path]:
    """
    Возвращает список директорий, которые должны существовать до запуска установщика.
    Вызывается ТОЛЬКО из core/system.py::ensure_dirs(), не при импорте.
    """
    return [
        LOG_FILE.parent,
        BACKUP_DIR,
        XRAY_BACKUP_DIR,
        STATE_DIR,
        XRAY_LOG_DIR,
        XRAY_CONFIG_DIR,
    ]

