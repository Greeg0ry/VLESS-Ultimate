# VLESS Ultimate

Модульный установщик VLESS/Xray с поддержкой REALITY, xHTTP TLS, Nginx, Certbot, WARP, AmneziaWG, split tunneling, диагностики и автоматического backup/rollback.

---

## ⚡ Быстрый запуск

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Greeg0ry/VLESS-Ultimate/master/bootstrap.sh)
```

> Требуется **root**. Поддерживаемые ОС: Ubuntu 20.04 / 22.04 / 24.04, Debian 11 / 12 / 13.

---

## 🚀 Что делает скрипт

- Устанавливает и настраивает **Xray-core** (VLESS REALITY или xHTTP TLS)
- Настраивает **Nginx** как reverse-proxy / маскировку
- Выпускает TLS-сертификаты через **Certbot**
- Настраивает **UFW**, **Fail2ban**, **DNSCrypt**
- Поднимает **WARP** и **AmneziaWG** для цепочки прокси
- Настраивает **split tunneling** и AS-маршрутизацию (ASN via RIPE NCC)
- Экспортирует клиентские конфиги (**Clash Meta**, **Sing-box**, ссылки)
- Управляет **backup/rollback**, ротацией логов, автообновлением

---

## 📋 Режимы установки

| Режим | Описание |
|-------|----------|
| **Mode A** | VLESS REALITY — без TLS-сертификата, сложнее детектировать |
| **Mode B** | xHTTP TLS + Nginx — полноценный TLS с маскировкой |
| **Диагностика** | Проверка статуса всех сервисов без изменений |
| **Backup / Rollback** | Сохранение и восстановление конфигурации |

---

## 🗂 Где что находится

| Что | Путь |
|-----|------|
| Xray config | `/usr/local/etc/xray/config.json` |
| Nginx config | `/etc/nginx/conf.d/vless.conf` |
| TLS сертификаты | `/etc/letsencrypt/live/<домен>/` |
| Логи Xray | `/var/log/xray/` |
| Логи установщика | `/var/log/vless-installer.log` |
| Backup-архивы | `/opt/vless-backup/` |

---

## 🔧 Полезные команды

```bash
# Статус сервисов
systemctl status xray nginx

# Перезапуск
systemctl restart xray nginx

# Логи Xray в реальном времени
journalctl -u xray -f

# Диагностика
python3 /opt/vless-ultimate/install.py --diagnostics

# Backup вручную
python3 /opt/vless-ultimate/install.py --backup

# Rollback
python3 /opt/vless-ultimate/install.py --rollback
```

---

## 📚 Документация

| Документ | Описание |
|----------|----------|
| [ARCHITECTURE.md](installer/docs/ARCHITECTURE.md) | Структура проекта, модули, поток установки |
| [TROUBLESHOOTING.md](installer/docs/TROUBLESHOOTING.md) | Решение типовых проблем |

---

## 🏗 Структура проекта

```
install.py              # точка входа
bootstrap.sh            # one-liner для запуска с сервера
installer/
  main.py               # главный поток установки
  cli/                  # баннер, прогресс-бар, меню
  core/                 # state, shell, paths, logging, validators, backup
  services/             # xray, nginx, certbot, ufw, fail2ban, warp, awg, dnscrypt
  config_builders/      # сборка конфигов Xray, Nginx, клиентских ссылок
  diagnostics/          # health, network, xray_stats
  docs/                 # документация
```

