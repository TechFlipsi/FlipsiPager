# 🏗️ UMBAU-PLAN: Feuerwehr-Einsatz-Monitor → Selbsthosting-Version

> **Stand:** 14.09.2026 · **Status:** Planung (Umbau noch NICHT begonnen)
> **Grundregel:** Am Original so wenig wie möglich ändern — es funktioniert. Der Umbau ist eine **Config-Schicht drüber**, kein Rewrite.

---

## 🎯 Ziel

Dritte (erfahrene Nutzer, Feuerwehren) hosten ihre **eigene Instanz** auf eigenem Pi/Server:
eigenes Telegram-Bot-Token, eigene Stamm-Feuerwehr, eigene Nützer. Unser Produktions-Bot auf dem InkyPi bleibt **unverändert weiterlaufen** — die Config-Schicht wird so gebaut, dass unsere Instanz nur eine "Config mit Offenhausen-Werten" ist.

## 📌 Was ist hart verdrahtet? (verifiziert im Code, Stand v12.2, 4652 Zeilen)

| Stelle | Zeile(n) | Problem |
|---|---|---|
| `ADMIN_ID = 7790051948` (Fallback) | 71 | Deine echte Chat-ID als Fallback im Code |
| `"username": "Fabian"` für Admin | 101 | Dein Name im Code |
| `"orte": ["Offenhausen"]` Admin-Stamm-Watch | 102, 106–107 | Unsere Feuerwehr |
| `known = {"offenhausen": "414113"}` Org-ID-Mapping | 619 | Unsere Org-ID |
| `url2 = ".../organizations/414113"` | 3527 | Hardcode-Doppel |
| Befehle `/offenhausen`, `/training` + ~20 Texte "FF Offenhausen" | 508, 518, 2752, 2762, 3043, 3449, 3534 … | 24 Stellen gesamt |
| `/unortall` schützt "Offenhausen" | 3674–3681 | Geschützte Watch |
| InkyPi-Trigger nur bei `Offenhausen`-Match | 4638–4640 | Display-Kopplung |
| `POLL_INTERVAL = 5` | 37 | Für Fremd-Instanzen zu aggressiv |
| `MAX_USERS = 2000` | 1578 | Soll konfigurierbar werden |

**Bewusst NICHT angefasst:** Datenquellen-URLs (OOELFV, GeoSphere, hydro.ooe.gv.at, netzooe.at, Lawinenwarndienst — alles OÖ, bleibt so), Voice (Piper, optional), Telegram-API-Logik, State-Handling. Alles davon funktioniert und ist instanz-unabhängig.

---

## 🧩 Umsetzungs-Prinzip: Eine einzige neue Datei statt Rewrite

**`fw_bot.conf`** (INI-Format, configparser — stdlib, keine Abhängigkeit) neben `bot_token.env`:

```ini
[feuerwehr]
name = FF Musterdorf        ; erscheint in /offenhausen, /training, Begrüßung, Menü
org_id = 000000             ; einsaetze.at-Org-ID (Auto-Findung über den bestehenden
                            ; 880-FF-Index bleibt als Fallback aktiv!)

[besitzer]
admin_id = 123456789        ; Telegram-Chat-ID des Betreibers

[bot]
poll_interval = 60          ; Default für Fremd-Instanzen (unsere: 5)
max_users = 2000            ; Kapazitäts-Limit
```

**Ladereihenfolge (Schutz vor Regression):** Fehlt die Datei oder ein Wert → exakt heutiges Verhalten (Offenhausen-Werte + Fallbacks). Unsere Produktions-Instanz braucht damit **kein Update zu brauchen, um weiterzulaufen** — sie kriegt trotzdem eine `fw_bot.conf` mit ihren Werten, damit alles explizit ist.

