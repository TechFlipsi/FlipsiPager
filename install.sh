#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  Feuerwehr-Einsatz-Monitor — Installations-Assistent (Linux/Pi)
#  Einzeiler:  curl -fsSL https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main/install.sh | bash
#  Was das Skript tut: Python/System prüfen, Bot-Token + FF-Daten interaktiv
#  abfragen, Config + systemd-Service anlegen, Bot starten und prüfen.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main"
FW_DIR="$HOME/.config/fw_bot"
SERVICE_NAME="feuerwehr-monitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_PATH="$HOME/feuerwehr-monitor/einsatz_watcher_v4.py"

B="\033[1m"; G="\033[32m"; Y="\033[33m"; R="\033[31m"; N="\033[0m"
say()  { echo -e "${G}==>${N} $1"; }
warn() { echo -e "${Y} !!${N} $1"; }
die()  { echo -e "${R} ✗${N} $1" >&2; exit 1; }

echo -e "${B}🔥 Feuerwehr-Einsatz-Monitor — Installation${N}"
echo "─────────────────────────────────────────────"
echo "Dieses Skript installiert den Bot auf DIESEM Rechner und richtet"
echo "einen systemd-Dienst ein. Es fragt vorher alles ab — nichts wird"
echo "ohne deine Eingabe geändert. Abbruch jederzeit mit Strg+C."
echo

# ── Root-Check für systemd (sudo wird nur für Service-Datei gebraucht) ──
if [ "$(id -u)" -eq 0 ]; then
    die "Bitte NICHT als root ausführen (der Bot soll unter deinem Benutzer laufen). Verwende: bash install.sh"
fi
SUDO=""
if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

# ── 1. System-Voraussetzungen ──
say "Prüfe System-Voraussetzungen…"
command -v python3 >/dev/null 2>&1 || die "python3 nicht gefunden. Installiere es: sudo apt install python3"
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 - "$PYV" <<'EOF'
import sys
v = sys.argv[1].split(".")
ok = (int(v[0]), int(v[1])) >= (3, 10)
sys.exit(0 if ok else 1)
EOF
[ $? -eq 0 ] || die "Python 3.11+ nötig, gefunden: $PYV"
say "Python $PYV ✓ (empfohlen 3.11+)"

# systemd vorhanden?
if command -v systemctl >/dev/null 2>&1; then
    HAS_SYSTEMD=1
else
    HAS_SYSTEMD=0
    warn "Kein systemd gefunden — der Bot wird per nohup gestartet (kein Autostart nach Reboot)."
fi

# ── 2. Bestehende Installation? ──
if [ -f "$FW_DIR/fw_bot.conf" ]; then
    warn "Bestehende Installation gefunden ($FW_DIR)."
    read -rp "   Neu installieren und alte Werte überschreiben? [j/N] " jn
    [ "${jn:-n}" = "j" ] || die "Abgebrochen."
fi

echo
echo -e "${B}── Schritt 1/4: Deine Feuerwehr ──${N}"
read -rp "Name deiner Feuerwehr (z. B. FF Musterdorf): " FF_NAME
[ -n "$FF_NAME" ] || die "Feuerwehr-Name darf nicht leer sein."

read -rp "einsaetze.at Organisations-ID (Enter = automatisch suchen): " FF_ORG
if [ -z "$FF_ORG" ]; then
    say "Suche '$FF_NAME' im einsaetze.at-Index …"
    TMPF_ORG=$(mktemp)
    python3 - "$FF_NAME" > "$TMPF_ORG" 2>/dev/null <<PYEOF_ORG
import json, sys, urllib.request, difflib
name = sys.argv[1].lower().strip()
idx_url = "https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main/data/einsaetze_at_index.json"
idx = {}
try:
    with urllib.request.urlopen(idx_url, timeout=15) as r:
        idx = json.loads(r.read())
except Exception:
    idx = {}
best = difflib.get_close_matches(name, idx.keys(), n=1, cutoff=0.4)
print(idx[best[0]] if best else "")
PYEOF_ORG
    FF_ORG=$(head -n1 "$TMPF_ORG" | tr -d "[:space:]")
    rm -f "$TMPF_ORG"
    if [ -n "$FF_ORG" ]; then
        say "Organisations-ID gefunden: $FF_ORG"
    else
        warn "Konnte die Org-ID nicht automatisch finden."
        read -rp "   Org-ID manuell eingeben (oder leer lassen → Historie-Befehl deaktiviert): " FF_ORG
    fi
fi

echo
echo -e "${B}── Schritt 2/4: Telegram-Bot anlegen ──${N}"
echo "1. Öffne in Telegram den Chat mit @BotFather"
echo "2. Sende:  /newbot"
echo "3. Gib einen Namen (z. B. '$FF_NAME Einsatz-Monitor') und einen Benutzernamen"
echo "   (muss auf 'bot' enden, z. B. ${FF_NAME// /}_monitor_bot) ein."
echo "4. BotFather antwortet mit einem TOKEN (sieht aus wie 123456:ABC-DEF...)."
echo
read -rp "Token einfügen: " BOT_TOKEN
case "$BOT_TOKEN" in
    *:*) : ;;  # grobe Form-Prüfung
    "") die "Kein Token — Abbruch." ;;
    *)  warn "Das sieht nicht wie ein Token aus (Format: 123456:ABC-…). Fortsetzung trotzdem." ;;
