"""
installer.services — Установка и управление системными сервисами.

Каждый модуль управляет одним сервисом и не зависит от других сервисов напрямую.

Модули:
  xray.py         — Xray-core: установка, systemd, безопасное применение конфига
  nginx.py        — Nginx: установка, конфиг, reload
  certbot.py      — Let's Encrypt TLS-сертификаты
  fail2ban.py     — Fail2ban: защита от перебора
  ufw.py          — UFW: управление фаерволом
  dnscrypt.py     — DNSCrypt-proxy: шифрование DNS
  warp.py         — Cloudflare WARP
  awg.py          — AmneziaWG (обфусцированный WireGuard)
  asn_routing.py  — AS-маршрутизация (ASN-based routing через RIPE NCC)
  logrotate.py    — Управление ротацией логов
"""

