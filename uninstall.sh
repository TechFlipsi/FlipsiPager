#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  FlipsiPager — Deinstallation (restlose Entfernung)
#
#  Einzeiler:
#    curl -fsSL https://raw.githubusercontent.com/TechFlipsi/FlipsiPager/main/uninstall.sh | bash
#    (Alles inklusive Nutzerdaten: … | bash -s -- --purge)
#
#  Stoppt/entfernt den systemd-Dienst und das Programm-Verzeichnis.
#  Nutzerdaten (~/.config/fw_bot: Nützer, Beobachtungen, Token) bleiben
#  standardmäßig ERHALTEN — Wiedereinsetzen später übernimmt sie automatisch.
#  Mit --purge werden auch die Daten gelöscht.
# ═══════════════════════════════════════════════════════════════════
FW_DIR="$HOME/.config/fw_bot"
SERVICE_NAME="feuerwehr-monitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

B="\033[1m"; R="\033[31m"; G="\033[32m"; N="\033[0m"
say() { echo -e "${G}==>${N} $1"; }

echo -e "${B}🗑️ FlipsiPager — Deinstallation${N}"
echo "─────────────────────────────────────────────"

SUDO=""
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

say "Stoppe und entferne Dienst ($SERVICE_NAME) …"
$SUDO systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
$SUDO rm -f "$SERVICE_FILE"
$SUDO systemctl daemon-reload 2>/dev/null || true

say "Entferne Programm-Verzeichnis ~/feuerwehr-monitor …"
rm -rf "$HOME/feuerwehr-monitor"

say "Dienst und Programm entfernt."

if [ "${1:-}" = "--purge" ]; then
    rm -rf "$FW_DIR"
    say "🗑️ Nutzerdaten gelöscht: $FW_DIR"
else
    say "💾 Nutzerdaten BEHALTEN: $FW_DIR (token, users.json, Beobachtungen)."
    say "   Restlos löschen:  curl -fsSL https://raw.githubusercontent.com/TechFlipsi/FlipsiPager/main/uninstall.sh | bash -s -- --purge"
    say "   Wiedereinsetzen:  normale Installation — die Altdaten werden übernommen."
fi
