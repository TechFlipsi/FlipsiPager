# 🔥 FF Feuerwehr-Einsatz-Monitor

Ein **selbst hostbarer** Telegram-Bot für Feuerwehr-Einsätze in **Oberösterreich** — auf deiner eigenen Hardware. Alarm bei Einsätzen an deinen beobachteten Orten, inklusive Unwetter-Warnungen, Pegel-Überwachung, Stromausfall-Wache, Lawinenlage, Sprachalarm und vielem mehr.

Keine Cloud, kein Abo, keine Registrierung außer Telegram selbst — **deine Daten bleiben auf deinem Gerät.**

## ⚡ Schnellstart (10 Minuten)

Bot bei [@BotFather](https://t.me/BotFather) anlegen, dann auf deinem Pi/Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main/install.sh | bash
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

## ⚠️ Rechtliches & Verlässlichkeit

- Privates, **inoffizielles** Projekt — **keine offizielle Alarmierung!** Sirene, Funk, Pager und **Notruf 122** gehen immer vor.
- Liest ausschließlich öffentlich zugängliche Quellen. **OÖ-Fokus** — andere Regionen werden nicht abgedeckt.
- **Du bist Betreiber deiner Instanz** und verantwortlich für den Umgang mit den Daten deiner Benutzer (DSGVO). Der Bot liefert die Werkzeuge (Datenschutz-Info, Selbstlöschung, Auskunft) mit.
- Kein offizielles Produkt des Oö. Landes-Feuerwehrverbandes oder der genannten Quellen.

## 📜 Lizenz

[MIT mit Non-Commercial-Einschränkung](LICENSE) — privat, für Bildungszwecke und Feuerwehren (intern, gemeinnützig) frei nutzbar. Kommerzielle Nutzung (verkaufte App, Bezahldienst) nur mit schriftlicher Erlaubnis des Autors.

---
*Teil der TechFlipsi-Projektfamilie · Gebaut und gepflegt von [@TechFlipsi](https://github.com/TechFlipsi)*