esac

echo
echo -e "${B}── Schritt 3/4: Deine Admin-Chat-ID ──${N}"
echo "Die Admin-ID ist deine Telegram-Kennung. Zwei Wege:"
echo "  (a) Du weißt sie schon → jetzt eintippen"
echo "  (b) Automatisch erkennen: Ich frage Telegram ab, während du deinem"
echo "      neuen Bot eine Nachricht schickst."
read -rp "ID direkt eingeben (Enter = automatisch erkennen): " ADMIN_ID
if [ -z "$ADMIN_ID" ]; then
    say "Warte auf deine erste Nachricht an den Bot (max. 120 s)…"
    echo "   → Öffne Telegram und schick deinem Bot jetzt irgendwas (z. B. hi)."
    ADMIN_ID=""
    for i in $(seq 1 24); do
        RESP=$(curl -fsS --max-time 10 "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates" 2>/dev/null || true)
        CID=$(echo "$RESP" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    res = d.get("result", [])
    if res:
        print(res[0]["message"]["chat"]["id"])
except Exception:
    pass
' 2>/dev/null || true)
        if [ -n "$CID" ]; then ADMIN_ID="$CID"; break; fi
        sleep 5
    done
    [ -n "$ADMIN_ID" ] || die "Keine Nachricht empfangen. Hast du dem Bot geschrieben? Danach Skript erneut starten."
    say "Admin-Chat-ID erkannt: $ADMIN_ID"
fi
case "$ADMIN_ID" in
    ''|*[!0-9]*) die "Admin-ID muss eine positive Zahl sein." ;;
esac

echo
echo -e "${B}── Schritt 4/4: Feineinstellungen ──${N}"
read -rp "Poll-Intervall in Sekunden [60] (Respekt vor der Datenquelle — 60 empfohlen): " POLL
POLL=${POLL:-60}
case "$POLL" in ''|*[!0-9]*) POLL=60 ;; esac
[ "$POLL" -ge 5 ] || POLL=5
read -rp "Maximale Benutzeranzahl [2000]: " MAXU
MAXU=${MAXU:-2000}
case "$MAXU" in ''|*[!0-9]*) MAXU=2000 ;; esac
read -rp "InkyPi-E-Display anbinden? URL eingeben oder Enter für nein: " INKYPI_URL

# ── 3. Dateien anlegen ──
say "Schreibe Konfiguration nach $FW_DIR/ …"
mkdir -p "$FW_DIR/state"
umask 077
cat > "$FW_DIR/fw_bot.conf" <<CONF
[feuerwehr]
name = $FF_NAME
org_id = ${FF_ORG:-}

[besitzer]
admin_id = $ADMIN_ID
admin_username =

[bot]
poll_interval = $POLL
max_users = $MAXU
inkypi_api = ${INKYPI_URL:-}
CONF
cat > "$FW_DIR/bot_token.env" <<CONF
FW_BOT_TOKEN=$BOT_TOKEN
FW_BOT_CHAT_ID=$ADMIN_ID
CONF
umask 022

say "Lade Bot-Skript …"
mkdir -p "$(dirname "$SCRIPT_PATH")"
curl -fsSL "${REPO_RAW}/einsatz_watcher_v4.py" -o "$SCRIPT_PATH" || die "Download des Skripts fehlgeschlagen."
chmod 700 "$SCRIPT_PATH"

# ── 4. systemd-Service ──
if [ "$HAS_SYSTEMD" = "1" ]; then
    say "Richte systemd-Service ein …"
    $SUDO tee "$SERVICE_FILE" >/dev/null <<UNIT
[Unit]
Description=Feuerwehr-Einsatz-Monitor ($FF_NAME)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(dirname "$SCRIPT_PATH")
ExecStart=/usr/bin/python3 $SCRIPT_PATH
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
UNIT
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    say "Warte 20 s auf ersten Start …"; sleep 20
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        say "$(systemctl is-active $SERVICE_NAME) — Bot läuft."
    else
        warn "Service noch nicht aktiv — Log ansehen: journalctl -u $SERVICE_NAME -n 20"
    fi
else
    say "Starte Bot im Hintergrund (nohup) …"
    nohup python3 "$SCRIPT_PATH" > "$FW_DIR/bot.log" 2>&1 &
    echo $! > "$FW_DIR/bot.pid"
fi

echo
echo -e "${G}═══════════════════════════════════════════${N}"
echo -e "${G} ✅ Installation abgeschlossen!${N}"
echo -e "${G}═══════════════════════════════════════════${N}"
echo "  Öffne Telegram und schick deinem Bot:  /start"
echo "  Danach:  /registrieren <DeinName>"
echo "  Alle Befehle:  /hilfe   ·   Datenquellen:  /quellen"
echo
echo "  Verwaltung:"
[ "$HAS_SYSTEMD" = "1" ] && echo "   Status:  systemctl status $SERVICE_NAME" && \
echo "   Logs:    journalctl -u $SERVICE_NAME -f" && \
echo "   Neustart: sudo systemctl restart $SERVICE_NAME"
echo "   Config:  $FW_DIR/fw_bot.conf (danach Service neu starten)"
echo
echo "  ⚠️  Inoffizielles Projekt — im Notfall gilt IMMER Sirene/Funk/Notruf 122."