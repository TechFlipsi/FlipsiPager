# 🇦🇹 FlipsiPager — der Feuerwehr-Einsatz-Monitor für Oberösterreich

[![Release](https://img.shields.io/github/v/release/TechFlipsi/FlipsiPager?logo=github&label=Aktuelle%20Version)](https://github.com/TechFlipsi/FlipsiPager/releases)
[![Lizenz](https://img.shields.io/badge/Lizenz-MIT%20%2B%20Non--Commercial-blue.svg)](LICENSE)
[![Plattform](https://img.shields.io/badge/Plattform-Raspberry%20Pi%20%7C%20Linux-c7a07c?logo=raspberrypi&logoColor=white)](docs/ANLEITUNG.md)
[![Sprache](https://img.shields.io/badge/Sprache-Deutsch-green.svg)](docs/ANLEITUNG.md)
[![Stars](https://img.shields.io/github/stars/TechFlipsi/FlipsiPager?style=social)](https://github.com/TechFlipsi/FlipsiPager/stargazers)

Ein **selbst hostbarer** Telegram-Bot für Feuerwehr-Einsätze in **Oberösterreich** — auf deiner eigenen Hardware. Alarm bei Einsätzen an deinen beobachteten Orten, inklusive Unwetter-Warnungen, Pegel-Überwachung, Stromausfall-Wache, Lawinenlage, Sprachalarm und vielem mehr.

Keine Cloud, kein Abo, keine Registrierung außer Telegram selbst — **deine Daten bleiben auf deinem Gerät.**

## ⚡ Schnellstart (10 Minuten)

Bot bei [@BotFather](https://t.me/BotFather) anlegen, dann auf deinem Pi/Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/TechFlipsi/FlipsiPager/main/install.sh | bash
```

Der Einrichtungsassistent fragt alles ab (Feuerwehr-Name, Bot-Token, Admin-ID — vieles wird automatisch erkannt) und richtet einen systemd-Dienst ein. **Komplette Anleitung mit allen Details:** [docs/ANLEITUNG.md](docs/ANLEITUNG.md)

## ✨ Funktionen

- 🔥 **Live-Einsatz-Alarm** für frei wählbare Orte (OOELFV)
- ⛈️ **Amtliche Unwetter-Warnungen** (GeoSphere Austria) inklusive
- 🌊 **Hochwasser-Wache** — Pegel im Umkreis deiner Orte (Hydro OÖ)
- ⚡ **Stromausfall-Wache** — Störungskarte Netz OÖ
- ❄️ **Lawinen-Wache** — Lawinenlagebericht + Zonen-Warnung
- 🗣️ **Sprachalarm** — Alarme zusätzlich als Sprachnachricht (optional)
- 📱 **Inline-Buttons** mit Karte & Navigation bei jedem Einsatz
- 📊 Statistiken, Wochenrückblicke, Übungs-Historie, QR-Code zum Weiterschicken
- 👥 **Multi-User** — offene Registrierung, pro-User Beobachtungen (10 dauerhaft + 10 temporär), Admin-Verwaltung, Auto-Ban-Schutz
- 🔐 **DSGVO-freundlich** — Selbst-Löschung mit 2-Stufen-Bestätigung, Datenschutz-Info, Quellen-Offenlegung, DSGVO-Auskunft
- 🖥️ Optional: E-Ink-Display-Anbindung (InkyPi)

## ⚙️ Konfiguration

Alles läuft über eine Datei: `~/.config/fw_bot/fw_bot.conf` (wird vom Installer angelegt, Vorlage: [fw_bot.conf.example](fw_bot.conf.example)):

```ini
[feuerwehr]
name = FF Musterdorf      # deine Feuerwehr
org_id = 000000           # einsaetze.at-Org-ID (Auto-Findung aktiv)

[besitzer]
admin_id = 123456789      # Telegram-Chat-ID des Betreibers

[bot]
poll_interval = 60        # Sekunden — Respekt vor der Datenquelle
max_users = 2000          # Kapazitäts-Limit
```

Fehlt die Datei, läuft der Bot mit Standard-Werten (Poll 5 s) — für Heimat-Instanzen mit kleinem Freundeskreis. Für öffentliche Instanzen: **60 s einstellen**.

## 🖥️ Systemvoraussetzungen

- Linux mit systemd (Raspberry Pi OS, Debian, Ubuntu — Pi Zero 2 W reicht)
- Python 3.10+ (nur Standardbibliothek + optional `pyproj` für Pegel-Koordinaten, `piper` für Sprachalarm)
- Ein Telegram-Bot-Token (kostenlos via BotFather)

## 📋 Befehle (Auszug)

| | |
|---|---|
| `/ort <Ort>` | Ort dauerhaft beobachten (Alarm bei jedem Einsatz) |
| `/einsatz <Ort>` | Nur den laufenden Einsatz beobachten |
| `/lage`, `/heute`, `/bezirk WL` | Einsätze abfragen |
| `/warnungen`, `/pegel`, `/strom`, `/waldbrand`, `/lawine` | Wachen abfragen |
| `/statistik`, `/rueckblick`, `/wochen` | Auswertungen |
| `/stumm 22-7` | Stillfenster (Alarme sammeln, morgens zustellen) |
| `/testalarm` | Alarm-Kette prüfen |
| `/quellen` | Alle Datenquellen anzeigen |
| `/datenschutz`, `/vergessen`, `/meinedaten` | DSGVO |
| `/hilfe` | Alle Befehle |

## 🧭 Was diesen Bot von anderen unterscheidet

- **Kein Cloud-Zwang:** Läuft komplett auf deiner Hardware, offline-fähig außer den Datenquellen selbst
- **Bewährtes Multi-User-System:** Offene Registrierung, Limits, Auto-Ban, Zwei-Stufen-Löschung — seit Monaten produktiv im Einsatz
- **Vier Wachen in einem:** Einsatz, Unwetter, Pegel, Stromausfall — keine vier Apps, ein Bot
- **Sprachalarm:** Der Bot ruft den Alarm zusätzlich am Ohr aus (lokale Spracherzeugung, keine Cloud-TTS)

## ⚠️ Rechtliches & Verlässlichkeit

- Privates, **inoffizielles** Projekt — **keine offizielle Alarmierung!** Sirene, Funk, Pager und **Notruf 122** gehen immer vor.
- Liest ausschließlich öffentlich zugängliche Quellen. **OÖ-Fokus** — andere Regionen werden nicht abgedeckt.
- **Du bist Betreiber deiner Instanz** und verantwortlich für den Umgang mit den Daten deiner Benutzer (DSGVO). Der Bot liefert die Werkzeuge (Datenschutz-Info, Selbstlöschung, Auskunft) mit.
- Kein offizielles Produkt des Oö. Landes-Feuerwehrverbandes oder der genannten Quellen.

## ❓ FAQ

<details>
<summary><b>Ist der Bot offiziell?</b></summary>
Nein — ein privates, inoffizielles Hobby-Projekt. Er liest öffentlich zugängliche Seiten aus (Liste im Bot via /quellen, detailliert: [docs/QUELLEN.md](docs/QUELLEN.md)). Im Notfall gilt immer die offizielle Alarmierung.
</details>

<details>
<summary><b>Funktioniert das auch außerhalb Oberösterreichs?</b></summary>
Nein, die Datenquellen sind oberösterreichisch (OOELFV, Netz OÖ, Hydro OÖ …). Der Bot ist aber so gebaut, dass eine Anpassung an andere Quellen möglich ist — Contributions willkommen.
</details>

<details>
<summary><b>Kostet das was?</b></summary>
Nein. Auf einem vorhandenen Pi entstehen keine laufenden Kosten. Ein eigener Telegram-Bot ist kostenlos.
</details>

<details>
<summary><b>Wie viele Benutzer kann meine Instanz bedienen?</b></summary>
Standard-Limit 2000 (einstellbar). Realistisch: Bis einige hundert Benutzer läuft das problemlos auf einem Pi 4. Größere Instanzen: Poll-Intervall fair halten.
</details>

<details>
<summary><b>Ist das sicher / DSGVO-konform?</b></summary>
Die Daten deiner Benutzer liegen nur auf deinem Gerät (Chat-ID, Name, beobachtete Orte — keine Adressen). Der Bot bringt DSGVO-Werkzeuge mit: Datenschutz-Info (/datenschutz), DSGVO-Auskunft (/meinedaten), Selbstlöschung mit 2-Stufen-Bestätigung (/vergessen). Du bist als Betreiber für den rechtskonformen Umgang verantwortlich.
</details>

## 🐳 Docker (Alternative zum Pi)

Wer den Bot lieber in einem Container betreibt (NAS, VPS, Homelab):

```bash
# 1. Verzeichnis anlegen und Bot-Token + Admin-ID setzen
mkdir data
# 2. Image bauen & starten (docker compose)
FW_BOT_TOKEN=dein-token FW_ADMIN_ID=deine-chat-id docker compose up -d
```

Oder direkt mit `docker run`:

```bash
docker run -d --name feuerwehr-monitor \
  -e FW_BOT_TOKEN=dein-token \
  -e FW_ADMIN_ID=deine-chat-id \
  -e FW_FF_NAME="Deine Feuerwehr" \
  -v $(pwd)/data:/data \
  --restart unless-stopped \
  feuerwehr-monitor:latest
```

**Wichtig:** Das `data`-Verzeichnis muss dem Container-Nützer gehören:

```bash
sudo chown -R 1000:1000 data
```

Alle Einstellungen laufen über Umgebungsvariablen (`FW_BOT_TOKEN`, `FW_ADMIN_ID`, `FW_FF_NAME`, `FW_ORG_ID`, `FW_POLL_INTERVAL`, `FW_MAX_USERS`, `TZ`) — die schreibt der Container beim Start automatisch in die Config unter `/data`.


## 🗺️ Roadmap

- [x] v1.0.0 — Selbsthosting-Release (Installations-Assistent, Anleitung)
- [ ] Docker-Image (docker-compose für NAS-Betreiber)
- [ ] Update-Skript (`update.sh`) für installierte Instanzen
- [ ] Regionale Erweiterung (Datenquellen außerhalb OÖ) — Community-Beitrag möglich
- [ ] Englische Oberfläche (optional, Konfig-Flag)

## 🤝 Mitmachen

Issues und Pull Requests sind willkommen! Für Bug-Reports: Service-Log (`journalctl -u feuerwehr-monitor -n 50`) beilegen (Zugangsdaten/Tokens unkenntlich!).

## 📜 Lizenz

[MIT mit Non-Commercial-Einschränkung](LICENSE) — privat, für Bildungszwecke und Feuerwehren (intern, gemeinnützig) frei nutzbar. Kommerzielle Nutzung (verkaufte App, Bezahldienst) nur mit schriftlicher Erlaubnis des Autors.

---
*Teil der TechFlipsi-Projektfamilie · Gebaut und gepflegt von [@TechFlipsi](https://github.com/TechFlipsi)*