# 📖 Anleitung: Feuerwehr-Einsatz-Monitor selbst hosten

So betreibst du deinen **eigenen** Einsatz-Monitor-Bot für deine Feuerwehr — auf einem Raspberry Pi oder jedem Linux-Rechner. Dauer: **~10 Minuten**.

> ⚠️ **Vorab ehrlich:** Das ist ein Projekt für Leute, die mit dem Terminal umgehen können. Es ist kein One-Click-Produkt. Wer das nicht möchte: Es gibt fertige Telegram-Bots mit ähnlichem Funktionsumfang — unser offizieller Bot ist via `t.me/feuerwehroff_bot` erreichbar.

---

## Was du brauchst

- Raspberry Pi (3, 4, 5, Zero 2 W — alles reicht) **oder** jeder Linux-Rechner/VPS
- SD-Karte mit Raspberry Pi OS / Debian / Ubuntu (Python 3.10+)
- SSH-Zugang oder Tastatur+Bildschirm am Gerät
- Internetzugang
- **Telegram-Account** (für dich und deine Kameraden)

## Was der Bot macht (Kurzfassung)

- 🔥 Alarm bei Einsätzen an deinen beobachteten Orten (OOELFV, OÖ)
- ⛈️ Unwetter-Warnungen (GeoSphere), 🌊 Pegel (Hydro OÖ), ⚡ Stromausfälle (Netz OÖ), ❄️ Lawinen (Land OÖ)
- 👥 Deine Kameraden registrieren sich selbst beim Bot
- 🔐 Alle Daten bleiben auf deinem Gerät

---

## Schritt 1: Bot bei Telegram anlegen (2 Min)

