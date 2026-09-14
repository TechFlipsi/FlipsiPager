# ⚡ Netzbetreiber in Oberösterreich — warum nur Netz OÖ im Bot?

FlipsiPager liest die Stromausfall-Daten von der **Netz OÖ Störungskarte** (status.netzooe.at). Das deckt den größten Teil Oberösterreichs ab — aber **nicht alles**. Diese Seite erklärt transparent, warum die anderen Netzbetreiber (Stand 14.09.2026) nicht als Quelle drin sind.

## Die vier Strom-Netzbetreiber in OÖ

| Netzbetreiber | Versorgungsgebiet | Störungsdaten im Bot? |
|---|---|---|
| **Netz OÖ GmbH** (Tochter der Energie AG) | Größter Teil OÖ — u. a. Offenhausen, Wels-Land, Grieskirchen, Vöcklabruck, Bezirk Urfahr … | ✅ Ja — `/strom` + Strom-Wache |
| **LINZ NETZ GmbH** (Linz AG) | Stadt Linz + Umlandgemeinden | ❌ siehe unten |
| **eww Wels** | Stadt Wels, Thalheim bei Wels, Teile von Buchkirchen, Gunskirchen, Marchtrenk, Steinhaus | ❌ siehe unten |
| **Energie Ried GmbH** | Stadt Ried im Innkreis + 27 Umlandgemeinden im Inn-/Hausruckviertel | ❌ siehe unten |

## Warum die anderen drei nicht drin sind

Wir haben alle drei Betreiber im Detail untersucht (14.09.2026) — das Ergebnis ist ehrlich, aber unbefriedigend: **keiner der drei veröffentlicht Störungsdaten in einer maschinenlesbaren, abfragbaren Form.**

### LINZ NETZ GmbH — Seite existiert, aber nichts Abfragbares

- Es gibt eine Seite „Aktuelle Störmeldungen" (linznetz.at) — aber die Störungsliste wird **server-seitig nur gerendert, wenn gerade Meldungen aktiv sind**. Im leeren Zustand (kein Ausfall) steht nur Infotext drin.
- **Folge:** Wir könnten einen Parser bauen, aber ohne eine aktive Störung **wissen wir nicht, wie die Liste aussieht**, wenn sie gefüllt ist. Ein unbelegter Parser wäre raten — das machen wir nicht. Die Struktur kann erst verifiziert werden, wenn es einen Ausfall mit öffentlicher Liste gibt.
- Alternativen (REST-Endpunkt, JSON-Datei, JS-Backend) haben wir geprüft: keine öffentlich zugängliche API.

### eww Wels — nur ein Meldeformular

- eww bietet ein **Formular zum Melden** eines Stromausfalls (eingehend), aber **keine öffentliche Störungsliste oder Karte** (ausgehend). Für den Bot fehlt schlicht die Datenquelle — man kann keine Ausfälle anzeigen, die nirgends veröffentlicht werden.

### Energie Ried — nur Grenz-Polygon und Hotline

- Die Netzgebiet-Karte (energie-ried.at/map) zeigt ein **Grenz-Polygon als Grafik** (Google-Maps-Polygon-Koordinaten), aber **keine Störungsinformationen** — weder Liste noch Karte mit aktiven Ausfällen. Auch hier: nur Störungshotline, keine Veröffentlichung.

## Was der Bot stattdessen macht

- Beim **Hinzufügen eines Orts zur Überwachung**, der in einem Nicht-Netz-OÖ-Gebiet liegt (Stadt Linz, Stadt Wels, Thalheim, Stadt Ried), weist der Bot sofort darauf hin: **Stromdaten für diesen Ort sind nicht verfügbar**, weil der Ort zu einem anderen Netzbetreiber gehört.
- **Alle anderen Wachen (Einsätze, Unwetter, Pegel, Lawinen, Waldbrand) funktionieren für diese Orte ganz normal** — die Strom-Lücke betrifft ausschließlich den Strom-Teil.
- Orte im Netz-OÖ-Gebiet sind von all dem **nicht betroffen** und liefern weiterhin volle Bezirks- und Gemeinden-Störungsdaten.

## Würde mehr gehen?

Technisch: ja, sobald die Betreiber etwas Abfragbares veröffentlichen. Wir haben alle drei geprüft (Stand 14.09.2026) — **ohne dass die Betreiber selbst Daten veröffentlichen, gibt es keinen legalen, zuverlässigen Weg**. Aggregatoren wie Stromausfall-Karten mit nutzergemeldeten Ausfällen sind keine offizielle Quelle und für eine Alarmierung nicht seriös genug.

*Sollte einer der Betreiber eine öffentliche Störungs-API oder -Karte bereitstellen, ist der Einbau geplant — Hinweise dazu gerne als Issue oder Funktionswunsch (`/wunsch`).*
