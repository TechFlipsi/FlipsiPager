#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  Container-Einstiegspunkt für den Feuerwehr-Einsatz-Monitor
#
#  Konfiguration NUR über Umgebungsvariablen (kein Config-File nötig):
#    FW_BOT_TOKEN     (Pflicht)  Bot-Token vom @BotFather
#    FW_ADMIN_ID      (Pflicht)  Telegram-Chat-ID des Admins
#    FW_FF_NAME       (optional) Name der Stamm-Feuerwehr (Default: Offenhausen)
#    FW_ORG_ID        (optional) einsaetze.at-Org-ID (leer = Auto-Findung)
#    FW_POLL_INTERVAL (optional) Sekunden zwischen den Abfragen (Default: 60)
#    FW_MAX_USERS     (optional) maximale Anzahl registrierter Nützer (Default: 2000)
#    TZ               (optional) Zeitzone (Default: Europe/Vienna)
#
#  Die Variablen werden beim Start in /data/.config/fw_bot/ geschrieben,
#  damit der Bot (der nur seine Dateien liest) unverändert bleibt.
#  Ein Mount auf /data macht alle Daten persistent (Bot-Token, Nützer,
#  Beobachtungen) — der Container selbst bleibt austauschbar.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

FW_DIR="/data/.config/fw_bot"
if ! mkdir -p "$FW_DIR/state" 2>/dev/null; then
    echo "❌ Kein Schreibzugriff auf /data — das Volume-Verzeichnis gehört nicht dem Bot-Nützer (uid 1000)." >&2
    echo "   Fix auf dem Host:  sudo chown -R 1000:1000 <dein-data-Verzeichnis>" >&2
    exit 1
fi

# ── Pflichtvariablen prüfen ──────────────────────────────────────
if [ -z "${FW_BOT_TOKEN:-}" ]; then
    echo "❌ FW_BOT_TOKEN ist nicht gesetzt — der Bot-Token vom @BotFather fehlt." >&2
    echo "   Beispiel: docker run -e FW_BOT_TOKEN=123456:ABC -e FW_ADMIN_ID=123456789 …" >&2
    exit 1
fi
if [ -z "${FW_ADMIN_ID:-}" ]; then
    echo "❌ FW_ADMIN_ID ist nicht gesetzt — die Telegram-Chat-ID des Admins fehlt." >&2
    echo "   Tipp: Schick deinem Bot eine Nachricht und lies sie auf api.telegram.org nach" >&2
    echo "         (getUpdates mit deinem Token), oder nutze den install.sh-Assistenten." >&2
    exit 1
fi

# ── Token-Datei schreiben/aktualisieren (nur wenn geändert) ──────
TOKEN_FILE="$FW_DIR/bot_token.env"
NEW_TOKEN="FW_BOT_TOKEN=$FW_BOT_TOKEN
FW_BOT_CHAT_ID=$FW_ADMIN_ID"
if [ ! -f "$TOKEN_FILE" ] || [ "$(cat "$TOKEN_FILE")" != "$NEW_TOKEN" ]; then
    printf '%s\n' "$NEW_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "✅ Token-Datei aktualisiert."
fi

# ── Config schreiben/aktualisieren ───────────────────────────────
CONF="$FW_DIR/fw_bot.conf"
NEW_CONF="[feuerwehr]
name = ${FW_FF_NAME:-Offenhausen}
org_id = ${FW_ORG_ID:-}

[besitzer]
admin_id = $FW_ADMIN_ID

[bot]
poll_interval = ${FW_POLL_INTERVAL:-60}
max_users = ${FW_MAX_USERS:-2000}
inkypi_api =
"
if [ ! -f "$CONF" ] || [ "$(cat "$CONF")" != "$NEW_CONF" ]; then
    printf '%s\n' "$NEW_CONF" > "$CONF"
    chmod 600 "$CONF"
    echo "✅ Konfiguration aktualisiert (FF ${FW_FF_NAME:-Offenhausen}, Admin $FW_ADMIN_ID)."
fi

echo "🚀 Starte Feuerwehr-Einsatz-Monitor …"
exec python3 /app/einsatz_watcher_v4.py