1. Öffne in Telegram den Chat mit **[@BotFather](https://t.me/BotFather)**
2. Sende `/newbot`
3. Name: z. B. `FF Musterdorf Einsatz-Monitor`
4. Benutzername: muss auf `bot` enden, z. B. `ff_musterdorf_monitor_bot`
5. BotFather antwortet mit einem **Token** — kopiere ihn dir (Format: `123456:ABC-DEF1234…`)

> 🔒 Den Token **niemals weitergeben** — wer ihn hat, kontrolliert deinen Bot!

## Schritt 2: Einzeiler-Installation (5 Min)

Verbinde dich per SSH mit deinem Pi und führe aus:

```bash
curl -fsSL https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main/install.sh | bash
```

> 🔍 Misstrauisch? (Gut so!) Dann erst ansehen und manuell starten:
> ```bash
> curl -fsSL https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main/install.sh -o install.sh
> less install.sh
> bash install.sh
> ```

Der Assistent fragt dich alles ab:

| Frage | Antwort |
|---|---|
| Name deiner Feuerwehr | `FF Musterdorf` |
| Organisations-ID | **Enter** (= wird automatisch gesucht) |
| Bot-Token | Den Token aus Schritt 1 einfügen |
| Admin-Chat-ID | **Enter** (= wird automatisch erkannt — du schickst deinem Bot dann eine Nachricht) |
| Poll-Intervall | **Enter** (60 s, fair für die Datenquellen) |
| Max. Benutzer | **Enter** (2000) |
| InkyPi-Display | **Enter** (nur für E-Ink-Display-Besitzer) |

Danach legt der Installer an: `~/.config/fw_bot/` (Config + Token, chmod 600), lädt das Bot-Skript, richtet den systemd-Dienst `feuerwehr-monitor` ein und startet ihn.

## Schritt 3: Erste Anmeldung (1 Min)

Öffne in Telegram deinen neuen Bot und sende:

```
/start
```

Danach:

```
/registrieren DeinName
```

Du bist jetzt **Admin** deiner Instanz (Benutzer verwalten, `/rundruf`, Sperren etc.).

## Schritt 4: Beobachten & Testen

```
/ort Musterdorf          ← Ort dauerhaft beobachten (Alarm bei jedem Einsatz)
/hilfe                   ← alle Befehle
/testalarm               ← prüft, ob die Alarm-Kette bei dir funktioniert
/quellen                 ← zeigt alle Datenquellen
/datenschutz             ← DSGVO-Info für deine Kameraden
```

Lade deine Kameraden ein: Sie starten den Bot und registrieren sich selbst — du musst nichts anlegen.

---

## ⚙️ Konfiguration nachträglich ändern

```bash
nano ~/.config/fw_bot/fw_bot.conf
sudo systemctl restart feuerwehr-monitor
```

Alle Optionen sind in `fw_bot.conf.example` dokumentiert (Poll-Intervall, User-Limit, InkyPi, FF-Name, Org-ID).

**Wichtig:** Die Telegram-Kennung des Admins steht in **beiden** Dateien (`fw_bot.conf` → `admin_id` und `bot_token.env` → `FW_BOT_CHAT_ID`). Bei Änderung: beide anpassen.

## 🔧 Wartung

```bash
systemctl status feuerwehr-monitor     # läuft der Bot?
journalctl -u feuerwehr-monitor -f     # Live-Log
sudo systemctl restart feuerwehr-monitor   # Neustart
sudo systemctl disable --now feuerwehr-monitor  # Autostart aus
```

**Update auf neue Version:**

```bash
cd ~/feuerwehr-monitor
curl -fsSL https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main/einsatz_watcher_v4.py -o einsatz_watcher_v4.py
chmod 700 einsatz_watcher_v4.py
sudo systemctl restart feuerwehr-monitor
```

Deine Daten (`users.json`, State, Logs unter `~/.config/fw_bot/`) bleiben davon unberührt.

## 🩺 Troubleshooting

| Problem | Lösung |
|---|---|
| Bot antwortet nicht | `journalctl -u feuerwehr-monitor -n 30` — steht dort `Token fehlt`/`401` → Token falsch, `bot_token.env` prüfen |
| „Unauthorized" im Log | Token falsch oder widerrufen — bei BotFather `/mybots` → Token neu generieren → `bot_token.env` aktualisieren → Neustart |
| Historie/Übungen leer | Org-ID falsch — bei [einsaetze.at](https://einsaetze.at) deine Wehr suchen, die Zahl in der URL ist die Org-ID → `fw_bot.conf` → Neustart |
| „Leider sind alle Plätze belegt" | User-Limit erreicht — `max_users` in der Config erhöhen oder alte Benutzer löschen |
| Bot stoppt nach Reboot nicht mehr / startet nicht | `systemctl enable feuerwehr-monitor` |
| Keine Alarme trotz Einsatz | 1. Bist du registriert? 2. `/ort <Ort>` gesetzt? 3. `/testalarm` — schlägt er fehl, siehe Log |
| Alarm kommt zu spät | Poll-Intervall hoch? 60 s = bis zu 1 Min Verzögerung (normal & fair). Für sofortigen Alarm 5 s, aber nur bei kleiner Nützerzahl |

## 🗑️ Deinstallation

```bash
sudo systemctl disable --now feuerwehr-monitor
sudo rm /etc/systemd/system/feuerwehr-monitor.service
sudo systemctl daemon-reload
rm -rf ~/feuerwehr-monitor ~/.config/fw_bot
```

---

## ⚠️ Rechtliches & Verlässlichkeit

- Privates, **inoffizielles** Projekt — **keine offizielle Alarmierung!** Sirene, Funk, Pager und **Notruf 122** gehen immer vor.
- Liest ausschließlich öffentliche Quellen (OOELFV, einsaetze.at, GeoSphere, Hydro OÖ, Netz OÖ, Lawinenwarndienst OÖ, OpenStreetMap). Details im Bot: `/quellen`.
- **Du bist Betreiber deiner Instanz** — der Umgang mit den Daten deiner Benutzer (DSGVO) liegt bei dir. Der Bot hilft dir: Offene Registrierung, `/datenschutz`-Info, Zwei-Stufen-Selbstlöschung, `/meinedaten`-Auskunft sind eingebaut.
- **OÖ-Fokus:** Die Quellen decken Oberösterreich ab. Andere Regionen funktionieren nicht.

## 📜 Lizenz

MIT mit Non-Commercial-Einschränkung — privat, Bildung und Feuerwehren (intern, gemeinnützig) frei. Kommerzielle Nutzung nur mit schriftlicher Erlaubnis. Details: [LICENSE](../LICENSE)