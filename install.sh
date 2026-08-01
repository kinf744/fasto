#!/usr/bin/env bash
set -e

REPO_URL="https://github.com/kinf744/fasto/raw/main"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'
WHITE='\033[0;97m'; RST='\033[0m'

echo -e "\n  ${CYAN}╔══════════════════════════════════════════════════════╗${RST}"
echo -e "            ${WHITE}Kighmu Panel — Installation automatique${RST}"
echo -e "  ${CYAN}╚══════════════════════════════════════════════════════╝${RST}\n"

[[ $EUID -eq 0 ]] || { echo -e "  ${RED}✗${RST} Root requis."; exit 1; }

os_id=$(grep ^ID= /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')
[[ "$os_id" =~ ^(debian|ubuntu)$ ]] || { echo -e "  ${RED}✗${RST} Debian/Ubuntu seulement."; exit 1; }

export DEBIAN_FRONTEND=noninteractive
echo -e "  ${YELLOW}→${RST} Mise à jour des paquets..."
apt-get update -qq
echo -e "  ${YELLOW}→${RST} Installation des dépendances..."
apt-get install -y -qq curl git sqlite3 openssl screen nftables jq unzip python3 2>/dev/null

case "$(uname -m)" in
    x86_64|amd64)  BIN_NAME="install2.bin" ;;
    aarch64|arm64) BIN_NAME="install2-arm64.bin" ;;
    *) echo -e "  ${RED}✗${RST} Architecture non supportée : $(uname -m)"; exit 1 ;;
esac

BIN="/usr/local/bin/kighmu"
echo -e "  ${YELLOW}→${RST} Téléchargement du binaire (${BIN_NAME})..."
curl -sL "${REPO_URL}/${BIN_NAME}" -o "$BIN"
chmod 700 "$BIN"

echo -e "  ${GREEN}✓${RST} Lancement du panneau..."
"$BIN" --install
