# 📚 Datenquellen — Offenlegung

FlipsiPager arbeitet ausschließlich mit **öffentlich zugänglichen Quellen**. Hier findest du alle, mit URL und Lizenz-Nutzung — nachvollziehbar für jeden Nützer, jederzeit abrufbar im Bot selbst über `/quellen`.

## 1. OOELFV — Landesfeuerwehrverband OÖ (Einsätze)

- **URL:** https://einsaetze.ooelfv.at
- **Inhalt:** Aktuelle Einsätze + Tagesübersicht, Bezirkslisten, Einsatzdetails (Stichwort, Ort, Feuerwehren)
- **Nutzung:** Öffentlich zugängliche Alarmierungs-Seite des LFV OÖ. Andere Dienste (z. B. SmartPager, ff.ampits.at) nutzen dieselben Daten ebenfalls. Automatisierter Abruf im Sekundenbereich wie bei einem Meldedienst — respektvoll im 60-Sekunden-Takt (einstellbar).

## 2. einsaetze.at (Einsatz-Historie + Übungen)

- **URL:** https://www.einsaetze.at
- **Nutzung:** 12-Monats-Statistiken und Übungs-Historie pro Feuerwehr (`/training`, `/rueckblick`, `/statistik`). Öffentlich einsehbare Daten; der 880-Feuerwehren-Index in `data/` wurde einmalig aus der öffentlichen Sitemap gebaut.

## 3. GeoSphere Austria — Unwetter-Warnungen

- **URL:** https://warnungen.geosphere.at (WarnAPI)
- **Lizenz:** **CC0** (public domain, offizielle ZAMG-Nachfolgerin) — freie Nutzung explizit vorgesehen
- **Nutzung:** Aktive Unwetter-Warnungen pro Bezirk (`/warnungen`, Unwetter-Alarm)

## 4. Hydrografischer Dienst OÖ — Pegel

- **URL:** https://hydro.ooe.gv.at
- **Lizenz:** **CC BY 3.0 AT** (Open Government Data Land OÖ) — Nutzung mit Quellenangabe
- **Nutzung:** Fluss-Pegelstände + Alarmstufen (`/pegel`, Hochwasser-Watch)

## 5. Netz OÖ — Stromausfälle

- **URL:** https://www.netzooe.at / https://status.netzooe.at
- **Nutzung:** Gesetzlich vorgeschriebene Störungsveröffentlichung (robots.txt erlaubt Abruf explizit)
- **Nutzung im Bot:** Stromausfall-Übersicht pro Bezirk (`/strom`, Stromausfall-Watch)
- **⚠️ Wichtige Einschränkung:** Die Daten decken **nur das Versorgungsgebiet der Netz OÖ GmbH** ab. In OÖ gibt es weitere Netzbetreiber mit eigenen Gebieten — **LINZ NETZ GmbH** (Linz AG: Stadt Linz + Umgebung), **eww Wels** (Stadt Wels, Thalheim, Teile von Buchkirchen, Gunskirchen, Marchtrenk, Steinhaus) und **Energie Ried** (Stadt Ried + 27 Umlandgemeinden). Orte in diesen Gebieten bekommen **keine Strom-Störungsdaten** (keiner dieser Betreiber veröffentlicht abfragbare Störungsdaten — Details und Begründung: [docs/NETZBETREIBER.md](NETZBETREIBER.md)). Der Bot weist beim Hinzufügen solcher Orte aktiv darauf hin.

## 6. Lawinenwarndienst OÖ

- **URL:** https://www.lawinenwarndienst-ooe.at
- **Nutzung:** Aktuelle Lawinen-Gefahrenstufen (CAAML-Format, öffentlich)
- **Nutzung im Bot:** Lawinen-Warnstufen (`/lawine`, Lawinen-Watch)

## 7. OpenStreetMap — Nominatim (Orts-Suche)

- **URL:** https://www.openstreetmap.org / https://nominatim.openstreetmap.org
- **Lizenz:** **ODbL** (Open Database License)
- **Nutzung:** Umkreissuche („Welche Orte liegen 5 km um X?") (`/umkreis`) — mit ordentlichem User-Agent inkl. Projekt-Verweis

---

## ⚖️ Wichtig zu wissen

- **Kein offizielles Produkt:** FlipsiPager ist **inoffiziell** und steht in keiner Verbindung zum LFV OÖ, dem Land OÖ oder einer der genannten Quellen.
- **Keine Alarmquelle für den Ernstfall:** Der Bot kann ausfallen (Server-Problem, Datenquellen offline, Parsing-Fehler). Verlass dich NICHT zu 100 % darauf — im Ernstfall zählt deine offizielle Alarmierung (Funkmeldeempfänger, App der Wehr).
- **Notruf:** Im Notfall immer **122** (Feuerwehr). Der Bot ersetzt keinen Notruf.
- Die Daten gehören den jeweiligen Eigentümern; Lizenz-Einhalte (CC0, CC BY, ODbL) werden respektiert und mit Quellenangabe genutzt.

*Hinweis: Diese Datei beschreibt die Standard-Datenquellen der OÖ-Quellen-Auswahl. Wer den Bot selbst hostet und die Quellen-URLs ändert, muss selbst prüfen, welche Regeln dort gelten (robots.txt, Nutzungsbedingungen).*