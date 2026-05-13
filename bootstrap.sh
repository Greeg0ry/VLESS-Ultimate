#!/usr/bin/env bash
# VLESS Ultimate Installer — bootstrap
# Использование: bash <(curl -fsSL https://raw.githubusercontent.com/Greeg0ry/VLESS-Ultimate/master/bootstrap.sh)

set -euo pipefail

REPO_URL="https://github.com/Greeg0ry/VLESS-Ultimate.git"
INSTALL_DIR="/opt/vless-ultimate"
BRANCH="master"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${CYAN}[•] $*${NC}"; }
success() { echo -e "${GREEN}[✓] $*${NC}"; }
warn()    { echo -e "${YELLOW}[!] $*${NC}"; }
die()     { echo -e "${RED}[✗] $*${NC}"; exit 1; }

require_root() {
    [ "$(id -u)" -eq 0 ] || die "Запустите от root: sudo bash <(curl -fsSL ...)"
}

check_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "$ID:$VERSION_ID" in
            ubuntu:20.04|ubuntu:22.04|ubuntu:24.04|debian:11|debian:12|debian:13)
                success "ОС поддерживается: $PRETTY_NAME" ;;
            *)
                warn "Неподдерживаемая ОС: $PRETTY_NAME. Продолжаю на свой риск..." ;;
        esac
    fi
}

install_deps() {
    info "Установка зависимостей (git, python3)..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y -qq git python3 python3-pip curl
    else
        die "apt-get не найден. Поддерживаются только Debian/Ubuntu."
    fi
    success "Зависимости установлены"
}

fetch_or_update_repo() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Обновление репозитория в $INSTALL_DIR..."
        git -C "$INSTALL_DIR" fetch --quiet origin
        git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH" --quiet
        success "Репозиторий обновлён"
    else
        info "Клонирование репозитория в $INSTALL_DIR..."
        rm -rf "$INSTALL_DIR"
        git clone --depth=1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" --quiet
        success "Репозиторий клонирован"
    fi
}

run_installer() {
    info "Запуск установщика..."
    cd "$INSTALL_DIR"
    exec python3 install.py "$@"
}

main() {
    echo ""
    echo -e "${CYAN}  ╔══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}  ║     VLESS Ultimate Installer         ║${NC}"
    echo -e "${CYAN}  ╚══════════════════════════════════════╝${NC}"
    echo ""

    require_root
    check_os
    install_deps
    fetch_or_update_repo
    run_installer "$@"
}

main "$@"