**Wichtig (Sir-Regel „am Original bleiben"):** Kein Umbau von Funktionen, keine Umbenennung von Befehlen. Nur die ~24 Offenhausen-Stellen + 4 Konstanten werden config-lesend. Alles andere bleibt Byte-für-Byte-identisch, soweit möglich.

### Der Einzeiler-Installationsassistent (geht das? → Ja!)

`install.sh` macht in einem Rutsch:
1. Pakete prüfen/installieren (`python3` 3.11+, systemd) — keine pip-Pakete nötig, Code nutzt nur stdlib + optional piper
2. **Interaktive Abfrage** (read-Dialog im Terminal): FF-Name → Org-ID (mit Auto-Suche über den 880-FF-Index, Tippfehler-Toleranz) → Bot-Token (direkter Link + Schritt-für-Schritt zur BotFather-Anleitung) → Admin-Chat-ID (Assistent erklärt: „Schick /start an deinen neuen Bot, die ID steht in der Antwort" — oder automatischer Abfrage-Modus: Skript pollt getUpdates und fängt die ID ab) → Poll-Intervall (Default 60) → MAX_USERS (Default 2000)
3. Schreibt `~/.config/fw_bot/bot_token.env` + `fw_bot.conf` (chmod 600)
4. Lädt die aktuelle `einsatz_watcher_v4.py` aus diesem Repo
5. systemd-Service anlegen + starten, Health-Check (Log liest „Telegram Bot aktiv")
6. Abschluss: „Schick jetzt /start an deinen Bot und registriere dich."

**Einzeiler (Vorschau fürs README):**
```bash
curl -fsSL https://raw.githubusercontent.com/TechFlipsi/feuerwehr-einsatz-monitor/main/install.sh | bash
```
(curl | bash mit klarem „Was macht das Skript?"-Hinweis im README; Alternative: git clone + ./install.sh für Misstrauische)

---

## 🗂️ Geplante Repo-Struktur

```
feuerwehr-einsatz-monitor/
├── README.md              ✅ (Coming-Soon-Fassung existiert, wird zur Anleitung)
├── LICENSE                ✅ (MIT + Non-Commercial)
├── install.sh             ⬜ Assistent (Abfrage + systemd + Health-Check)
├── einsatz_watcher_v4.py  ⬜ (Release-Kopie, ent-personalisiert)
├── fw_bot.conf.example    ⬜ Dokumentierte Beispiel-Config
├── uninstall.sh           ⬜ (Service + Dateien entfernen, Daten mit -purge)
└── docs/
    └── ANLEITUNG.md       ⬜ Schritt-für-Schritt mit Screenshots-Platzhaltern + Troubleshooting
```

## 📋 Arbeits-Reihenfolge (Schätzung: 2 Abende + 1 Test-Abend)

1. **Config-Schicht** (~1. Abend): `fw_bot.conf` laden → ersetzt die 24 Offenhausen-Stellen + `POLL_INTERVAL` + `MAX_USERS` + `ADMIN_ID-Fallback` + Admin-Name. Default-Verhalten bei fehlender Datei = heutiges Verhalten (Regressionssicherung).
2. **Test-Regression:** Beide Suiten (40 + 106) auf dem Pi gegen die konfigurierte Version — grün = nichts kaputt.
3. **Install-Assistent** (~2. Abend): `install.sh` mit Abfrage-Dialog, Token-Handling (Token-Datei NIE via write_file — scp/echo-Mechanik beachten), systemd-Unit (User=pi, Restart=always), `uninstall.sh`.
4. **Anleitung:** `docs/ANLEITUNG.md` — von Null (leeres Pi OS) bis erster Alarm, inkl. BotFather-Screenshots-Texte, Troubleshooting (Token falsch, ID falsch, Service stirbt, Org-ID nicht gefunden).
5. **Audit-Pass:** Release-Kopie greppen auf echte IDs (`7790051948`), Namen (Fabian/Kirchweger), interne Hosts (192.168.x, TrueNAS-Backups). Nur die bereinigte Kopie kommt ins Repo — **nicht** die Produktionsdatei.
6. **Test auf Jungfrau-Pi:** Install auf einem sauberen System (oder Distrobox/Container), erster `/start` + Alarm-Zyklus.
7. **Release:** `Coming Soon` raus, v1.0.0 taggen, Release-Notes.

## ⚠️ Offene Entscheidungen (Sir entscheidet beim Start)

- **Voice (Sprachalarm):** In die Fremd-Instanz-Version? (Piper-Modell ~40 MB Download, optional ja/nein im Installer) — Empfehlung: als Opt-in mit Download beim ersten `/stimme`
- **InkyPi-Display-Trigger:** Nur aktivieren wenn `INKYPI_API` in der Config steht (Fremd-Instanzen ohne Pi-Display: automatisch aus)
- **Quellen-Disclaimer:** bleibt unverändert (ist schon drin: /quellen, /datenschutz §8, /anleitung)
- **Update-Weg für Fremd-Instanzen:** `update.sh` (git pull + Restart) oder Manuell-Note im README — Empfehlung: update.sh, simple

## 🛡️ Nicht ändern (Bewusst-Liste)

- Telegram-Command-Namen, Message-Texte (außer FF-Name-String-Ersetzung via Config)
- Zwei-Stufen-Löschung, Auto-Ban, Onboarding-Flow, Buttons — alles bewährt
- 5-s-Poll **unserer** Instanz (nur der Default für neue Instanzen wird 60)
- InkyPi-Integration unserer Instanz (läuft, wird nur optionalisiert)