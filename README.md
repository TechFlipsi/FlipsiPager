# FF Feuerwehr-Einsatz-Monitor 🔥🤖

> **Status: 🚧 Coming Soon** — Das Projekt wird gerade für die eigenständige Selbst-Installation vorbereitet. Noch keine Installation möglich, das Repo wird in Kürze mit Installer + Anleitung befüllt.

Ein privater Telegram-Bot, der Feuerwehr-Einsätze in **Oberösterreich** automatisch beobachtet und registrierte Benutzer sofort alarmiert — inklusive Unwetter-Warnungen, Pegel-Überwachung, Stromausfall-Wache, Lawinenlage, Sprachalarm und vielem mehr.

**Läuft komplett auf deiner eigenen Hardware** (z. B. Raspberry Pi) — keine Cloud, keine Registrierung bei Drittanbietern außer Telegram selbst.

## ✨ Funktionen (Auszug)

- 🔥 **Live-Einsatz-Alarm** für frei wählbare Orte (OOELFV, Poll alle paar Sekunden)
- ⛈️ **Amtliche Unwetter-Warnungen** (GeoSphere Austria) inklusive
- 🌊 **Hochwasser-Wache** — Pegel im Umkreis deiner Orte (Hydro OÖ)
- ⚡ **Stromausfall-Wache** — Störungskarte Netz OÖ
- ❄️ **Lawinen-Wache** — Lawinenlagebericht + Zonen-Warnung (Land OÖ)
- 🗣️ **Sprachalarm** — Alarme zusätzlich als Sprachnachricht
- 👥 **Multi-User** — offene Registrierung, pro-User Beobachtungen, Admin-Verwaltung, Auto-Ban-Schutz
- 📊 Statistiken, Wochenrückblicke, QR-Code zum Weiterschicken, Inline-Buttons mit Karte & Navigation
- 🔐 DSGVO-freundlich: Selbst-Löschung mit 2-Stufen-Bestätigung, Datenschutz-Info, Quellen-Offenlegung (`/quellen`)

Die vollständige Befehlsliste gibt's nach dem Release in der Anleitung.

## 📋 Geplanter Ablauf nach Release

1. Raspberry Pi (oder jeder Linux-Rechner) mit Python 3.11+ vorbereiten
2. Eigenen Bot bei [@BotFather](https://t.me/BotFather) anlegen → Token eintragen
3. `install.sh` ausführen — legt systemd-Service + Ordnerstruktur an
4. Feuerwehr-Heimatort + Admin-Konto in der `fw_bot.conf` setzen
5. Fertig — deine Familie/Kameraden registrieren sich im eigenen Bot-Chat

## ⚙️ Konfiguration (Vorschau)

Alle heimat-spezifischen Werte wandern in eine Config-Datei — keine Code-Änderungen nötig:

```ini
[feuerwehr]
name = FF Musterdorf        # deine Feuerwehr (Befehle, Historie, geschützte Watch)
org_id = 000000             # einsaetze.at-Org-ID deiner Wehr
admin_id = 123456789        # deine Telegram-Chat-ID

[bot]
poll_interval = 60          # Sekunden — Respekt vor der Datenquelle (5–86400, einstellbar)
```

## ⚠️ Rechtliches / Verlässlichkeit

- Privates, **inoffizielles** Projekt — keine offizielle Alarmierung! Sirene, Funk, Pager und **Notruf 122** gehen immer vor.
- Liest ausschließlich öffentlich zugängliche Quellen (OOELFV, einsaetze.at, GeoSphere Austria, Hydro OÖ, Netz OÖ, Lawinenwarndienst OÖ, OpenStreetMap). Details im Bot via `/quellen`.
- Jeder Instanz-Betreiber ist selbst verantwortlich für den Betrieb seiner Instanz (DSGVO, Umgang mit den Daten seiner Benutzer).
- **OÖ-Fokus:** Die Datenquellen sind oberösterreichisch. Andere Bundesländer sind nicht abgedeckt.

## 📜 Lizenz

[MIT mit Non-Commercial-Einschränkung](LICENSE) — privat, für Bildungszwecke und Feuerwehren (intern, gemeinnützig) frei nutzbar. Kommerzielle Nutzung (verkaufte App, Bezahldienst) nur mit schriftlicher Erlaubnis.

Der Bot ist **kein offizielles Produkt** des Oö. Landes-Feuerwehrverbandes oder der genannten Datenquellen und steht in keiner Verbindung zu ihnen.

---
*Teil der TechFlipsi-Projektfamilie. Gebaut und gepflegt von [@TechFlipsi](https://github.com/TechFlipsi).*