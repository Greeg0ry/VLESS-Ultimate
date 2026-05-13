"""
core/constants.py — Все константы, URL, имена сервисов и глобальные строковые параметры.

Правило: здесь ТОЛЬКО константы. Никакого I/O, никаких системных вызовов.
"""

VERSION = "4.06"
APP_NAME = "VLESS Ultimate Installer"
APP_NAME_FULL = f"{APP_NAME} v{VERSION}"

SUPPORTED_OS = [
    "ubuntu:20.04", "ubuntu:22.04", "ubuntu:24.04",
    "debian:11", "debian:12", "debian:13",
]

XRAY_SERVICE_NAME   = "xray"
XRAY_USER           = "xray"
XRAY_GROUP          = "xray"
XRAY_STATS_API_PORT = 10085

XRAY_RELEASE_API_URL    = "https://api.github.com/repos/XTLS/Xray-core/releases"
XRAY_DOWNLOAD_BASE_URL  = "https://github.com/XTLS/Xray-core/releases/download"

GEOSITE_URL = (
    "https://raw.githubusercontent.com/runetfreedom/"
    "russia-v2ray-rules-dat/release/geosite.dat"
)
GEOIP_URL = (
    "https://raw.githubusercontent.com/runetfreedom/"
    "russia-v2ray-rules-dat/release/geoip.dat"
)

NGINX_SERVICE_NAME = "nginx"

CERTBOT_SNAP_BIN = "/snap/bin/certbot"
CERTBOT_APT_BIN  = "/usr/bin/certbot"

FAIL2BAN_SERVICE_NAME = "fail2ban"
FAIL2BAN_JAIL_NAME    = "xray-reality"

DNSCRYPT_SERVICE_NAME = "dnscrypt-proxy"
DNSCRYPT_LISTEN_ADDR  = "127.0.0.1"
DNSCRYPT_LISTEN_PORT  = 5300

WARP_SERVICE_NAME = "warp-svc"

WARP_MODE_FULL      = "full"
WARP_MODE_SELECTIVE = "selective"
WARP_MODE_RUNET     = "runet"

AWG_DEFAULT_SUBNET      = "10.66.66.0/24"
AWG_DEFAULT_CLIENT_IP   = "10.66.66.2/32"
AWG_DEFAULT_SERVER_IP   = "10.66.66.1/32"
AWG_DEFAULT_SUBNET_V6   = "fd66:66:66::/64"
AWG_DEFAULT_CLIENT_IPv6 = "fd66:66:66::2/128"
AWG_DEFAULT_SERVER_IPv6 = "fd66:66:66::1/128"
AWG_DEFAULT_MTU         = 1280
AWG_DEFAULT_PORT        = 51820
AWG_INTERFACE_NAME      = "awg0"
AWG_FWMARK              = 1000
AWG_ROUTE_TABLE         = 1000

AWG_DEFAULT_JC   = 4
AWG_DEFAULT_JMIN = 40
AWG_DEFAULT_JMAX = 70
AWG_DEFAULT_S1   = 0
AWG_DEFAULT_S2   = 0
AWG_DEFAULT_H1   = 1
AWG_DEFAULT_H2   = 2
AWG_DEFAULT_H3   = 3
AWG_DEFAULT_H4   = 4

PROTOCOL_REALITY = "reality"
PROTOCOL_XHTTP   = "xhttp"

XTLS_FLOW_VISION = "xtls-rprx-vision"
XTLS_FLOW_SPLICE = "xtls-rprx-splice"
XTLS_FLOW_NONE   = ""

XHTTP_MODE_STREAMUP  = "streamup"
XHTTP_MODE_STREAMONE = "streamone"
XHTTP_MODE_PACKETUP  = "packetup"

BALANCER_ROUND_ROBIN = "roundRobin"
BALANCER_LEAST_PING  = "leastPing"
BALANCER_LEAST_LOAD  = "leastLoad"
BALANCER_RANDOM      = "random"

BALANCER_STRATEGIES = [
    BALANCER_ROUND_ROBIN,
    BALANCER_LEAST_PING,
    BALANCER_LEAST_LOAD,
    BALANCER_RANDOM,
]

INSTALL_MODE_A = "A"
INSTALL_MODE_B = "B"

MAX_CHAIN_NODES = 10

DEFAULT_SERVER_PORT = 443
DEFAULT_SSH_PORT    = 22
PROBE_TIMEOUT_SEC   = 3.0
PROBE_INTERVAL_MIN  = 5

_DIAG_STATS_API_ADDR = f"127.0.0.1:{XRAY_STATS_API_PORT}"

MIN_RAM_MB_RECOMMENDED = 2048
MIN_RAM_MB_SUPPORTED   = 512
MAX_RETRIES            = 5

GEO_API_URL = "http://ip-api.com/json?fields=status,country,countryCode,city"

THEME_ENV_VAR   = "VLESS_THEME"
THEME_LIGHT_VAL = "light"


RIPE_STAT_PREFIXES_URL = "https://stat.ripe.net/data/announced-prefixes/data.json"
RIPE_STAT_ASN_URL      = "https://stat.ripe.net/data/rir-stats-country/data.json"
IP_TO_ASN_API_URL      = "https://stat.ripe.net/data/prefix-routing-consistency/data.json"
IPINFO_ASN_URL         = "https://ipinfo.io/{ip}/json"

ASN_XRAY_CIDR_BATCH    = 500

ASN_RESERVED_0         = 0
ASN_RESERVED_TRANS     = 23456
ASN_MAX                = 4294967295

ASN_ACTION_DIRECT  = "direct"
ASN_ACTION_PROXY   = "proxy"
ASN_ACTION_BLOCK   = "block"
ASN_ACTIONS        = [ASN_ACTION_DIRECT, ASN_ACTION_PROXY, ASN_ACTION_BLOCK]

ASN_UPDATE_INTERVAL_DAYS = 1

ASN_TIMER_NAME   = "xray-as-direct.timer"
ASN_SERVICE_NAME = "xray-as-direct.service"

CHANGE_LOG_LABEL = "AS_ROUTE"

CLIENT_CONFIGS_DIR = "/root/xray-client-configs"

LOGROTATE_CONF_NAME     = "xray-vless"
LOGROTATE_CONF_DIR      = "/etc/logrotate.d"
LOGROTATE_DEFAULT_FREQ  = "daily"
LOGROTATE_DEFAULT_KEEP  = 14

SCHEDULED_BACKUP_CRON_FILE   = "/etc/cron.d/xray-backup"
SCHEDULED_BACKUP_DEFAULT_DAYS = 1
SCHEDULED_BACKUP_KEEP_LAST    = 7
SCHEDULED_BACKUP_LOG          = "/var/log/xray-scheduled-backup.log"


