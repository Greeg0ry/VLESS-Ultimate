# TROUBLESHOOTING.md — Частые проблемы и решения

## Xray не стартует

```bash
# Проверить статус
systemctl status xray
journalctl -u xray --no-pager -n 50

# Проверить конфиг вручную
/usr/local/bin/xray run -test -config /etc/xray/config.json

# Частые причины:
# 1. Права на config.json (нужны 640 root:xray)
ls -la /etc/xray/config.json
chown root:xray /etc/xray/config.json && chmod 640 /etc/xray/config.json

# 2. Занят порт 443
ss -tlnp | grep 443
# Если занят nginx — остановить: systemctl stop nginx

# 3. Нет бинарника
ls -la /usr/local/bin/xray
```

---

## Nginx не стартует

```bash
# Проверить синтаксис конфига
nginx -t

# Посмотреть ошибки
journalctl -u nginx --no-pager -n 30

# Частые причины:
# 1. Unix-сокет не создан (Xray ещё не запущен)
#    → Сначала запустить Xray: systemctl start xray
#    → Потом Nginx: systemctl start nginx

# 2. Сертификат не найден
ls /etc/letsencrypt/live/yourdomain.com/

# 3. Порт 80 занят
ss -tlnp | grep :80
```

---

## Certbot не получил сертификат

```bash
# Проверить DNS (домен должен указывать на IP сервера)
dig +short yourdomain.com
curl -4 ifconfig.me

# Убедиться что порт 80 открыт
ufw status | grep 80
curl -v http://yourdomain.com/.well-known/acme-challenge/test

# Попробовать вручную
certbot certonly --webroot -w /var/www/yourdomain.com -d yourdomain.com

# Если не работает webroot — попробовать standalone
systemctl stop nginx
certbot certonly --standalone -d yourdomain.com
systemctl start nginx
```

---

## Нет IPv6

```bash
# Проверить наличие глобального IPv6-адреса
ip -6 addr show scope global

# Проверить маршрут
ip -6 route show default

# Если IPv6 есть, но не работает — проверить UFW
ufw status verbose | grep v6

# Разрешить IPv6 в UFW
ufw allow 443/tcp
ufw reload
```

---

## Ошибка прав на config.json

```bash
# Симптом: xray падает с кодом 23 ("permission denied")
# Решение:
groupadd -f xray
usermod -aG xray xray 2>/dev/null || true
chown root:xray /etc/xray/config.json
chmod 640 /etc/xray/config.json

# Проверить группу
id xray
ls -la /etc/xray/config.json
```

---

## APT lock (apt занят)

```bash
# Симптом: "Could not get lock /var/lib/dpkg/lock-frontend"
# Причина: фоновые автообновления

# Подождать завершения
while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    echo "Ждём apt..."
    sleep 5
done

# Принудительно убить (осторожно!)
# kill -9 $(fuser /var/lib/dpkg/lock-frontend 2>/dev/null)
# rm -f /var/lib/dpkg/lock-frontend /var/cache/apt/archives/lock
# dpkg --configure -a
```

---

## Не найден бинарник

```bash
# xray
which xray || ls /usr/local/bin/xray
# Переустановить через меню: Управление Xray → Обновить/Переустановить

# nginx
which nginx || ls /usr/sbin/nginx

# certbot
ls /snap/bin/certbot /usr/bin/certbot 2>/dev/null

# curl, wget
apt-get install -y curl wget
```

---

## Потерян доступ по SSH

```bash
# Если SSH-порт закрыт UFW случайно — используй консоль VPS-провайдера:

# Открыть SSH
ufw allow 22/tcp
ufw reload

# Или временно выключить UFW
ufw disable
# (потом включить: ufw enable)
```

**Профилактика:** скрипт всегда добавляет `allow 22/tcp` ПЕРВЫМ при
настройке UFW, до любых других правил. EXIT TRAP также открывает порт 22
при аварийном завершении.

---

## Xray/Nginx падают после обновления системы

```bash
# Обновить конфиг systemd
systemctl daemon-reload
systemctl enable xray nginx
systemctl start xray nginx

# Проверить, не изменился ли путь к бинарнику
which xray
# Если путь изменился — обновить ExecStart в /etc/systemd/system/xray.service
```

---

## Диагностика одной командой

```bash
# Полная диагностика через установщик
sudo python3 install.py
# → Диагностика → Полная диагностика

# Или напрямую
sudo python3 -c "
from installer.diagnostics.health import run_full_health_check
run_full_health_check('yourdomain.com', 443)
"
```

---

## AS-маршрутизация (asn_routing)

**RIPE NCC API недоступен:**
```bash
# Проверить доступность
curl -v "https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS8359"
# Если блокировка — префиксы будут загружены из локального кэша (SQLite)
# Принудительно сбросить кэш и перезагрузить:
python3 -c "
from installer.services.asn_routing import update_all_asn_prefixes
update_all_asn_prefixes()
"
```

**Правила AS не применяются:**
```bash
# Проверить, что config.json содержит маркер _comment: "_asn_<ASN>_auto"
grep -i "_asn_" /etc/xray/config.json
# Проверить список активных маршрутов
cat /etc/xray/as_direct_list.json
```

**Таймер автообновления не работает:**
```bash
systemctl status xray-as-direct.timer
systemctl status xray-as-direct.service
journalctl -u xray-as-direct.service -n 30
# Перезапустить вручную
systemctl restart xray-as-direct.timer
```

---

## Xray не поднялся после применения конфига (авто-откат)

Если `xray_safe_apply_config()` произвёл авто-откат:
```bash
# Смотрим лог изменений
grep "XRAY_APPLY_ROLLBACK\|XRAY_APPLY_FAIL" /var/log/xray-changes.log | tail -20
# Проверяем pre-apply бэкап
ls -la /etc/xray/config.json.pre-apply
# Запустить pre-flight вручную
xray run -test -config /etc/xray/config.json.pre-apply
```

---

## Экспорт Clash Meta / Sing-box не создаётся

```bash
# Проверить права на директорию
ls -la /root/xray-client-configs/
# Для Clash Meta нужен pyyaml (опционально — при отсутствии создаётся .json)
pip3 install pyyaml
# Экспортировать вручную
python3 -c "
import sys; sys.path.insert(0, '/opt/vless-installer')
from installer.core.state import InstallerState
from installer.core.paths import STATE_FILE
from installer.config_builders.client_links import export_client_configs
state = InstallerState.load(STATE_FILE)
export_client_configs(state)
"
```

---

## Ротация логов не работает

```bash
# Проверить конфиг logrotate
cat /etc/logrotate.d/xray-vless
# Принудительная ротация для проверки
logrotate -df /etc/logrotate.d/xray-vless   # dry-run
logrotate -f /etc/logrotate.d/xray-vless    # применить
# Если logrotate не установлен
apt install logrotate
```

---

## Плановый backup не выполняется

```bash
# Проверить cron-задачу
cat /etc/cron.d/xray-backup
# Проверить лог
tail -20 /var/log/xray-scheduled-backup.log
# Запустить вручную
python3 -c "
from installer.core.backup import create_scheduled_backup
create_scheduled_backup(keep_last=7)
"
# Проверить, что cron запущен
systemctl status cron || systemctl status crond
```

