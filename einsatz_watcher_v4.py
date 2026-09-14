#!/usr/bin/env python3
"""Feuerwehr-Einsatzmonitor v6 — Deutsche Befehle (Telegram erlaubt keine Umlaute im Befehl), Selbst-Löschung /vergessen, DSGVO-Transparenz"""
import re, json, os, logging, time, sys, subprocess
try:
    from pyproj import Transformer as _PegelTransformer
except ImportError:
    _PegelTransformer = None
import urllib.request, urllib.parse
from datetime import datetime, timedelta, date
from html import unescape, escape

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

def esc(text):
    """Escapt User-Input für sichere Telegram HTML-Anzeige."""
    if not text:
        return ""
    return escape(str(text))

def strip_tags(text):
    """Entfernt HTML-Tags aber behält den Textinhalt (für Alarmstufe etc.)."""
    if not text:
        return ""
    # <font...>INHALT</font> -> INHALT, <a title="X">❸</a> -> ❸ (innerer Text)
    # <a> Tags mit title-Attribut: behalte den inneren Text (z.B. Alarmstufe-Symbol ❸)
    text = re.sub(r'<a[^>]*title="[^"]*"[^>]*>([^<]*)</a>', r'\1', text)
    # Alle übrigen Tags entfernen
    text = re.sub(r'<[^>]+>', '', text)
    return unescape(text).strip()

# ═══ Config ═══
def _lade_fw_config():
    """Liest fw_bot.conf (INI) — fehlt sie oder ein Wert, gilt das Default-Verhalten.

    Keys: [feuerwehr] name/org_id, [besitzer] admin_id, [bot] poll_interval/max_users/inkypi_api.
    Die Admin-Stamm-Watch (dauerhaft aktiv) trägt den FF-Namen."""
    cfg = {
        "ff_name": "Offenhausen",       # Stamm-Feuerwehr der Instanz (Default = Original)
        "org_id": "",                   # einsaetze.at-Org-ID (leer = Auto-Findung über FF-Index)
        "admin_id_fallback": None,  # ohne fw_bot.conf Pflicht: in bot_token.env (FW_BOT_CHAT_ID) setzen
        "admin_username": "Admin",
        "poll_interval": 5,
        "max_users": 2000,
        "inkypi_api": "http://127.0.0.1:80/display_plugin_instance",
        "inkypi_playlist": "Bilder",
        "inkypi_instance": "Feuerwehr",
    }
    try:
        conf_path = os.path.expanduser("~/.config/fw_bot/fw_bot.conf")
        if os.path.exists(conf_path):
            import configparser
            cp = configparser.ConfigParser()
            cp.read(conf_path, encoding="utf-8")
            if cp.has_option("feuerwehr", "name"):
                cfg["ff_name"] = cp.get("feuerwehr", "name").strip() or cfg["ff_name"]
            if cp.has_option("feuerwehr", "org_id"):
                cfg["org_id"] = cp.get("feuerwehr", "org_id").strip() or cfg["org_id"]
            if cp.has_option("besitzer", "admin_id"):
                v = cp.get("besitzer", "admin_id").strip()
                if v.isdigit():
                    cfg["admin_id_fallback"] = int(v)
            if cp.has_option("besitzer", "admin_username"):
                cfg["admin_username"] = cp.get("besitzer", "admin_username").strip() or cfg["admin_username"]
            if cp.has_option("bot", "poll_interval"):
                try:
                    v = int(cp.get("bot", "poll_interval").strip())
                    if 5 <= v <= 86400:
                        cfg["poll_interval"] = v
                except (ValueError, TypeError):
                    pass
            if cp.has_option("bot", "max_users"):
                try:
                    v = int(cp.get("bot", "max_users").strip())
                    if v > 0:
                        cfg["max_users"] = v
                except (ValueError, TypeError):
                    pass
            if cp.has_option("bot", "inkypi_api"):
                cfg["inkypi_api"] = cp.get("bot", "inkypi_api").strip()
            if cp.has_option("bot", "inkypi_playlist"):
                cfg["inkypi_playlist"] = cp.get("bot", "inkypi_playlist").strip() or cfg["inkypi_playlist"]
            if cp.has_option("bot", "inkypi_instance"):
                cfg["inkypi_instance"] = cp.get("bot", "inkypi_instance").strip() or cfg["inkypi_instance"]
            logger.info(f"fw_bot.conf geladen: FF {cfg['ff_name']} (Org {cfg['org_id']}), Poll {cfg['poll_interval']}s, Max-User {cfg['max_users']}")
        else:
            logger.info("fw_bot.conf nicht vorhanden — Standard-Werte aktiv (Original-Verhalten)")
    except Exception as e:
        logger.warning(f"fw_bot.conf nicht lesbar ({e}) — Standard-Werte aktiv")
    return cfg

_FW_CFG = _lade_fw_config()
FF_NAME = _FW_CFG["ff_name"]
FF_ORG_ID = _FW_CFG["org_id"]
ADMIN_ID_FALLBACK = _FW_CFG["admin_id_fallback"]
ADMIN_USERNAME_DEFAULT = _FW_CFG["admin_username"]
POLL_INTERVAL = _FW_CFG["poll_interval"]
MAX_USERS = _FW_CFG["max_users"]
INKYPI_ENABLED = bool(_FW_CFG["inkypi_api"].strip())
INKYPI_API = _FW_CFG["inkypi_api"].strip() if _FW_CFG["inkypi_api"].strip() else None
INKYPI_PLUGIN_DATA = {"playlist_name": _FW_CFG["inkypi_playlist"], "plugin_id": "screenshot", "plugin_instance": _FW_CFG["inkypi_instance"]}

SOURCE_URL = "https://einsaetze.ooelfv.at/einsatz/aktuell"
SOURCE_URL_TAG = "https://einsaetze.ooelfv.at/einsatz/tag"
BOT_TOKEN_FILE = os.path.expanduser("~/.config/fw_bot/bot_token.env")
USERS_FILE = os.path.expanduser("~/.config/fw_bot/users.json")
BLACKLIST_FILE = os.path.expanduser("~/.config/fw_bot/blacklist.json")
STATE_DIR = os.path.expanduser("~/.config/fw_bot/state")
# Snapshot für Lösch-Wächter: Admin wird informiert, wenn ein bekannter User aus
# users.json verschwindet (gleich ob /vergessen, Admin-Entfernung oder externer Edit).
USER_SNAPSHOT_FILE = os.path.expanduser("~/.config/fw_bot/user_snapshot.json")
os.makedirs(STATE_DIR, exist_ok=True)
OFFSET_FILE = os.path.join(STATE_DIR, "bot_offset.txt")

FARBEN = {"red":"\U0001f534 Brand","blue":"\U0001f535 Technisch","yellow":"\U0001f7e1 Personenrettung","green":"\U0001f7e2 Sonstige","black":"\u26ab Gro\u00dfeinsatz","orange":"\U0001f7e0 Unwetter"}
MAX_ORTS_PER_USER = 10        # max. dauerhafte Orts-Beobachtungen pro User
MAX_EINSATZ_WATCHES_PER_USER = 10  # max. temporäre Einsatz-Beobachtungen pro User
MAX_WATCHES_PER_USER = 20     # Gesamtobergrenze (orte + einsatz_watches) — Spam-Schutz
WATCH_LIMIT_BAN_HOURS = 12  # Auto-Bann-Dauer bei wiederholtem Limit-Missbrauch
WATCH_LIMIT_BAN_AFTER = 3   # Anzahl Limit-Warnungen bis zum Auto-Ban
# ═══ Token laden ═══
BOT_TOKEN = None
ADMIN_ID = None
try:
    with open(BOT_TOKEN_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("FW_BOT_TOKEN="):
                BOT_TOKEN = line.split("=", 1)[1]
            elif line.startswith("FW_BOT_CHAT_ID="):
                ADMIN_ID = int(line.split("=", 1)[1])
except Exception as e:
    logger.error(f"Bot-Token-Datei nicht ladbar: {e}")

if not ADMIN_ID and ADMIN_ID_FALLBACK:
    ADMIN_ID = ADMIN_ID_FALLBACK

# ═══ User Management ═══
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"users": {}}

def save_users(data):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Users speichern fehlgeschlagen: {e}")

def init_users():
    data = load_users()
    admin_str = str(ADMIN_ID) if ADMIN_ID else None
    # Migration: watches → orte + einsatz_watches
    for uid, ud in data["users"].items():
        if "watches" in ud and "orte" not in ud:
            ud["orte"] = ud.pop("watches")
        if "einsatz_watches" not in ud:
            ud["einsatz_watches"] = []
    if not admin_str or admin_str == "None":
        return data  # keine Admin-ID konfiguriert — kein Auto-Admin
    if admin_str not in data["users"]:
        data["users"][admin_str] = {
            "username": ADMIN_USERNAME_DEFAULT, "is_admin": True,
            "orte": [FF_NAME], "einsatz_watches": [], "registered": True,
            "added_at": datetime.now().isoformat()
        }
        save_users(data)
    else:
        admin_orte = data["users"][admin_str].setdefault("orte", [])
        # Wechsel der Stamm-Feuerwehr: der alte Default-Watch 'Offenhausen' ist ein
        # Konfigurations-Rest, kein bewusst gesetzter Beobachtungswunsch — er weicht.
        if admin_orte == ["Offenhausen"] and FF_NAME != "Offenhausen":
            admin_orte = [FF_NAME]
        elif FF_NAME not in admin_orte:
            admin_orte.append(FF_NAME)
        data["users"][admin_str]["orte"] = admin_orte
        save_users(data)
    # Admin-Rechte + Registrierung immer wiederherstellen (falls durch Auto-Bann entfernt)
    admin_modified = False
    if not data["users"][admin_str].get("is_admin"):
        data["users"][admin_str]["is_admin"] = True
        admin_modified = True
    if not data["users"][admin_str].get("registered"):
        data["users"][admin_str]["registered"] = True
        admin_modified = True
    # Ban aufheben falls vorhanden (Admin darf nie gebannt bleiben)
    if data["users"][admin_str].get("ban_until"):
        data["users"][admin_str]["ban_until"] = None
        admin_modified = True
    if admin_modified:
        save_users(data)
    return data

users = init_users()

# ═══ Admin-Blacklist (präventives Bannen, auch ohne users.json-Eintrag) ═══
# blacklist.json Format: {"ids": {"<chat_id>": null|ISO-Datetime}}
# null = dauerhaft, ISO-Datetime = temporärer Bann bis zu diesem Zeitpunkt.

def load_blacklist():
    try:
        with open(BLACKLIST_FILE, "r") as f:
            bl = json.load(f)
        if not isinstance(bl, dict):
            return {"ids": {}}
        bl.setdefault("ids", {})
        return bl
    except FileNotFoundError:
        return {"ids": {}}
    except Exception as e:
        logger.warning(f"Blacklist-Lesefehler: {e}")
        return {"ids": {}}

def save_blacklist(bl):
    try:
        with open(BLACKLIST_FILE, "w") as f:
            json.dump(bl, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Blacklist-Schreibfehler: {e}")

def blocked_reason(cid_str):
    """Grund-String wenn ID gebannt (Blacklist o. Auto-Ban), sonst None.
    Abgelaufene temporäre Blacklist-Einträge werden lazy entfernt."""
    bl = load_blacklist()
    entry = bl.get("ids", {}).get(cid_str)
    if entry is not None or cid_str in bl.get("ids", {}):
        if entry is None:
            return "Blacklist (dauerhaft)"
        try:
            if datetime.now() < datetime.fromisoformat(entry):
                return f"Blacklist (bis {entry[:16].replace('T', ' ')})"
            # Abgelaufen → lazy entfernen
            bl["ids"].pop(cid_str, None)
            save_blacklist(bl)
        except Exception:
            pass
    # Auto-Ban aus users.json (3x Admin-Remove-Versuch)
    if cid_str in users["users"]:
        bu = users["users"][cid_str].get("ban_until")
        if bu:
            try:
                if datetime.now() < datetime.fromisoformat(bu):
                    return "Auto-Bann (24h)"
            except Exception:
                pass
    return None

def register_limit_violation(cid_str, chat_id, limit_name="Beobachtungs-Limit"):
    """Zählt verweigerte /ort-/einsatz-Versuche über dem Watch-Limit.
    Ab WATCH_LIMIT_BAN_AFTER Verstößen: automatischer 12h-Bann (Auto-Ban).
    Der Bann läuft über blocked_reason -> blacklist.json mit Ablaufzeit, d.h.
    nach 12 Stunden ist der User zu 100% automatisch wieder komplett freigeschaltet
    (lazy-Entfernung beim nächsten Kontakt) — kein Admin-Eingriff nötig."""
    ud = users["users"].setdefault(cid_str, {})
    count = int(ud.get("limit_warnings", 0)) + 1
    ud["limit_warnings"] = count
    if count >= WATCH_LIMIT_BAN_AFTER:
        until = (datetime.now() + timedelta(hours=WATCH_LIMIT_BAN_HOURS)).isoformat()
        bl = load_blacklist()
        bl["ids"][cid_str] = until
        save_blacklist(bl)
        ud["limit_warnings"] = 0  # Zähler reset — nach Ablauf wieder 3 Versuche
        save_users(users)
        logger.warning(f"AUTO-BANN (Limit-Spam): User {cid_str} nach {count}x Limit-Missbrauch für {WATCH_LIMIT_BAN_HOURS}h gebannt.")
        send_to(chat_id, (
            f"\U0001f6ab <b>AUTOMATISCHER BANN ({WATCH_LIMIT_BAN_HOURS} Stunden)</b>\n"
            f"Du hast {count}x versucht, das Limit zu überschreiten ({limit_name}).\n\n"
            f"Deine Beobachtungen bleiben unverändert erhalten.\n"
            f"Nach {WATCH_LIMIT_BAN_HOURS} Stunden wirst du AUTOMATISCH wieder freigeschaltet."))
        return True
    save_users(users)
    rest = WATCH_LIMIT_BAN_AFTER - count
    send_to(chat_id, (
        f"\u26a0\ufe0f Warnung {count}/{WATCH_LIMIT_BAN_AFTER}: Limit erreicht — {limit_name}.\n"
        f"Noch {rest} Versuch(e), dann wirst du für {WATCH_LIMIT_BAN_HOURS} Stunden automatisch gebannt.\n"
        f"Entferne Beobachtungen mit /unort oder /uneinsatz."))
    return False

# ═══ Tag-Page Cache (pro Cycle) ═══
_tag_cache = [None]
def get_tag_html():
    if _tag_cache[0] is None:
        try:
            _tag_cache[0] = fetch_ooelfv(SOURCE_URL_TAG)
        except Exception:
            _tag_cache[0] = ""
    return _tag_cache[0]

# ═══ Telegram Send ═══
TG_TEXT_LIMIT = 4096

def split_telegram_text(text, limit=4000):
    """Teilt einen Text an Absatzgrenzen (\\n\\n) in Telegram-taugliche
    Stücke (API-Limit 4096, Sicherheitsgrenze 4000). HTML-Tags sind pro
    Absatz balanciert, daher bleiben <b>-Formatierungen beim Splitten intakt."""
    text = str(text or "")
    if len(text) <= limit:
        return [text]
    teile = []
    rest = text
    while len(rest) > limit:
        schnitt = rest.rfind("\n\n", 0, limit)
        if schnitt < 200:
            # Kein sinnvoller Absatz-Schnitt -> Hart-Schnitt, aber nie mitten im Tag
            schnitt = limit
            letzte_auf = rest.rfind("<", 0, schnitt)
            letzte_zu = rest.rfind(">", 0, schnitt)
            if letzte_auf > letzte_zu:
                schnitt = letzte_auf
        teile.append(rest[:schnitt])
        rest = rest[schnitt:].lstrip("\n")
    if rest:
        teile.append(rest)
    return teile

def send_to(target_id, text, reply_markup=None):
    if not BOT_TOKEN:
        return False
    # Telegram-Limit: Texte >4096 werden an Absatzgrenzen geteilt und als
    # Fortsetzungs-Teile gesendet (gab sonst stille API-Ablehnung + Retry-Loop).
    teile = split_telegram_text(text)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    ok_gesamt = True
    for i, teil in enumerate(teile):
        payload = {"chat_id": target_id, "text": teil, "parse_mode": "HTML"}
        if reply_markup and i == 0:
            try:
                payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            except Exception:
                pass
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(url, data=data)
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logger.error(f"Telegram-Send Fehler (ID {target_id}, Teil {i+1}/{len(teile)}): {e}")
            ok_gesamt = False
    return ok_gesamt

# ═══ Inline-Buttons: Karte + Beobachten ═══
def karten_url(ort):
    """Google-Maps-URL für einen Ortsnamen (Einsatzort-Ansicht)."""
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(str(ort or "Oberösterreich").strip())

def navigations_url(ort):
    """Direkte Navigations-URL: Google Maps Directions-Mode — startet sofort die Route."""
    return "https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote_plus(str(ort or "").strip()) + "&travelmode=driving"

def btn_navi_url(ort):
    """URL-Button '🧭 Navigation' — startet direkt die Routenführung."""
    return {"text": "\U0001f9ed Navigation", "url": navigations_url(ort)}

def btn_karte_url(ort):
    """URL-Button '📍 <Ort>' — öffnet Google Maps, kein callback nötig."""
    label = "📍 " + str(ort or "").strip()
    if len(label.encode("utf-8")) > 60:
        label = label[:56] + "…"
    return {"text": esc(label), "url": karten_url(ort)}

def _cb_safe(prefix, ort):
    """callback_data (max 64 Byte UTF-8) oder None wenn zu lang."""
    try:
        cb = (prefix + str(ort or "")).encode("utf-8")
        if len(cb) > 64:
            return None
        return cb.decode("utf-8")
    except Exception:
        return None

def btn_beobachten(ort, dauerhaft=False):
    """Callback-Button '⏱️ Beobachten' — legt temporäre (ae:) oder dauerhafte (ao:)
    Beobachtung per Klick an. None wenn der Ortsname zu lang für callback_data ist."""
    cb = _cb_safe("ae:" if not dauerhaft else "ao:", ort)
    if cb is None:
        return None
    return {"text": "⏱️ Beobachten", "callback_data": cb}

def zeilen_keyboard(zeilen):
    """Aus Liste von (Ort, karte_nur_fallback) Inline-Keyboards bauen — eine Reihe pro Einsatz."""
    rows = []
    for ort in zeilen:
        r = []
        bb = btn_beobachten(ort)
        if bb:
            r.append(bb)
        r.append(btn_karte_url(ort))
        r.append(btn_navi_url(ort))
        rows.append(r)
    return {"inline_keyboard": rows} if rows else None

def _answer_cb(cbid, text):
    """answerCallbackQuery — kleines Popup als Button-Klick-Bestätigung."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        data = urllib.parse.urlencode({"callback_query_id": cbid, "text": text[:190], "show_alert": "false"}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass

# ═══ Orts-Index (einsaetze.at) + Vorschläge bei Tippfehlern ═══
ORT_INDEX_FILE = os.path.join(os.path.dirname(USERS_FILE), "einsaetze_at_index.json")
_ort_index_cache = None

def _lade_ort_index():
    global _ort_index_cache
    if _ort_index_cache is not None:
        return _ort_index_cache
    _ort_index_cache = {}
    try:
        with open(ORT_INDEX_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            _ort_index_cache = {str(k).lower(): str(v) for k, v in d.items()}
    except Exception:
        pass
    return _ort_index_cache

def _norm_q(s):
    return (str(s or "").lower()
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))

def _ort_vorschlaege(eingabe, max_n=3):
    """Ähnlich geschriebene Orte aus dem einsaetze.at-Index (Levenshtein + Anfänger/Substring)."""
    idx = _lade_ort_index()
    if not idx:
        return []
    q = _norm_q(eingabe)
    if not q:
        return []
    def lev(a, b):
        if a == b:
            return 0
        la, lb = len(a), len(b)
        if la == 0 or lb == 0:
            return max(la, lb)
        prev = list(range(lb + 1))
        for i in range(1, la + 1):
            cur = [i] + [0] * lb
            for j in range(1, lb + 1):
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            prev = cur
        return prev[lb]
    bewertet = []
    for name in idx.keys():
        n = _norm_q(name)
        if n == q:
            return [name]  # exakter Index-Treffer (ggf. andere Schreibweise)
        d = lev(n, q)
        if d <= 3 or q in n or (len(q) >= 4 and q[:4] == n[:4]):
            bewertet.append((d, len(name), name))
    bewertet.sort()
    return [name for _, _, name in bewertet[:max_n]]

# ═══ Parser-Canary: meldet Admin wenn OOELFV dauerhaft keine Daten liefert ═══
PARSER_FAIL_STREAK = 60  # ~5-10 Min ohne auswertbare Daten → einmalige Admin-Warnung
_canary_streak = 0
_canary_gemeldet = False

def _parser_canary(html, einsaetze):
    """Leere Einsatzliste allein ist NORMAL (nachts) — gewertet wird nur, wenn
    die Meta-Summenzeile der Seite fehlt ODER Abrufe wiederholt fehlschlagen.
    Struktureller Seiten-Umbau (siehe einsaetze.at 08/2026) wird so sichtbar,
    statt dass der Bot wochenlang 'glücklich' nichts meldet."""
    global _canary_streak, _canary_gemeldet
    meta_ok = bool(re.search(r"Einsätze:\s*\d+,\s*Feuerwehren:\s*\d+", html or ""))
    if meta_ok or einsaetze:
        _canary_streak = 0
        _canary_gemeldet = False
        return
    _canary_streak += 1
    if _canary_streak >= PARSER_FAIL_STREAK and not _canary_gemeldet:
        _canary_gemeldet = True
        logger.error(f"PARSER-CANARY: {PARSER_FAIL_STREAK}x keine auswertbaren OOELFV-Daten — Seiten-Umbau verdächtig!")
        try:
            send_to(ADMIN_ID, (
                "\U0001f9ed <b>Parser-Check fehlgeschlagen</b>\n"
                f"Die OOELFV-Quelle liefert seit {PARSER_FAIL_STREAK} Abfragen keine auswertbaren Daten.\n"
                "Möglicher Seiten-Umbau → Neueinsätze/Alarme könnten unentdeckt bleiben.\n"
                f"Stand: {datetime.now().strftime('%d.%m. %H:%M')}"))
        except Exception:
            pass

def handle_callback(cq):
    """callback_query-Verarbeitung für ⏱️-Buttons: ae: = temporäre Einsatz-Beobachtung
    anlegen, ao: = dauerhafte Orts-Beobachtung anlegen. Register/Blacklist/Limits
    identisch zu /einsatz und /ort."""
    cbid = cq.get("id")
    from_id = cq.get("from", {}).get("id")
    data = cq.get("data", "") or ""
    try:
        if not (data.startswith("ae:") or data.startswith("ao:")):
            _answer_cb(cbid, "Unbekannter Button.")
            return
        ort = data[3:].strip()[:100]
        if not ort:
            _answer_cb(cbid, "Leerer Button-Datenwert.")
            return
        cid_str = str(from_id)
        if blocked_reason(cid_str):
            _answer_cb(cbid, "Kein Zugriff.")
            return
        ud = users["users"].get(cid_str)
        if not ud or not ud.get("registered"):
            _answer_cb(cbid, "Bitte zuerst /registrieren <Name> ausführen.")
            return
        dauerhaft = data.startswith("ao:")
        if dauerhaft:
            orte_cb = ud.get("orte", [])
            if ort.lower() in [w.lower() for w in orte_cb]:
                _answer_cb(cbid, f"'{ort}' wird bereits dauerhaft beobachtet.")
                return
            if len(orte_cb) >= MAX_ORTS_PER_USER or len(orte_cb) + len(ud.get("einsatz_watches", [])) >= MAX_WATCHES_PER_USER:
                register_limit_violation(cid_str, from_id, "Orts-Limit (max. 10)")
                _answer_cb(cbid, f"Orts-Limit erreicht (max. {MAX_ORTS_PER_USER}).")
                return
            orte_cb.append(ort)
            ud["orte"] = orte_cb
            save_users(users)
            logger.info(f"Callback-Ort hinzugefügt: {ort} von User {from_id}")
            _answer_cb(cbid, f"⭐ {ort} wird jetzt dauerhaft beobachtet.")
            hinweis = _strom_fremd_hinweis(ort)
            if hinweis:
                try:
                    send_to(from_id, hinweis)
                except Exception:
                    pass
        else:
            einkl = ud.get("einsatz_watches", [])
            if ort.lower() in [w.lower() for w in einkl]:
                _answer_cb(cbid, f"'{ort}' wird bereits beobachtet.")
                return
            if len(einkl) >= MAX_EINSATZ_WATCHES_PER_USER or len(ud.get("orte", [])) + len(einkl) >= MAX_WATCHES_PER_USER:
                register_limit_violation(cid_str, from_id, "Einsatz-Limit (max. 10)")
                _answer_cb(cbid, f"Einsatz-Beobachtungs-Limit erreicht (max. {MAX_EINSATZ_WATCHES_PER_USER}).")
                return
            # Nur anlegen, wenn der Einsatz noch läuft (keine toten Temp-Watches)
            laeuft = None
            beendet_info = None  # Einsatz-Objekt vom Tag-Abruf (für Abschlussbericht-Ersatz)
            try:
                einsatzliste_cb = parse_einsaetze_full(fetch_ooelfv(SOURCE_URL)) or []
                ort_lower = ort.lower()
                laeuft = False  # Abruf erfolgreich → standard: läuft NICHT, bis Treffer gefunden
                for e in einsatzliste_cb:
                    if ort_lower in e.get("ort", "").lower():
                        laeuft = True
                        break
                if not laeuft:
                    # Einsatz auf der aktuell-Liste schon abgeräumt? Tag-Liste prüfen:
                    # Steht er dort mit Endzeit, ist er BEENDET — dann bekommt der User
                    # direkt den Abschlussbericht als Ersatz (statt nur dem Toast).
                    tag_e_cb = parse_einsaetze_full(get_tag_html()) or []
                    for te in tag_e_cb:
                        if ort_lower in te.get("ort", "").lower():
                            beendet_info = te
                            break
            except Exception:
                laeuft = None  # Abruf-Fehler: nicht blockieren (Alarm-Logik mehrtägig greift weiter)
            if laeuft is False:
                _answer_cb(cbid, f"Einsatz in {ort} läuft nicht mehr — Info unten.")
                # In-Chat-Abschlussbericht als Ersatz (der Button versprach Meldungen,
                # die kommen aber nie mehr — der Einsatz ist längst fertig):
                if beendet_info:
                    te = beendet_info
                    end_fw = te.get("feuerwehren", [])
                    endzeiten = [fw["end"] for fw in end_fw if fw.get("end")]
                    end_zeit = endzeiten[-1] if endzeiten else None
                    fw0 = end_fw[0] if end_fw else {}
                    start = fw0.get("start", "?")
                    msg_beendet = (
                        f"ℹ️ <b>Einsatz in {esc(ort)} wurde bereits beendet</b> — "
                        "die Beobachtung wurde daher nicht angelegt.\n\n"
                        f"✅ <b>EINSATZ BEENDET</b>\n"
                        f"📋 {esc(te.get('typ', ''))} {esc(te.get('stichwort', ''))}\n"
                        f"📍 {esc(te.get('ort', '?'))} ({esc(te.get('bezirk', '?'))})\n"
                        f"⏱️ Dauer: {calc_dauer(fw0.get('start', '?'), end_zeit)}\n"
                        f"👥 {len(end_fw)} Feuerwehr(en):")
                    for fw in end_fw:
                        z = f"\n  • {esc(fw['name'])}: "
                        if fw.get("end"):
                            z += f"{fw['start'].split()[-1]}–{fw['end'].split()[-1]} ({calc_dauer(fw['start'], fw['end'])})"
                        elif end_zeit:
                            z += f"{fw['start'].split()[-1]}–{end_zeit.split()[-1]} ({calc_dauer(fw['start'], end_zeit)})"
                        else:
                            z += f"{fw['start'].split()[-1]}"
                        msg_beendet += z
                    try:
                        send_to(from_id, msg_beendet)
                    except Exception:
                        pass
                else:
                    # Nicht mal auf der Tag-Seite (älter/heute nicht gefunden):
                    try:
                        send_to(from_id, ("ℹ️ Der Einsatz in '" + esc(ort) + "' läuft nicht mehr "
                                          "(beendet oder bereits von der Einsatzliste entfernt) — "
                                          "daher wurde keine Beobachtung angelegt."))
                    except Exception:
                        pass
                return
            einkl.append(ort)
            ud["einsatz_watches"] = einkl
            save_users(users)
            logger.info(f"Callback-Einsatz-Beobachtung: {ort} von User {from_id}")
            _answer_cb(cbid, f"⏱️ Einsatz {ort} wird beobachtet — Meldungen folgen.")
    except Exception as e:
        logger.error(f"handle_callback Fehler: {e}")
        try:
            _answer_cb(cbid, "Fehler beim Verarbeiten des Buttons.")
        except Exception:
            pass

# ═══ Telegram Command Menu (/ Vorschläge) ═══
def setup_telegram_commands():
    """Setzt das Telegram Command Menu, damit beim Tippen von / alle Befehle als Vorschläge erscheinen."""
    if not BOT_TOKEN:
        return

    # Befehle für alle User
    all_commands = [
        {"command": "start", "description": "Bot aktivieren / Begrüßung"},
        {"command": "hilfe", "description": "Alle Befehle im Überblick"},
        {"command": "anleitung", "description": "Wie funktioniert der Bot?"},
        {"command": "datenschutz", "description": "Welche Daten speichert der Bot?"},
        {"command": "lage", "description": "Aktuelle Einsätze in Oberösterreich"},
        {"command": "warnungen", "description": "Aktive Unwetter-Warnungen (GeoSphere)"},
        {"command": "ort", "description": "Ort dauerhaft beobachten"},
        {"command": "unort", "description": "Dauerhafte Beobachtung entfernen"},
        {"command": "unortall", "description": "Alle dauerhaften Beobachtungen entfernen"},
        {"command": "einsatz", "description": "Aktuellen Einsatz beobachten (temporär)"},
        {"command": "uneinsatz", "description": "Einsatz-Beobachtung entfernen"},
        {"command": "meinebeobachtungen", "description": "Meine Beobachtungen anzeigen"},
        {"command": "offenhausen", "description": "Letzte Einsätze der Heimat-Feuerwehr"},
        {"command": "heute", "description": "Einsätze von heute für meine Orte"},
        {"command": "stumm", "description": "Stillen Modus / Stillfenster einrichten"},
        {"command": "bezirk", "description": "Einsätze heute im Bezirk (z.B. WL)"},
        {"command": "brand", "description": "Laufende Brände (Ort oder Bezirk)"},
        {"command": "technisch", "description": "Technische Einsätze (Ort/Bezirk)"},
        {"command": "personenrettung", "description": "Personenrettungen (Ort/Bezirk)"},
        {"command": "unwetter", "description": "Unwetter-Einsätze (Ort/Bezirk)"},
        {"command": "sonstiges", "description": "Sonstige Einsätze (Ort/Bezirk)"},
        {"command": "umkreis", "description": "Einsätze im Umkreis [km] meiner Orte"},
        {"command": "training", "description": "Übungen der Heimat-Feuerwehr"},
        {"command": "statistik", "description": "Einsatzstatistik der letzten 12 Monate"},
        {"command": "wochen", "description": "Wochenrückblick ein-/ausschalten"},
        {"command": "qr_code", "description": "QR-Code zum Weiterschicken des Bots"},
        {"command": "fehler", "description": "Fehler/Problem an den Admin melden"},
        {"command": "wunsch", "description": "Wunsch/Idee für den Bot dem Admin schreiben"},
        {"command": "quellen", "description": "Welche Datenquellen nutzt der Bot?"},
        {"command": "meinedaten", "description": "Deine gespeicherten Daten anzeigen (DSGVO)"},
        {"command": "vergessen", "description": "Meinen Zugang komplett löschen (DSGVO, 2-Stufen)"},
        {"command": "testalarm", "description": "Probealarm prüfen, ob Alarme ankommen"},
        {"command": "pegel", "description": "Wasserstände rund um deine Orte"},
        {"command": "strom", "description": "⚡ Stromausfälle im Bezirk (Netz OÖ)"},
        {"command": "waldbrand", "description": "Waldbrand-Gefährdung an deinen Orten"},
        {"command": "lawine", "description": "Lawinenlage OÖ — mit Ort: /lawine Gosau"},
        {"command": "sirene", "description": "Nächster Sirenenprobe-Termin (Zivilschutz-Probealarm)"},
        {"command": "rueckblick", "description": "Dein persönlicher Einsatzrückblick"},
        {"command": "stimme", "description": "Sprachnachricht-Alarm ein-/ausschalten"},
        {"command": "abbruch", "description": "Laufende Löschung abbrechen / alles zurückholen"},
        {"command": "registrieren", "description": "Benutzernamen setzen/ändern"},
        {"command": "id", "description": "Deine Chat-ID anzeigen"},
    ]
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
    data = json.dumps({"commands": all_commands}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        logger.info("Telegram Command Menu gesetzt (alle User)")
    except Exception as e:
        logger.error(f"setMyCommands Fehler (alle User): {e}")

    # Admin-spezifische Befehle (scope: chat mit ADMIN_ID)
    if ADMIN_ID:
        admin_commands = all_commands + [
            {"command": "aufnehmen", "description": "Benutzer hinzufügen"},
            {"command": "entfernen", "description": "Benutzer entfernen"},
            {"command": "benutzer", "description": "Alle Benutzer anzeigen"},
            {"command": "verwalten", "description": "Beobachtung für anderen User setzen"},
            {"command": "sperren", "description": "ID sperren (dauerhaft oder X Stunden)"},
            {"command": "freigeben", "description": "Sperre aufheben"},
            {"command": "rundruf", "description": "Nachricht an alle Benutzer"},
            {"command": "serverstatus", "description": "Bot-Status: Laufzeit, User, Quelle, Speicher"},
            {"command": "widerruf", "description": "Laufende Lösch-Anträge anzeigen"},
        ]
        data_admin = json.dumps({
            "commands": admin_commands,
            "scope": {"type": "chat", "chat_id": ADMIN_ID}
        }).encode()
        req_admin = urllib.request.Request(url, data=data_admin, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req_admin, timeout=10)
            logger.info("Telegram Command Menu gesetzt (Admin)")
        except Exception as e:
            logger.error(f"setMyCommands Fehler (Admin): {e}")

# ═══ einsaetze.at Stats Helper ═══
def _rsc_operations(html):
    """Extrahiert operation-Objekte aus Next.js-RSC-Payload (einsaetze.at, seit ~08.2026).
    Daten liegen in self.__next_f.push-Blöcken als escaped JSON — nach unicode_escape
    normales JSON, ops via balanced-brace-Scan einsammeln."""
    try:
        pushes = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', html)
        raw = ''.join(pushes)
        # unicode_escape zerlegt Nicht-ASCII (Ã¼ statt ü) — Reparatur über latin-1-Rückweg
        dec = raw.encode().decode("unicode_escape", errors="replace")
        try:
            dec = dec.encode("latin-1", errors="ignore").decode("utf-8", errors="replace")
        except Exception:
            pass
        ops = []
        for m in re.finditer(r'"operation":\{', dec):
            start = m.end() - 1
            depth = 0; i = start; in_str = False; esc = False
            while i < len(dec):
                c = dec[i]
                if in_str:
                    if esc: esc = False
                    elif c == '\\': esc = True
                    elif c == '"': in_str = False
                else:
                    if c == '"': in_str = True
                    elif c == '{': depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            ops.append(dec[start:i+1]); break
                i += 1
        parsed = []
        for o in ops:
            try:
                parsed.append(json.loads(o))
            except Exception:
                pass
        return parsed
    except Exception:
        return []

EINSAETZE_AT_CATS = {"BRAND": "Brand", "TEE": "Technisch", "PERSON": "Personenrettung",
                     "UNWETTER": "Unwetter", "SONSTIGE": "Sonstige"}

def find_einsaetze_at_org_id(ort_name):
    """Findet die einsaetze.at Organisations-ID fuer einen Ort."""
    known = {FF_NAME.lower(): FF_ORG_ID} if FF_ORG_ID else {}
    key = ort_name.lower().strip()
    if key in known:
        return known[key]
    # Vollständiger FF-Index (einmalig aus Sitemap gebaut, 880 FFs) -> /bot/einsaetze_at_index.json
    try:
        idx_file = os.path.join(os.path.dirname(USERS_FILE), "einsaetze_at_index.json")
        if os.path.exists(idx_file):
            with open(idx_file, encoding="utf-8") as f:
                idx = json.load(f)
            if key in idx:
                return idx[key]
            # Toleranter Match: Teilstring (z.B. 'lengau' in 'lengau am hausruck')
            candidates = [k for k in idx if key in k or k in key]
            if len(candidates) == 1:
                return idx[candidates[0]]
            if candidates:
                # Mehrere Substring-Treffer (z. B. 'bach' in 'steinbach an der steyr'):
                # Längster Kandidat passt am besten zum Suchbegriff — nicht der kürzeste,
                # der zufällig überall als Teilstring vorkommt.
                pref = max(candidates, key=len)
                logger.info(f"einsaetze.at: {len(candidates)} Kandidaten für '{ort_name}': {candidates[:3]} — nehme '{pref}'")
                return idx[pref]
    except Exception as e:
        logger.debug(f"Index-Lookup Fehler: {e}")
    try:
        # Suche via RSC-Payload der Suchseite (alte /organizations/<id>-Links sind im HTML geblieben)
        search_url = f"https://www.einsaetze.at/search?q={urllib.parse.quote(ort_name)}"
        req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        org_matches = re.findall(r'/organizations/(\d+)', html)
        if org_matches:
            return org_matches[0]
        # Fallback: RSC-Payload nach organizations-IDs durchsuchen
        pushes = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', html)
        dec = ''.join(pushes).encode().decode("unicode_escape", errors="replace")
        org_matches = re.findall(r'"organizations/(\d+)"', dec) or re.findall(r'/organizations/(\d+)', dec)
        if org_matches:
            return org_matches[0]
    except Exception:
        pass
    return None

# ═══ Ort-Koordinaten (für Unwetter-Warnungen + /umkreis) ═══
ORT_KOORDINATEN = {
    "offenhausen": (48.1574, 13.8372),
    "lambach": (48.0965, 13.8894),
    "lengau": (48.0057, 13.2158),
    "bad schallerbach": (48.2304, 13.9194),
    "gaspoltshofen": (48.1320, 13.8422),
    "gunskirchen": (48.1333, 13.9333),
    "wels": (48.1667, 14.0333),
    "thalheim bei wels": (48.1333, 14.2167),
    "buchkirchen": (48.2167, 14.0667),
    "marchtrenk": (48.2000, 14.0833),
    "eferding": (48.4667, 14.0333),
    "grieskirchen": (48.2333, 13.8333),
    "vöcklabruck": (48.0031, 13.6553),
    "attnang-puchheim": (48.0167, 13.7167),
    "schwanenstadt": (48.0553, 13.7617),
    "st. martin im innkreis": (48.3200, 13.5167),
}

UA_NOMINATIM = "FlipsiPager/1.0 (github.com/TechFlipsi/FlipsiPager)"


def _ort_koordinaten(ort):
    """Liefert (lat, lon) für einen Ort: erst Lookup-Tabelle, sonst Nominatim (+Cache in users.json-Verzeichnis)."""
    key = ort.lower().strip()
    if key in ORT_KOORDINATEN:
        return ORT_KOORDINATEN[key]
    geo_file = os.path.join(os.path.dirname(USERS_FILE), "ort_geo.json")
    cache = {}
    try:
        if os.path.exists(geo_file):
            with open(geo_file, encoding="utf-8") as f:
                cache = json.load(f)
            if key in cache:
                return tuple(cache[key])
    except Exception:
        cache = {}
    try:
        from urllib.parse import quote as _q
        url = f"https://nominatim.openstreetmap.org/search?q={_q(ort + ' Österreich')}&format=json&limit=1&countrycodes=at"
        req = urllib.request.Request(url, headers={"User-Agent": UA_NOMINATIM})
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read().decode("utf-8", errors="replace"))
        if d:
            lat, lon = float(d[0]["lat"]), float(d[0]["lon"])
            cache[key] = [lat, lon]
            try:
                with open(geo_file, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
            except Exception:
                pass
            return (lat, lon)
    except Exception as e:
        logger.debug(f"Geocoding fehlgeschlagen für {ort}: {e}")
    return None


def _haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    la1, lo1, la2, lo2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, a ** 0.5))


# ═══ Unwetter-Warnungen (GeoSphere-Austria-WarnAPI, offizielle ZAMG-Nachfolger) ═══
UNWETTER_CHECK_INTERVAL_MIN = 10      # nicht öfter prüfen (API schont)
UNWETTER_ACTIVATE_STUFE = 2           # Warnstufe 2+ = 'starke Unwetter' alarmieren; 1 = nur Hinweis
UNWETTER_STATE_FILE = os.path.join(os.path.dirname(USERS_FILE), "unwetter_state.json")


def _load_unwetter_state():
    try:
        with open(UNWETTER_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_unwetter_state(state):
    try:
        os.makedirs(os.path.dirname(UNWETTER_STATE_FILE), exist_ok=True)
        with open(UNWETTER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.debug(f"Unwetter-State nicht speicherbar: {e}")


def _warntyp_name(warntypid):
    return {1: "Wind", 2: "Schneefall/Schneelast", 3: "Straßenglätte", 4: "Gewitter",
            5: "Gewitter/Starkregen", 6: "Schnee", 7: "Sturm", 8: "Hochwasser",
            9: "Regen", 10: "Hitze"}.get(warntypid, f"Warnung {warntypid}")


def _warnstufe_emoji(stufe):
    return {1: "\U0001f7e2", 2: "\U0001f7e1", 3: "\U0001f534", 4: "\U0001f7e0"}.get(stufe, "\u26a0\ufe0f")


def fetch_unwetter(lat, lon, lang="de"):
    """Aktive Unwetter-Warnungen an Koordinate. Rückgabe: Liste von Dicts
    (warntyp, stufe, begin, end, text, warnid) — leer wenn nichts aktiv."""
    out = []
    try:
        url = f"https://warnungen.zamg.at/wsapp/api/getWarningsForCoords?lat={lat}&lon={lon}&lang={lang}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode("utf-8", errors="replace"))
        for w in d.get("properties", {}).get("warnings", []) or []:
            wp = w.get("properties", {})
            out.append({
                "warntyp": _warntyp_name(wp.get("warntypid", 0)),
                "stufe": wp.get("warnstufeid", 0),
                "begin": wp.get("begin", "?"),
                "end": wp.get("end", "?"),
                "text": (wp.get("text") or "").strip(),
                "warnid": f"{wp.get('warnid', 'x')}-{wp.get('chgid', 0)}-{wp.get('verlaufid', 0)}",
            })
    except Exception as e:
        logger.debug(f"Unwetter-Abruf fehlgeschlagen ({lat},{lon}): {e}")
    return out


def check_unwetter_for_users(users):
    """Läuft im Haupt-Loop: Alle beobachteten Orte aller User auf aktive Unwetter-Warnungen
    prüfen (GeoSphere-WarnAPI). Alarm bei NEUER Warnung ab Stufe UNWETTER_ACTIVATE_STUFE,
    auch bei Stufen-Erhöhung einer bereits gesehenen. Dedup über unwetter_state.json."""
    now = time.time()
    state = _load_unwetter_state()
    if now - state.get("last_check", 0) < UNWETTER_CHECK_INTERVAL_MIN * 60:
        return
    # Einzigartige Orte über alle User sammeln (ein API-Call pro Ort, Meldung an alle Beobachter)
    orte_map = {}
    for cid, ud in users.get("users", {}).items():
        if ud.get("silent"):
            continue
        for ort in ud.get("orte", []):
            orte_map.setdefault(ort.lower().strip(), set()).add(cid)
    state["last_check"] = now
    if not orte_map:
        _save_unwetter_state(state)
        return
    seen = dict(state.get("seen", {}))
    aktive_keys = set()
    for ort_key, chat_ids in orte_map.items():
        coords = _ort_koordinaten(ort_key)
        if not coords:
            continue
        warns = fetch_unwetter(coords[0], coords[1])
        ort_anzeige = esc(_ort_anzeige_cap(ort_key))
        meldunge_ort = []
        for w in warns:
            if not w["stufe"] or int(w["stufe"]) < UNWETTER_ACTIVATE_STUFE:
                continue
            warn_key = f"{ort_key}:{w['warnid']}"
            aktive_keys.add(warn_key)
            prev = seen.get(warn_key)
            if prev is None or int(w["stufe"]) > int(prev):
                seen[warn_key] = w["stufe"]
                meldunge_ort.append(w)
        # Neue/Stufen-höhere Warnungen an ALLE Beobachter des Ortes senden
        for w in meldunge_ort:
            emoji = _warnstufe_emoji(int(w["stufe"]))
            msg = (f"{emoji} <b>{esc(w['warntyp'])} — {ort_anzeige}</b>\n"
                   f"Warnstufe {w['stufe']} · {esc(w['begin'])} bis {esc(w['end'])}\n"
                   f"{esc(w['text'])}")
            kb_warnung = {"inline_keyboard": [[btn_karte_url(_ort_anzeige_cap(ort_key))]]}
            for cid in chat_ids:
                ud = users.get("users", {}).get(str(cid), {})
                if ud.get("silent"):
                    continue
                send_to(cid, msg, reply_markup=kb_warnung)
    seen = {k: v for k, v in seen.items() if k in aktive_keys}
    state["seen"] = seen
    _save_unwetter_state(state)


def _ort_anzeige_cap(ort_key):
    return ort_key[:1].upper() + ort_key[1:] if ort_key else ort_key

# Alias für alten Namen (falls irgendwo referenziert)
ort_anzeige_cap = _ort_anzeige_cap


def fetch_einsaetze_at_stats(ort_name):
    """Holt Einsatzstatistik von einsaetze.at (letzte 12 Monate, nach Typ).

    einsaetze.at ist seit ~08.2026 eine Next.js/React-App — die alte
    operation-group-header/operation-item-HTML-Struktur existiert nicht mehr.
    Neu: operation-JSON-Objekte im RSC-Payload + Kategorie-Filter ?kategorie=.
    SELBST (=Selbsteinsatz/Übung) wird bewusst NICHT gezählt.
    """
    org_id = find_einsaetze_at_org_id(ort_name)
    if not org_id:
        return None
    cutoff = (datetime.now() - timedelta(days=365)).date()
    stats = {"gesamt": 0, "Brand": 0, "Technisch": 0, "Personenrettung": 0, "Sonstige": 0}
    try:
        for cat in EINSAETZE_AT_CATS:
            url = f"https://www.einsaetze.at/organizations/{org_id}?kategorie={cat}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            for o in _rsc_operations(html):
                try:
                    d = datetime.strptime(o.get("dateKey", ""), "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
                if d >= cutoff:
                    stats["gesamt"] += 1
                    stats[EINSAETZE_AT_CATS[cat]] += 1
        return stats
    except Exception:
        return None

# ═══ OOELFV Parsing (unverändert) ═══
def fetch_ooelfv(url, bezirk_code=None):
    if bezirk_code:
        post_data = urllib.parse.urlencode({"bezirk": bezirk_code, "exercise": "-1"}).encode()
        req = urllib.request.Request(url, data=post_data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_einsaetze_full(html):
    einsaetze = []
    if "kein Einsatz" in html or "Zur Zeit sind keine Einsätze offen" in html:
        return []
    td_pattern = re.findall(r'<td[^>]*style="background-color:\s*(\w+)"[^>]*>\s*&nbsp;\s*</td>\s*<td[^>]*style="border-bottom[^"]*"[^>]*>(.*?)</td>', html, re.DOTALL)
    for farbe, content in td_pattern:
        ort_match = re.search(r'<b>(.*?)</b>\s*\(\<a[^>]*title="([^"]*)"[^>]*>([^<]*)</a>\)\s*:\s*(.*?)(?:<br>|\s*<ul|$)', content, re.DOTALL)
        if not ort_match:
            continue
        ort = strip_tags(ort_match.group(1).strip())
        bezirk = strip_tags(ort_match.group(2).strip())
        bezirk_kuerzel = strip_tags(ort_match.group(3).strip())
        stichwort = strip_tags(ort_match.group(4).strip())
        fw_pattern = re.findall(r'<li>(.*?):\s*&nbsp;([\d.]+\s+[\d:]+)(?:(?:\s*&nbsp;)?\s*&ndash;\s*(?:&nbsp;)?([\d.]+\s+[\d:]+|[\d:]+))?', content)
        feuerwehren = []
        for fw_name, start, end in fw_pattern:
            feuerwehren.append({"name": strip_tags(fw_name.strip()), "start": start.strip(), "end": end.strip() if end else None})
        einsaetze.append({"ort": ort, "bezirk": bezirk, "bezirk_kuerzel": bezirk_kuerzel, "stichwort": stichwort, "typ": FARBEN.get(farbe, "?"), "farbe": farbe, "feuerwehren": feuerwehren})
    return einsaetze

def parse_zeit(zeit_str):
    try:
        return datetime.strptime(f"{zeit_str} {datetime.now().year}", "%d.%m. %H:%M %Y")
    except (ValueError, TypeError):
        # Fallback: time-only Format wie "08:52" (OOELFV Endzeiten sind oft nur Uhrzeit)
        try:
            heute = datetime.now()
            t = datetime.strptime(zeit_str, "%H:%M")
            return heute.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        except (ValueError, TypeError):
            return None

def calc_dauer(start_str, end_str=None):
    s = parse_zeit(start_str)
    if not s:
        return "?"
    e = parse_zeit(end_str) if end_str else datetime.now()
    if not e:
        e = datetime.now()
    delta = e - s
    if delta.total_seconds() < 0:
        e = e + timedelta(days=1)
        delta = e - s
    minuten = int(delta.total_seconds() // 60)
    stunden, rest = divmod(minuten, 60)
    if stunden > 0 and rest > 0:
        return f"{stunden}h {rest}min"
    elif stunden > 0:
        return f"{stunden}h"
    else:
        return f"{minuten}min"

def einsatz_key(e):
    fw0 = e["feuerwehren"][0]["start"] if e["feuerwehren"] else "?"
    return f"{e['ort']}|{e['stichwort']}|{fw0}"

def fw_namen(fw_list):
    return ", ".join(fw["name"] for fw in fw_list) if fw_list else "?"

def load_state(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return None

def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, ensure_ascii=False)

def clear_state(path):
    if os.path.exists(path):
        os.remove(path)

# ═══ Watch Matching ═══
def einsatz_matches_watch(einsatz, watch_term):
    w = watch_term.lower()
    # Ort: exakter oder Teil-Match
    if w in einsatz["ort"].lower():
        return True
    # Feuerwehr-Namen
    for fw in einsatz["feuerwehren"]:
        if w in fw["name"].lower():
            return True
    # Stichwort: Teil-Match (z.B. "Brand" matched alle Brand-Einsätze)
    if w in einsatz.get("stichwort", "").lower():
        return True
    # Bezirk: Teil-Match (z.B. "Braunau" matched alle Einsätze im Bezirk Braunau)
    if w in einsatz.get("bezirk", "").lower():
        return True
    return False

# ═══ Per-User Check ═══
# ═══ Bezirk-Match: Kürzel (WL) oder voller Name (Wels-Land) ═══
BEZIRKS_KUERZEL = {
    "wl": "Wels-Land", "ll": "Linz-Land", "gm": "Gmunden", "ki": "Kirchdorf",
    "gr": "Grieskirchen", "pe": "Perg", "br": "Braunau", "ef": "Eferding",
    "fr": "Freistadt", "ri": "Ried im Innkreis", "ro": "Rohrbach", "sd": "Schärding",
    "se": "Steyr-Land", "uu": "Urfahr-Umgebung", "vb": "Vöcklabruck",
    "sr": "Steyr-Stadt", "we": "Wels-Stadt", "ls": "Linz-Stadt",
}


def such_bezirk_match(e, kz):
    """Matcht Einsatz e gegen Bezirks-Kürzel ODER vollen Bezirksnamen (case-insensitive)."""
    k = kz.lower().strip()
    if not k:
        return False
    bez = (e.get("bezirk", "") or "").lower()
    kzl = (e.get("bezirk_kuerzel", "") or "").lower()
    if bez == k or kzl == k:
        return True
    # Kürzel eingegeben, nur voller Name bekannt: 'wl' -> 'wels-land'
    voller = BEZIRKS_KUERZEL.get(k)
    if voller and bez == voller.lower():
        return True
    # Voller Name als Teil-Match (z.B. 'wels-land' in bezirk)
    return k in bez


def _in_quiet_hours(qh):
    """Prüft ob die aktuelle Uhrzeit im Stillfenster liegt (Format '22-07' = 22 bis 07 Uhr)."""
    try:
        if not qh or "-" not in str(qh):
            return False
        a, b = str(qh).split("-", 1)
        a, b = int(a), int(b)
        if not (0 <= a <= 23 and 0 <= b <= 23):
            return False
        h = datetime.now().hour
        if a <= b:
            return a <= h < b
        return h >= a or h < b  # Fenster über Mitternacht
    except (ValueError, TypeError):
        return False


def check_user_watches(chat_id, user_data, einsaetze_all, suppress=False):
    orte = user_data.get("orte", [])
    einsatz_watches = user_data.get("einsatz_watches", [])
    all_watches = orte + einsatz_watches
    state_file = os.path.join(STATE_DIR, f"user_{chat_id}.json")
    if not all_watches:
        clear_state(state_file)
        return False

    # Track which matched einsaetze came from temporary einsatz_watches
    temp_keys = set()
    matched = []
    matched_by = {}
    beendet_flags = []  # parallel zu meldungen: True = BEENDET-Meldung (wird auch bei suppress gesendet)
    # Typ-Filter: ort_typen[chat_id als key im user_data? — liegt im user_data selbst]
    ort_filter = user_data.get("ort_typen") or {}
    for e in einsaetze_all:
        for watch in all_watches:
            if einsatz_matches_watch(e, watch):
                # Typ-Filter (dauerhafte /ort-Beobachtungen): 'Brand' etc. als Teilstring im typ ('🔴 Brand')
                gef_typ = ort_filter.get(watch)
                if gef_typ and gef_typ not in e.get("typ", ""):
                    # ABER: Temporäre /einsatz-Watches ignorieren den Filter nicht —
                    # der Filter gilt nur wenn exakt dieser Ort gefiltert ist.
                    continue
                matched.append(e)
                matched_by[einsatz_key(e)] = watch
                if watch in einsatz_watches:
                    temp_keys.add(einsatz_key(e))
                break

    state = load_state(state_file) or {"einsaetze": {}}
    letzter_stand = state.get("einsaetze", {})
    aktueller_stand = {einsatz_key(e): e for e in matched}
    meldungen = []
    melde_kbs = []  # parallel zu meldungen: Inline-Keyboard je Meldung (📍 Karte, BEENDET + ⭐)

    # Ausstehende Sammel-Meldung aus Stillfenster zustellen (Fenster vorbei + nicht silent)
    if not suppress and (state.get("pending_alerts") or []):
        if not user_data.get("silent") and not _in_quiet_hours(user_data.get("quiet_hours")):
            pend = state.get("pending_alerts")
            send_to(chat_id, "🌅 Einen guten Morgen! In der Nacht gab es %d Meldung(en) in deinen Orten:\n\n%s" % (len(pend), "\n\n".join(pend)))
            logger.info(f"Stillfenster-Sammel-Meldung gesendet an {chat_id} ({len(pend)} Meldungen)")
            state["pending_alerts"] = []

    # Neue Einsätze
    for k in aktueller_stand:
        if k not in letzter_stand:
            e = aktueller_stand[k]
            fw_count = len(e["feuerwehren"])
            fw0 = e["feuerwehren"][0] if e["feuerwehren"] else {}
            start = fw0.get("start", "?")
            namen = fw_namen(e["feuerwehren"])
            wt = matched_by.get(k, "?")
            typ_text = e.get("typ", "")
            stichwort_text = e.get("stichwort", "")
            # Großeinsatz-Highlight: ⚫-Typ oder Alarmstufe 4 im Stichwort
            if "⚫" in typ_text or "❹" in stichwort_text:
                betreff = "\U0001f6a8\U0001f6a8 <b>GROSSER EINSATZ</b> \U0001f6a8\U0001f6a8"
            elif "❸" in stichwort_text:
                betreff = "\U0001f6a8 Erhöhte Alarmstufe:"
            else:
                betreff = "\U0001f514 <b>NEUER EINSATZ</b>"
            # Alarm für Wochenrückblick protokollieren
            log_alarm(e, chat_id)
            # Nachbar-Feuerwehr-Auto-Watch: zeige mit-alarmierte FWs die nicht dem beobachteten Ort entsprechen
            nachbar_block = ""
            if fw_count > 1:
                # Primaere FW = die FW die zum beobachteten Ort passt
                primaere_fw = None
                w_lower = wt.lower() if wt != "?" else ""
                for fw in e["feuerwehren"]:
                    if w_lower in fw["name"].lower() or w_lower in e["ort"].lower():
                        primaere_fw = fw["name"]
                        break
                # Wenn keine primaere FW gefunden, nimm die erste
                if not primaere_fw:
                    primaere_fw = e["feuerwehren"][0]["name"] if e["feuerwehren"] else ""
                # Nachbar-FWs = alle ausser der primaeren
                nachbarn = [fw["name"] for fw in e["feuerwehren"] if fw["name"] != primaere_fw]
                if nachbarn:
                    nachbar_block = f"\n\U0001f692 <b>Mit alarmiert:</b> {esc(', '.join(nachbarn))}"
            meldungen.append(
                f"{betreff}\n"
                f"\U0001f4cb {esc(e['typ'])} {esc(e['stichwort'])}\n"
                f"\U0001f4cd {esc(e['ort'])} ({esc(e['bezirk'])})\n"
                f"\U0001f465 {fw_count} Feuerwehr(en): {esc(namen)}"
                f"{nachbar_block}\n"
                f"\u23f1\ufe0f Alarm: {start} (seit {calc_dauer(start)})\n"
                f"\U0001f50d Beobachtet: {esc(wt)}"
            )
            beendet_flags.append(False)
            melde_kbs.append({"inline_keyboard": [[btn_karte_url(e.get("ort", "")), btn_navi_url(e.get("ort", ""))]]})

    # Beendete Einsätze
    beendete_temp_keys = []
    # Keys die still_active sind (nicht aus State löschen — für mehrtägige Einsätze)
    still_active_keys = set()
    for k in letzter_stand:
        if k not in aktueller_stand:
            e = letzter_stand[k]
            still_active = any(einsatz_key(ae) == k for ae in einsaetze_all)
            if still_active:
                still_active_keys.add(k)
                continue
            # Fallback: Prüfe auch Tag-Seite (bei mehrtägigen Einsätzen kann
            # der Einsatz noch aktiv sein aber von der aktuell-Seite verschwunden)
            tag_check = get_tag_html()
            if tag_check:
                try:
                    tag_e = parse_einsaetze_full(tag_check)
                    if any(te["ort"] == e.get("ort") and te["stichwort"] == e.get("stichwort") for te in tag_e):
                        # Noch auf Tag-Seite → prüfe ob noch FW ohne Endzeit
                        for te in tag_e:
                            if te["ort"] == e.get("ort") and te["stichwort"] == e.get("stichwort"):
                                if any(not fw.get("end") for fw in te.get("feuerwehren", [])):
                                    still_active = True
                                    still_active_keys.add(k)
                                    break
                except Exception:
                    pass
            if still_active:
                continue
            tag_html = get_tag_html()
            end_einsatz = None
            if tag_html:
                try:
                    tag_e = parse_einsaetze_full(tag_html)
                    for te in tag_e:
                        if te["ort"] == e["ort"] and te["stichwort"] == e["stichwort"]:
                            end_einsatz = te
                            break
                except Exception:
                    pass
            end_fw = end_einsatz["feuerwehren"] if end_einsatz else e.get("feuerwehren", [])
            endzeiten = [fw["end"] for fw in end_fw if fw.get("end")]
            end_zeit = endzeiten[-1] if endzeiten else None
            fw0 = end_fw[0] if end_fw else (e.get("feuerwehren") or [{}])[0]
            start = fw0.get("start", "?")
            dauer = calc_dauer(start, end_zeit)
            fw_count = len(end_fw)
            msg = (
                f"\u2705 <b>EINSATZ BEENDET</b>\n"
                f"\U0001f4cb {esc(e.get('typ',''))} {esc(e.get('stichwort',''))}\n"
                f"\U0001f4cd {esc(e.get('ort','?'))} ({esc(e.get('bezirk','?'))})\n"
                f"\u23f1\ufe0f Dauer: {dauer}\n"
                f"\U0001f465 {fw_count} Feuerwehr(en):"
            )
            for fw in end_fw:
                z = f"\n  \u2022 {esc(fw['name'])}: "
                if fw.get("end"):
                    z += f"{fw['start'].split()[-1]}\u2013{fw['end'].split()[-1]} ({calc_dauer(fw['start'], fw['end'])})"
                elif end_zeit:
                    z += f"{fw['start'].split()[-1]}\u2013{end_zeit.split()[-1]} ({calc_dauer(fw['start'], end_zeit)})"
                else:
                    z += f"{fw['start'].split()[-1]} (seit {calc_dauer(fw['start'])})"
                msg += z
            # Zusatz-Hinweis bei temporärer Einsatz-Beobachtung
            # Prüfe: ob dieser Einsatz durch eine einsatz_watch beobachtet wurde.
            # temp_keys wird beim Match gebaut, aber bei mehrtägigen Einsätzen
            # kann der Einsatz schon von der aktuell-Seite verschwunden sein.
            # Daher zusätzlich Prüfung: ob der Ort in einsatz_watches ist.
            is_temp_watch = k in temp_keys or einsatz_key(e) in temp_keys
            if not is_temp_watch:
                # Fallback: prüfe ob der Ort des beendeten Einsatzes in einsatz_watches ist
                ort_lower = e.get("ort", "").lower()
                for ew in einsatz_watches:
                    if ew.lower() == ort_lower:
                        is_temp_watch = True
                        break
            if is_temp_watch:
                msg += "\n\n✨ Automatische Beobachtung beendet."
                beendete_temp_keys.append(e.get("ort", ""))
            _kb_row_b = ([{"text": "⭐ Ort dauerhaft beobachten", "callback_data": _cb_safe("ao:", e.get("ort", ""))}] if is_temp_watch and _cb_safe("ao:", e.get("ort", "")) else []) + [btn_karte_url(e.get("ort", "")), btn_navi_url(e.get("ort", ""))]
            melde_kbs.append({"inline_keyboard": [_kb_row_b] if _kb_row_b else []})
            meldungen.append(msg)
            beendet_flags.append(True)

    # Aktualisierte Einsätze
    for k in aktueller_stand:
        if k in letzter_stand:
            alt = letzter_stand[k]
            neu = aktueller_stand[k]
            alt_fw = alt.get("feuerwehren", [])
            neu_fw = neu["feuerwehren"]
            alt_count = len(alt_fw)
            neu_count = len(neu_fw)
            aenderungen = []
            if neu_count > alt_count:
                alte_namen = {fw["name"] for fw in alt_fw}
                neue_namen = [fw["name"] for fw in neu_fw if fw["name"] not in alte_namen]
                aenderungen.append(f"\U0001f4c8 <b>+</b>{neu_count - alt_count} FW dazu: {esc(', '.join(neue_namen))} (jetzt {neu_count} gesamt)")
            elif neu_count < alt_count:
                neue_set = {fw["name"] for fw in neu_fw}
                gegangen = [fw["name"] for fw in alt_fw if fw["name"] not in neue_set]
                aenderungen.append(f"\U0001f4c9 {alt_count - neu_count} FW abgezogen: {esc(', '.join(gegangen))} (noch {neu_count} aktiv)")
            for nfw in neu_fw:
                for afw in alt_fw:
                    if afw["name"] == nfw["name"] and not afw.get("end") and nfw.get("end"):
                        aenderungen.append(f"  \u21b3 {esc(nfw['name'])}: {nfw['start'].split()[-1]}\u2013{nfw['end'].split()[-1]} ({calc_dauer(nfw['start'], nfw['end'])})")
            if aenderungen:
                fw0 = neu_fw[0] if neu_fw else alt_fw[0] if alt_fw else {}
                start = fw0.get("start", "?")
                msg = (
                    f"\U0001f4ca <b>UPDATE: {esc(neu['typ'])} {esc(neu['stichwort'])}</b>\n"
                    f"\U0001f4cd {esc(neu['ort'])} ({esc(neu['bezirk'])})\n"
                    + "\n".join(aenderungen) +
                    f"\n\u23f1\ufe0f Laufzeit: {calc_dauer(start)}"
                )
                melde_kbs.append({"inline_keyboard": [[btn_karte_url(neu.get("ort", "")), btn_navi_url(neu.get("ort", ""))]]})
                meldungen.append(msg)
                beendet_flags.append(False)

    # BEENDET-Meldungen (beendet_flags=True) werden AUCH beim ersten Zyklus nach
    # einem Bot-Neustart gesendet — der User hat bewusst auf Beobachten geklickt und
    # wartet auf den Abschlussbericht. Suppress (first_cycle) unterdrückt nur
    # NEU-/UPDATE-Meldungen (sonst Restart-Flut mit allen laufenden Einsätzen).
    if suppress:
        neu_update = [(m, kb) for m, kb, f in zip(meldungen, melde_kbs, beendet_flags) if not f]
        beendet_only = [(m, kb) for m, kb, f in zip(meldungen, melde_kbs, beendet_flags) if f]
        if beendet_only:
            # Abschlussberichte trotz first_cycle ausliefern (Bugfix: sie waren sonst
            # für immer verloren, wenn der Einsatz zwischen Restart und erstem Check endete)
            for m, kb in beendet_only:
                send_to(chat_id, m, reply_markup=kb)
            logger.info(f" BEENDET-Meldung(en) nach Neustart nachgesendet an {chat_id} ({len(beendet_only)})")
        meldungen = [m for m, kb in neu_update]
        melde_kbs = [kb for m, kb in neu_update]
    # (suppress=False → alles läuft klassisch durch den Send-Block unten)

    if meldungen and not suppress:
        if _in_quiet_hours(user_data.get("quiet_hours")):
            # Stillfenster: Alarme NICHT direkt senden, sondern sammeln
            pend = state.get("pending_alerts") or []
            pend.extend(meldungen)
            state["pending_alerts"] = pend[-50:]
            logger.info(f"Stillfenster aktiv (User {chat_id}): {len(meldungen)} Meldung(en) gesammelt")
        elif not user_data.get("silent"):
            # Silent-Modus: keine Alarm-Nachrichten senden, State aber trotzdem updaten
            # Mehrere Meldungen: EIN Sammel-Keyboard (eine Reihe pro Einsatz, ⏱️+📍)
            kb_gesamt = None
            if len(meldungen) > 1 and len(melde_kbs) == len(meldungen):
                kb_zeilen = []
                for kb in melde_kbs:
                    kb_zeilen.extend(kb.get("inline_keyboard", []))
                kb_gesamt = {"inline_keyboard": kb_zeilen}
            send_to(chat_id, "\n\n".join(meldungen), reply_markup=kb_gesamt or (melde_kbs[0] if melde_kbs else None))
            # Sprachnachricht (opt-in /stimme): für die NEUEN Einsätze (erster genügt als Sprach-Alarm)
            for k_neu, e_neu in list(aktueller_stand.items()):
                if k_neu not in letzter_stand:
                    fw_c = len(e_neu["feuerwehren"])
                    nm = fw_namen(e_neu["feuerwehren"])
                    send_stimme_wenn_aktiv(chat_id, user_data, e_neu, fw_c, nm)
                    break
            # Großeinsatz-Durchgriff: silent-User bekommen ⚫-GROSSEINSATZ/Alarmstufe-4-Meldungen TROTZDEM
            # (bewusste Ausnahme: bei wirklich großen Einsätzen schläft niemand weiter)
            if user_data.get("silent"):
                grosse = [(m, kb) for m, kb in zip(meldungen, melde_kbs) if ("GROSSER EINSATZ" in m or "Erhöhte Alarmstufe" in m)]
                for m, kb in grosse:
                    send_to(chat_id, "🔕⚡ <b>Großeinsatz-Durchgriff (stiller Modus bleibt aktiv):</b>\n\n" + m, reply_markup=kb)
                if grosse:
                    logger.info(f"Großeinsatz-Durchgriff an silent-User {chat_id}: {len(grosse)} Meldung(en)")

    # State speichern: aktuelle Matches + still_active Einsätze (mehrtägig)
    saved_einsaetze = {k: {"ort": e["ort"], "bezirk": e["bezirk"], "stichwort": e["stichwort"], "typ": e["typ"], "feuerwehren": e["feuerwehren"]} for k, e in aktueller_stand.items()}
    # still_active Einsätze aus letzter Stand behalten (damit sie im nächsten Cycle erkannt werden)
    for k in still_active_keys:
        if k in letzter_stand:
            se = letzter_stand[k]
            saved_einsaetze[k] = {"ort": se["ort"], "bezirk": se["bezirk"], "stichwort": se["stichwort"], "typ": se["typ"], "feuerwehren": se["feuerwehren"]}
    state_out = {"einsaetze": saved_einsaetze}
    if state.get("pending_alerts"):
        state_out["pending_alerts"] = state["pending_alerts"]
    save_state(state_file, state_out)
    # Auto-Entfernung beendeter temporärer Einsatz-Beobachtungen
    if beendete_temp_keys:
        user_einsatz_watches = user_data.get("einsatz_watches", [])
        for ort_name in beendete_temp_keys:
            for i, w in enumerate(user_einsatz_watches):
                if w.lower() == ort_name.lower():
                    user_einsatz_watches.pop(i)
                    logger.info(f"Temporäre Einsatz-Beobachtung auto-entfernt: {ort_name} (User {chat_id})")
                    break
        user_data["einsatz_watches"] = user_einsatz_watches
        save_users(users)
    return bool(matched)

# ═══ InkyPi Trigger ═══
def trigger_inkypi_feuerwehr():
    if not INKYPI_ENABLED:
        return False
    try:
        import requests
        resp = requests.post(INKYPI_API, json=INKYPI_PLUGIN_DATA, timeout=60)
        if resp.status_code == 200:
            logger.info("InkyPi: Feuerwehr-Monitor auf Display geladen")
            return True
        logger.error(f"InkyPi API Fehler: {resp.status_code}")
        return False
    except Exception as e:
        logger.error(f"InkyPi API nicht erreichbar: {e}")
        return False

# ═══ Telegram Photo-Send (multipart) ═══
def send_photo(chat_id, png_bytes, caption=None):
    if not BOT_TOKEN:
        return False
    boundary = "fwbot" + str(os.getpid()) + str(int(time.time() * 1000))
    parts = []
    parts.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n" + str(chat_id) + "\r\n").encode())
    if caption:
        parts.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n" + caption + "\r\n").encode())
    parts.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"qr.png\"\r\nContent-Type: image/png\r\n\r\n").encode())
    parts.append(png_bytes)
    parts.append(("\r\n--" + boundary + "--\r\n").encode())
    body = b"".join(parts)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        logger.error(f"sendPhoto Fehler (ID {chat_id}): {e}")
        return False

# ═══ Alarm-Log (für Wochenrückblick) ═══
def log_alarm(e, chat_id):
    """Hängt einen Alarm ans Monats-Log an (idempotent pro einsatz_key+chat_id)."""
    try:
        path = os.path.join(STATE_DIR, "alarme_%04d-%02d.json" % (datetime.now().year, datetime.now().month))
        eintraege = []
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    eintraege = json.load(f)
            except Exception:
                eintraege = []
        eintraege.append({
            "datum": datetime.now().isoformat(),
            "key": einsatz_key(e),
            "ort": e.get("ort", ""),
            "stichwort": e.get("stichwort", ""),
            "typ": e.get("typ", ""),
            "chat_ids": [str(chat_id)],
        })
        eintraege = eintraege[-3000:]
        with open(path, "w") as f:
            json.dump(eintraege, f)
    except Exception as ex:
        logger.error(f"Alarm-Log Fehler: {ex}")

# ═══ Wochenrückblick (Sonntag 20:00, opt-in) ═══
def send_week_digests():
    jetzt = datetime.now()
    if jetzt.weekday() != 6 or jetzt.hour != 20:
        return
    log_path = os.path.join(STATE_DIR, "alarme_%04d-%02d.json" % (jetzt.year, jetzt.month))
    alle = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                alle = json.load(f)
        except Exception:
            alle = []
    vor7 = jetzt - timedelta(days=7)
    for cid_str, ud in list(users["users"].items()):
        if not ud.get("registered") or not ud.get("week_digest"):
            continue
        if blocked_reason(cid_str):
            continue
        if ud.get("week_digest_last") == jetzt.date().isoformat():
            continue
        orte_lower = [o.lower() for o in ud.get("orte", [])]
        if not orte_lower:
            continue
        gef = {}
        for ein in alle:
            try:
                dt = datetime.fromisoformat(ein["datum"])
            except Exception:
                continue
            if dt < vor7:
                continue
            if ein.get("ort", "").lower() not in orte_lower:
                continue
            if cid_str not in [str(c) for c in ein.get("chat_ids", [])]:
                continue
            typ = ein.get("typ", "?")
            gef[typ] = gef.get(typ, 0) + 1
        gesamt = sum(gef.values())
        if gesamt == 0:
            text = "\U0001f4ca <b>Deine Woche:</b> Keine Einsätze in deinen Orten. Ruhige Woche! 🚒"
        else:
            teile = ["%dx %s" % (n, t) for t, n in sorted(gef.items(), key=lambda x: -x[1])]
            text = ("\U0001f4ca <b>Deine Woche:</b> %d Einsätze in deinen Orten:\n" % gesamt) + "\n".join("• " + esc(t) for t in teile)
        try:
            send_to(int(cid_str), text)
            ud["week_digest_last"] = jetzt.date().isoformat()
            save_users(users)
            logger.info(f"Wochenrückblick gesendet an {cid_str}")
        except Exception as e:
            logger.error(f"Wochenrückblick-Fehler {cid_str}: {e}")

# ═══ Help Texts ═══
def datenschutz_text():
    """Datenschutz-Information (DSGVO-transparenzgesetz-Pflicht): Welche Daten
    speichert der Bot, wie lange, wer sieht sie, wie lassen sie sich löschen."""
    return (
        "\U0001f6e1\ufe0f <b>Datenschutz — Feuerwehr-Monitor Bot</b>\n"
        "Dieser Bot verarbeitet personenbezogene Daten. Hier steht transparent, "
        "was, wie lange und zu welchem Zweck.\n\n"
        "\U0001f464 <b>1. Welche Daten speichert der Bot?</b>\n"
        "\u2022 <b>Telegram-Chat-ID</b> (technisch zwingend notwendig \u2014 Telegram-Nachrichten "
        "geht nicht ohne)\n"
        "\u2022 <b>Benutzername</b>, den du dir mit /registrieren selbst gibst\n"
        "\u2022 <b>Deine Beobachtungen</b>: beobachtete Orte (\u00f6ffentliche Ortsnamen, keine "
        "Adressen) und tempor\u00e4re Einsatz-Beobachtungen\n"
        "• <b>Zeitstempel</b> (seit wann du registriert bist)\n"
        "• <b>Alarm-Verlauf</b> (welche Alarme dich betroffen haben — für Rückblick/Wochenübersicht)\n"
        "• <b>Bei Sprachalarm (/stimme):</b> nur das Ein/Aus-Flag in deinen Einstellungen — "
        "die Spracherzeugung läuft auf dem eigenen Server, es werden keine Sprachdaten übertragen\n"
        "• <b>Bei Fehlermeldungen</b> (/fehler): dein Text + deine Chat-ID + Benutzername "
        "(Protokollierung, damit der Admin nachvollziehen kann)\n"
        "• <b>Bei Funktionswünschen</b> (/wunsch): dein Wunsch-Text + deine Chat-ID + Benutzername "
        "(Protokollierung, damit der Admin nachvollziehen kann)\n\n"
        "\U0001f465 <b>2. Wer kann meine Daten sehen?</b>\n"
        "Exakt eine Person: der Betreiber dieses Bots (der Administrator). Deine Chat-ID, "
        "deine Beobachtungen und deine Meldungen werden <b>niemals an andere Benutzer "
        "weitergegeben</b>. Andere User sehen von dir nichts. F\u00fcr Administrations-Zwecke "
        "(Fehlersuche, Unterst\u00fctzung) kann der Admin deine Daten einsehen \u2014 aber nur "
        "seine eigene Sicht, kein Austausch zwischen Usern.\n\n"
        "\U0001f3af <b>3. Wof\u00fcr werden die Daten verwendet?</b>\n"
        "Ausschlie\u00dflich f\u00fcr einen Zweck: dir Einsatz-Alarme f\u00fcr deine beobachteten "
        "Orte zustellen zu k\u00f6nnen — inklusive Unwetter-, Pegel-, Strom-, Waldbrand- und Lawinen-Wachen "
        "sowie der j\u00e4hrlichen Sirenenprobe-Erinnerung, Sprachalarmen und pers\u00f6nlichen R\u00fcckblicken, "
        "sofern du die Funktionen nutzt. "
        "Die Wachen fragen \u00f6ffentliche Quellen (Hydro O\u00d6, Netz O\u00d6, GeoSphere, Lawinenwarndienst) "
        "ab \u2014 es geht KEINE deiner Daten an diese Dienste. Keine Analyse, kein "
        "Tracking, kein Profiling, kein Verkauf, keine Weitergabe, keine Werbung. Der Bot kennt "
        "keine E-Mail-Adresse, keine Telefonnummer und keinen echten Namen \u2014 nur was du hier "
        "im Chat eingibst.\n\n"
        "\U0001f4c5 <b>4. Wie lange werden Daten gespeichert?</b>\n"
        "Bis zur L\u00f6schung durch dich oder durch den Admin. Es werden keine automatischen "
        "L\u00f6schfristen durchgesetzt \u2014 die Datenmenge ist minimal (Name, ID, Ort-Liste, "
        "Zeitstempel). Fehlermeldungen bleiben solange in der Protokoll-Datei, bis sie vom "
        "Admin bereinigt werden.\n\n"
        "\U0001f510 <b>5. Wo werden die Daten gespeichert?</b>\n"
        "Auf einem privaten Server in \u00d6sterreich (Raspberry Pi im Heimnetzwerk des "
        "Betreibers). Keine Cloud, keine Drittland\u00fcbertragung, weitergeben tut die Datei "
        "niemand au\u00dfer dem Admin.\n\n"
        "\U0001f5d1\ufe0f <b>6. Wie bekomme ich meine Daten gel\u00f6scht?</b>\n"
        "Ganz einfach selbst: Sende <b>/vergessen</b>. Nach einer Warnung und deiner "
        "Bestätigung wirst du auf die Löschungsliste gesetzt (Zugang pausiert, Daten bleiben "
        "erhalten). Nach <b>2 Wochen</b> fragt der Bot sicherheitshalber nach — erst wenn du "
        "diese letzte Frage erneut mit ja beantwortest, werden Chat-ID, Benutzername, alle "
        "Beobachtungen und dein kompletter Zugang endgültig gelöscht. In der ganzen Zeit kannst "
        "du mit <b>/abbruch</b> abbrechen und bekommst alles zurück. Nach der Löschung kannst du "
        "dich jederzeit neu registrieren. Alternativ geht die Löschung auch über den "
        "Administrator (persönliche Nachricht) \u2014 dann entfernt er deinen kompletten "
        "Eintrag inklusive protokollierter Fehlermeldungen.\n\n"
        "\u2696\ufe0f <b>7. Rechtliche Grundlage</b>\n"
        "Die Verarbeitung beruht auf deiner freiwilligen Nutzung des Bots. Du gibst nur "
        "Daten Preis, die du selbst im Chat eintippst \u2014 es werden keine Daten von "
        "Telegram-Profilen ausgesp\u00e4ht oder von Dritten bezogen. Telegram selbst hat "
        "eigene Datenschutzregeln, die unabh\u00e4ngig von diesem Bot gelten.\n\n"
        "\u26a0\ufe0f <b>8. Verl\u00e4sslichkeit (keine offizielle Alarmierung)</b>\n"
        "Dieser Bot ist ein privates, inoffizielles Projekt und KEIN Teil einer offiziellen "
        "Alarmierungskette. Er liest \u00f6ffentlich zug\u00e4ngliche Seiten aus (Feuerwehr-Eins\u00e4tze "
        "O\u00d6, Wetter-, Pegel-, Strom- und Lawinen-Dienste) \u2014 diese Daten k\u00f6nnen verz\u00f6gert, "
        "unvollst\u00e4ndig oder fehlerhaft sein, und der Bot selbst kann ausfallen. Verlasse dich "
        "im Notfall NIEMALS allein auf den Bot: Sirene, Funk, Pager und der Notruf 122 gehen "
        "immer vor.\n\n"
        "\u2755 <b>Wichtig:</b> Es handelt sich um einen privaten, nicht-kommerziellen Bot "
        "f\u00fcr Feuerwehr-Informationen. Er erhebt keine sensible Daten, keine Gesundheitsdaten, "
        "keine Standortdaten \u2014 nur \u00f6ffentliche Ortsnamen und dein Telegram-Kontext.")
def anleitung_text():
    """Komplette Funktionsweise des Bots — ergänzend zu /hilfe (Befehlsliste)."""
    return (
        "\U0001f692 <b>Feuerwehr-Monitor Bot — Anleitung</b>\n"
        "\U0001f50d <b>Woher kommen die Daten?</b>\n"
        "Der Bot liest live die Einsatzseiten des O\u00d6 Landesfeuerwehrverbands "
        "(einsaetze.ooelfv.at) und die Einsatzhistorie auf einsaetze.at. Alle ~5 Sekunden "
        "wird gepr\u00fcft, ob sich etwas an den laufenden Eins\u00e4tzen \u00e4ndert — "
        "deswegen sind die Meldungen fast in Echtzeit. Es gibt keine offizielle App-Funktion "
        "dafür, der Bot parst die \u00f6ffentlichen Seiten selbst.\n\n"
        "\U0001f514 <b>Wie funktioniert eine Beobachtung?</b>\n"
        "\u2022 <b>/ort &lt;Ort&gt;</b> — Dauerhafte \u00dcberwachung: Jeder Einsatz in diesem Ort "
        "l\u00f6st sofort eine Meldung aus, bis du ihn selbst wieder entfernst.\n"
        "\u2022 <b>/einsatz &lt;Ort&gt;</b> — Tempor\u00e4r: Beobachtet nur den JETZT laufenden Einsatz "
        "an diesem Ort. Nach dem Abschlussbericht verschwindet die Beobachtung automatisch wieder.\n"
        "Passend dazu kriegst du Meldungen, wenn sich der Einsatz \u00e4ndert (z.B. weitere "
        "Feuerwehren r\u00fccken aus, einzelne beenden) und am Ende einen Abschlussbericht "
        "mit Dauer und allen beteiligten Feuerwehren.\n\n"
        "\U0001f4cb <b>Regeln &amp; Limits</b>\n"
        "\u2022 Max. 10 dauerhafte Orts-Beobachtungen pro Benutzer\n"
        "\u2022 Max. 10 tempor\u00e4re Einsatz-Beobachtungen gleichzeitig\n"
        "\u2022 Wer \u00fcber dem Limit weiter /ort oder /einsatz versucht, bekommt zuerst "
        "3 Warnungen — danach wird er f\u00fcr 12 Stunden automatisch gesperrt und danach "
        "wieder automatisch freigeschaltet. Deine Beobachtungen bleiben dabei erhalten.\n"
        "\u2022 Einsatzmeldungen (Übungen/Selbsteins\u00e4tze) z\u00e4hlen bei /statistik nicht mit.\n"
        "\u2022 Der Bot ist privat, dein Zugang ist an deine Telegram-Chat-ID gebunden. "
        "Missbrauch f\u00fchrt zum Ausschluss durch den Admin.\n\n"
        "\U0001f4b0 <b>Kosten:</b> Keine — der Bot l\u00e4uft auf privater Hardware.\n\n"
        "\U0001f527 <b>Problem entdeckt?</b>\n"
        "Mit /fehler &lt;Beschreibung&gt; kannst du Fehler direkt dem Administrator melden — "
        "z.B. fehlender Alarm, falsche Einsatzdaten oder ein Befehl der nicht reagiert. "
        "Die Meldung wird protokolliert und automatisch an den Admin geschickt. "
        "Je genauer die Beschreibung (Ort, Uhrzeit, was passiert ist), desto schneller kann geholfen werden.\n\n"
        "\U0001f4a1 <b>Eine Idee f\u00fcr den Bot?</b>\n"
        "Mit /wunsch &lt;Wunsch&gt; kannst du dem Administrator schreiben, was dir noch fehlt \u2014 "
        "neue Funktionen, \u00c4nderungen oder Verbesserungen. Deine Idee wird protokolliert und direkt "
        "an den Admin geschickt. Der Bot lebt vom Feedback \u2014 sprich es einfach an!\n\n"
        "\U0001f6ab <b>Warum kann man gesperrt werden?</b>\n"
        "Der Bot ist offen f\u00fcr alle, aber keine Spielwiese. Automatisch gesperrt wird, wer...\n"
        "\u2022 ...wiederholt \u00fcber die Limits hinaus /ort oder /einsatz versucht "
        "(3 Warnungen, dann 12 Stunden Pause \u2014 danach geht\'s automatisch weiter),\n"
        "\u2022 ...versucht, den Admin zu entfernen (auch das f\u00fchrt zu einem 24h-Ausschluss),\n"
        "\u2022 ...den Bot sonstwie missbraucht \u2014 daf\u00fcr gibt es die manuelle Admin-Sperre.\n"
        "Tempor\u00e4re Sperren enden von selbst \u2014 deine Beobachtungen und dein Benutzername "
        "bleiben alle erhalten, nichts geht verloren. Es wird nur der Zugriff pausiert.\n\n"
        "\u26a0\ufe0f <b>Verl\u00e4sslichkeit &amp; Gew\u00e4hr:</b>\n"
        "Dieser Bot ist ein privates, inoffizielles Projekt \u2014 keine offizielle Alarmierung! "
        "Er liest \u00f6ffentlich zug\u00e4ngliche Seiten aus und kann dadurch Fehler haben, verz\u00f6gert "
        "sein oder ausfallen (Server-Problem, Datenquellen offline, Parsing-Fehler). Auf den Bot "
        "darf man sich NICHT zu 100 % verlassen: Verpassene oder falsche Meldungen sind m\u00f6glich. "
        "Im Notfall gilt IMMER die offizielle Alarmierung (Sirene, Funk, Pager, Notruf 122) \u2014 "
        "verlasse dich niemals allein auf diesen Bot. Mit /testalarm kannst du jederzeit pr\u00fcfen, "
        "ob die Alarm-Kette bei dir funktioniert. Mit /quellen siehst du, von welchen Seiten die "
        "Daten kommen.\n\n"
        "\u2696\ufe0f <b>Datenschutz &amp; Löschung:</b> Welche Daten dieser Bot speichert, wie "
        "lange und wie du sie löschen lässt — das steht in /datenschutz. Deine Daten kannst "
        "du jederzeit selbst mit /vergessen löschen (mit Bestätigung, 2 Wochen Bedenkzeit "
        "und letzter Nachfrage — jederzeit abbrechbar mit /abbruch).\n\n"
        "\U0001f9ed <b>Alle Befehle</b> findest du mit /hilfe (oder tippe / im Chat).\n"
        "\U0001f512 Ruhezeiten: Mit /stumm bekommst du gar keine Alarme, Befehle funktionieren "
        "weiterhin. Mit /stumm 22-07 richtest du ein Stillfenster ein — im Fenster werden Alarme "
        "gesammelt und morgens als eine Sammel-Meldung zugestellt. Mit /wochen bekommst du "
        "sonntags um 20:00 einen Wochenrückblick deiner Orte. Mit /bezirk &lt;Kürzel&gt; siehst du "
        "die heutigen Einsätze eines ganzen Bezirks (z.B. /bezirk WL), mit /training die "
        f"Übungs-Historie der Heimat-Feuerwehr ({FF_NAME}) und mit /qr_code einen QR-Code zum Weiterschicken des Bots. "
        "Direkte Abfragen nach Einsatzart gehen mit /brand, /technisch (Unfälle, Ölspuren, Türöffnungen), "
        "/personenrettung, /unwetter und /sonstiges — jeweils mit Ort oder Bezirks-Kürzel "
        "(z.B. /brand Lengau oder /brand WL). Mit /umkreis &lt;km&gt; siehst du alle laufenden "
        "Einsätze rund um deine Orte.\n\n"
        "\U0001f4cd <b>Inline-Buttons:</b> Bei Abfragen (/lage, /brand …) hat jeder Einsatz "
        "einen ⏱️-Beobachten-Button (legt die Beobachtung sofort an, mit den gleichen Limits wie "
        "per Befehl), eine 📍-Karte UND einen 🧭-Navigations-Button, der direkt die Route zum "
        "Einsatzort startet. Auch Alarm- und Abschluss-Nachrichten und die Unwetter-Warnungen "
        "kommen mit 📍-Karte und 🧭-Navigation — bei beendeten temporären Beobachtungen zusätzlich "
        "der ⭐-Button, um den Ort dauerhaft zu behalten.\n\n"
        "🌊 <b>Hochwasser-Wache inklusive:</b> Rund um deine beobachteten Orte werden automatisch "
        "Pegel des Hydrographischen Dienstes OÖ im 20-km-Umkreis überwacht (alle 15 Minuten). "
        "Steht ein Pegel auf Alarmstufe, kriegst du sofort eine Meldung — und eine Entwarnung, wenn "
        "sich alles beruhigt. Details anytime mit /pegel.\n\n"
        "⚡ <b>Strom-Wache inklusive:</b> Die Störungskarte des Netzbetreibers (Netz OÖ) wird automatisch "
        "für den Bezirk deiner Orte überwacht — bei Ausfällen kriegst du sofort Bescheid, mit Entwarnung. "
        "Abfragen mit /strom.\n\n"
        "🔥 <b>Waldbrand-Wache inklusive:</b> Aus offiziellen GeoSphere-Wetterdaten wird alle 3 Stunden eine "
        "Gefährdungseinschätzung an deinen Orten berechnet (Trockenheit, Wind, Regen). Abfragen mit /waldbrand.\n\n"
        "❄️ <b>Lawinen-Wache:</b> /lawine zeigt die Lage für ganz OÖ, /lawine <Ort> (z. B. /lawine Gosau) "
        "sagt dir die Gefahr am Berg für einen bestimmten Ort. Automatisch kriegst du eine Lawinenwarnung "
        "NUR, wenn einer deiner beobachteten Orte in einer Lawinen-Zone liegt und dort Stufe 3 (erheblich) "
        "oder mehr gilt. Nur im Winterhalbjahr aktiv.\n\n"
        "\U0001f9ef <b>Sirenenprobe-Wache:</b> /sirene zeigt den nächsten Zivilschutz-Probealarm "
        "(erster Samstag im Oktober, 12:00\u201312:45, bundesweit) samt Signalablauf. Automatische "
        "Erinnerungen: am Abend vorher (18:00) und am Probe-Tag 1 Stunde vorher (11:00).\n\n"
        "🧪 <b>Testalarm:</b> Mit /testalarm prüfst du, ob Alarme bei dir ankommen — ohne echten Einsatz.\n\n"
        "🔊 <b>Sprachalarm (opt-in):</b> /stimme aktivieren und bei jedem neuen Alarm zusätzlich eine "
        "kurze Sprachnachricht bekommen (Ort, Stichwort, Feuerwehren) — praktisch am Lenkrad.\n\n"
        "📊 <b>Rückblick:</b> /rueckblick zeigt deine persönlichen Alarme der letzten Monate.\n\n"
        "\u26c8\ufe0f <b>Unwetter inklusive:</b> Beobachtete Orte werden automatisch auch auf "
        "amtliche Unwetter-Warnungen geprüft (GeoSphere Austria, alle 10 Minuten). Ab Warnstufe 2 "
        "(z.B. starke Gewitter, Sturm, Starkregen) bekommst du sofort eine Meldung — auch wenn "
        "kein Einsatz läuft. Bei /statistik kannst du zusätzlich einen Ort angeben "
        "(z.B. /statistik Lengau).")
FEHLERLOG_FILE = os.path.expanduser("~/.config/fw_bot/fehlermeldungen.log")
FEHLER_MAX_LEN = 1000  # Max. Zeichen pro Fehlermeldung (Spam-Schutz)
WUNSCHLOG_FILE = os.path.expanduser("~/.config/fw_bot/wuensche.log")
WUNSCH_MAX_LEN = 1000  # Max. Zeichen pro Funktionswunsch (Spam-Schutz)

def log_fehlermeldung(cid_str, uname, text):
    """Hängt eine Fehlermeldung des Users an die Log-Datei (einzeilig, timestamp)."""
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_text = text.replace("\n", " | ").strip()
        with open(FEHLERLOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{stamp} | user={cid_str} ({uname}) | {safe_text}\n")
        return True
    except Exception as e:
        logger.error(f"Fehlermeldungs-Log Schreibfehler: {e}")
        return False

def fehlermeldungen_lesen():
    """Liest die letzten 30 Zeilen der Fehlermeldungs-Log (neueste zuletzt)."""
    try:
        with open(FEHLERLOG_FILE, "r", encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f if l.strip()]
        return lines[-30:]
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error(f"Fehlermeldungs-Log Lesefehler: {e}")
        return None

def log_wunsch(cid_str, uname, text):
    """Hängt einen Funktionswunsch des Users an die Log-Datei (einzeilig, timestamp)."""
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_text = text.replace("\n", " | ").strip()
        with open(WUNSCHLOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{stamp} | user={cid_str} ({uname}) | {safe_text}\n")
        return True
    except Exception as e:
        logger.error(f"Wunsch-Log Schreibfehler: {e}")
        return False

def wuensche_lesen():
    """Liest die letzten 30 Zeilen der Wunsch-Log (neueste zuletzt)."""
    try:
        with open(WUNSCHLOG_FILE, "r", encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f if l.strip()]
        return lines[-30:]
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error(f"Wunsch-Log Lesefehler: {e}")
        return None

LOESCH_FILE = os.path.expanduser("~/.config/fw_bot/loeschungen.json")
LOESCH_DELAY_HOURS = 336  # Sicherheitsfrist: erst 14 Tage (2 Wochen) nach Bestätigung kommt die letzte Nachfrage — endgültig wird erst nach der zweiten ja-Bestätigung gelöscht
LOESCH_REASK_GRACE_HOURS = 72  # Zeitfenster für die ja-Bestätigung nach der letzten Nachfrage — sonst Auto-Abbruch + Wiederherstellung

def load_loeschungen():
    try:
        with open(LOESCH_FILE, "r") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {}
        return d
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"Lösch-Anträge Lesefehler: {e}")
        return {}

def save_loeschungen(d):
    try:
        with open(LOESCH_FILE, "w") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Lösch-Anträge Schreibfehler: {e}")

def backup_user_data(cid_str):
    """Snapshots User-Eintrag + Watch-State in die Löschungs-Datei (Wiederherstellung bis zur endgültigen Löschung)."""
    ud = users["users"].get(cid_str, {})
    state_file = os.path.join(STATE_DIR, f"user_{cid_str}.json")
    state = None
    try:
        with open(state_file, "r") as f:
            state = json.load(f)
    except Exception:
        state = None
    return {
        "user_data": ud,
        "state": state,
        "requested_at": datetime.now().isoformat(),
        "delete_at": (datetime.now() + timedelta(hours=LOESCH_DELAY_HOURS)).isoformat(),
        "confirmed_by_user": True,
    }

def restore_user_data(cid_str, backup):
    """Stellt User + Zustand aus dem Backup wieder her (nach Abbruch der Löschung)."""
    try:
        users["users"][cid_str] = backup.get("user_data", {
            "username": "", "is_admin": False, "registered": True,
            "orte": [], "einsatz_watches": [],
            "added_at": datetime.now().isoformat(),
        })
        save_users(users)
        st = backup.get("state")
        if st:
            try:
                with open(os.path.join(STATE_DIR, f"user_{cid_str}.json"), "w") as f:
                    json.dump(st, f, ensure_ascii=False)
            except Exception:
                pass
        return True
    except Exception as e:
        logger.error(f"Restore fehlgeschlagen für {cid_str}: {e}")
        return False

def execute_delete(cid_str):
    """Endgültige Löschung: User aus users.json + State-Datei löschen."""
    try:
        users["users"].pop(cid_str, None)
        save_users(users)
        state_file = os.path.join(STATE_DIR, f"user_{cid_str}.json")
        if os.path.exists(state_file):
            os.remove(state_file)
        logger.info(f"Endgültige Löschung ausgeführt: {cid_str}")
        return True
    except Exception as e:
        logger.error(f"Endgültige Löschung fehlgeschlagen für {cid_str}: {e}")
        return False

def check_user_removals():
    """Lösch-Wächter: vergleicht users.json gegen den Snapshot vom Vorzyklus.
    Verschwindet ein bekannter User (Name+Orte bekannt), kriegt der Admin sofort
    eine Info — egal ob via /vergessen, Admin-/entfernen oder externen Edit."""
    try:
        with open(USERS_FILE, "r") as f:
            cur = json.load(f).get("users", {})
    except Exception as e:
        logger.error(f"Lösch-Wächter: users.json unlesbar: {e}")
        return
    try:
        with open(USER_SNAPSHOT_FILE, "r") as f:
            prev = json.load(f)
    except Exception:
        prev = {}
    if prev:
        gone = {k: v for k, v in prev.items() if k not in cur}
        for cid_str, ud in gone.items():
            name = ud.get("username") or "?"
            orte = ud.get("orte") or []
            orte_s = ", ".join(orte) if orte else "keine"
            logger.warning(f"LOESCH-WACHTER: User verschwunden: {cid_str} ({name})")
            send_to(ADMIN_ID, (
                f"\U0001f4e4 <b>Benutzer gel\u00f6scht</b>\n"
                f"{name} (ID {cid_str}) ist aus der Benutzerliste verschwunden "
                f"(Selbst-L\u00f6schung oder Admin-Entfernung).\n"
                f"Beobachtete Orte: {orte_s}\n"
                f"Zur\u00fcck per /registrieren jederzeit m\u00f6glich."))
    if prev != cur:
        try:
            with open(USER_SNAPSHOT_FILE, "w") as f:
                json.dump(cur, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Lösch-Wächter: Snapshot nicht schreibbar: {e}")

def loesch_nachfrage_stellen(cid_str, at, alter_days):
    """Stellt dem User die letzte Nachfrage nach der 2-Wochen-Frist und markiert
    den Antrag als 'Nachfrage gestellt' (reask_at + Token). Admin kriegt Info."""
    token2 = str(datetime.now().timestamp())[-4:]
    at["reask_at"] = datetime.now().isoformat()
    at["reask_token"] = token2
    antraege = load_loeschungen()
    antraege[cid_str] = at
    save_loeschungen(antraege)
    logger.warning(f"LOESCH-NACHFRAGE gestellt: {cid_str} (nach {alter_days} Tagen) — User antwortet auf ja/abbruch")
    send_to(int(cid_str), (
        f"\u23f3 <b>Letzte Nachfrage zu deiner L\u00f6schung</b>\n\n"
        f"Vor {alter_days} Tagen hast du die L\u00f6schung deines Zugangs best\u00e4tigt.\n\n"
        f"M\u00f6chtest du wirklich ALLES endg\u00fcltig gel\u00f6scht bekommen "
        f"(Benutzername, Beobachtungen, kompletter Zugang)?\n\n"
        f"<b>Ja, endg\u00fcltig l\u00f6schen:</b>\n"
        f"<code>/vergessen ja {token2}</code>\n\n"
        f"<b>Nein, abbrechen und alles zur\u00fcckholen:</b>\n"
        f"<code>/abbruch</code>\n\n"
        f"\u2139\ufe0f Antwortest du innerhalb von {LOESCH_REASK_GRACE_HOURS} Stunden nicht, "
        f"brechen wir die L\u00f6schung sicherheitshalber automatisch ab \u2014 dann ist alles wieder da."))
    try:
        uname = (at.get("user_data", {}) or {}).get("username") or "?"
        send_to(ADMIN_ID, (
            f"\U0001f5d1\ufe0f <b>Letzte Nachfrage gestellt</b>\n"
            f"User: {uname} (ID {cid_str}) \u2014 nach {alter_days} Tagen Wartezeit.\n"
            f"Best\u00e4tigt er jetzt mit ja, wird endg\u00fcltig gel\u00f6scht. Antwortet er innerhalb "
            f"{LOESCH_REASK_GRACE_HOURS}h nicht, wird automatisch abgebrochen + restauriert."))
    except Exception:
        pass

def check_loesch_nachfragen():
    """Auto-Abbruch-Komponente: 2 Wochen nach Bestätigung wird die letzte Nachfrage
    gestellt (siehe loesch_nachfrage_stellen). Antwortet der User auf die Nachfrage
    nicht innerhalb des Zeitfensters, wird die Löschung automatisch abgebrochen und
    der User vollständig restauriert (Sicherheitsnetz)."""
    antraege = load_loeschungen()
    if not antraege:
        return
    now = datetime.now()
    for cid_str in list(antraege.keys()):
        at = antraege[cid_str]
        try:
            del_at = datetime.fromisoformat(at["delete_at"])
        except Exception:
            continue
        reask_at_s = at.get("reask_at")
        if reask_at_s:
            # Nachfrage wurde schon gestellt: auf ja warten, sonst Auto-Abbruch
            try:
                reask_at = datetime.fromisoformat(reask_at_s)
            except Exception:
                continue
            if (now - reask_at).total_seconds() > LOESCH_REASK_GRACE_HOURS * 3600:
                grace = at.get("reask_grace_hours", LOESCH_REASK_GRACE_HOURS)
                if (now - reask_at).total_seconds() > grace * 3600:
                    antraege.pop(cid_str, None)
                    save_loeschungen(antraege)
                    ok = restore_user_data(cid_str, at)
                    if ok:
                        logger.warning(f"LOESCH-AUTOABBRUCH: keine Reaktion auf Nachfrage, restauriert: {cid_str}")
                        send_to(int(cid_str), (
                            "\u2705 <b>L\u00f6schung automatisch abgebrochen.</b>\n\n"
                            "Du hast auf die letzte Nachfrage nicht reagiert \u2014 "
                            "sicherheitshalber wurde die L\u00f6schung abgebrochen.\n"
                            "Dein Benutzername, deine Beobachtungen und dein kompletter Zugang sind wiederhergestellt. "
                            "Du bekommst ab sofort wieder deine Alarme. \U0001f692"))
                        try:
                            uname = (at.get("user_data", {}) or {}).get("username") or "?"
                            send_to(ADMIN_ID, (
                                f"\u2139\ufe0f L\u00f6schung von {uname} (ID {cid_str}) automatisch abgebrochen "
                                f"(keine Reaktion auf die letzte Nachfrage) \u2014 User vollst\u00e4ndig restauriert."))
                        except Exception:
                            pass
                    else:
                        logger.error(f"LOESCH-AUTOABBRUCH fehlgeschlagen für {cid_str} — Admin prüfen!")
                        send_to(ADMIN_ID, f"\u26a0\ufe0f Auto-Abbruch der L\u00f6schung von {cid_str} FEHLGESCHLAGEN \u2014 bitte pr\u00fcfen.")
            continue
        alter_tage = (now - del_at).total_seconds() / 3600 / 24
        if alter_tage >= 14:
            loesch_nachfrage_stellen(cid_str, at, round(alter_tage))

# ═══ Pegel-/Hochwasser-Wache (Hydro OÖ KiWIS-Daten) ═══
PEGEL_LAYER_URL = "https://hydro.ooe.gv.at/daten/internet/layers/9/index.json"
PEGEL_CHECK_INTERVAL_MIN = 15  # Pegel-Check alle 15 Minuten
PEGEL_KILOMETER_UMKREIS = 20  # Stationen im Umkreis eines beobachteten Orts
PEGEL_STATE_FILE = os.path.expanduser("~/.config/fw_bot/state/pegel_state.json")

def _pegel_alarm_label(code):
    """AlarmClassification-Code → Klartext. ##NOAL## = kein Alarm; sonst Stufentext."""
    if not code or code == "##NOAL##":
        return None
    c = str(code).strip("#")
    m = re.fullmatch(r"AL(\d)", c)
    if m:
        return f"Alarmstufe {m.group(1)}"
    return c

def _load_pegel_state():
    try:
        with open(PEGEL_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_pegel_state(d):
    try:
        os.makedirs(os.path.dirname(PEGEL_STATE_FILE), exist_ok=True)
        with open(PEGEL_STATE_FILE, "w") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Pegel-State Schreibfehler: {e}")

def _pegel_utm_to_wgs84():
    """Transformer BMN M34 (EPSG:31258) → WGS84. OÖ-Koordinaten sind M34, kein UTM!"""
    global _PegelTransformer
    if _PegelTransformer is None:
        return None
    try:
        return _PegelTransformer.from_crs("EPSG:31258", "EPSG:4326", always_xy=True)
    except Exception:
        return None

def fetch_pegel_aktiv():
    """Holt die Alarmpegel-Daten und injiziert station_latitude/longitude (aus BMN M34).
    Der Live-Layer liefert nur station_carteasting/cartnorthing (M34) — ohne Wandlung wäre
    der Umkreis-Filter leer (Bug am 13.09. entdeckt: Wache lief mit 0 Stationen)."""
    try:
        req = urllib.request.Request(PEGEL_LAYER_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        if not isinstance(data, list):
            return []
        tr = _pegel_utm_to_wgs84()
        if tr:
            for s in data:
                try:
                    lon, lat = tr.transform(float(s.get("station_carteasting") or 0),
                                            float(s.get("station_cartnorthing") or 0))
                    s["station_latitude"] = str(lat)
                    s["station_longitude"] = str(lon)
                except (TypeError, ValueError, KeyError):
                    pass
        return data
    except Exception as e:
        logger.debug(f"Pegel-Abruf fehlgeschlagen: {e}")
        return []

def _pegel_nahe_stationen(ort, alle, koords, umkreis_km):
    """Stationen im Umkreis eines Orts (via _ort_koordinaten + Haversine)."""
    lat, lon = koords
    treff = []
    for s in alle:
        try:
            slat = float(s.get("station_latitude") or 0)
            slon = float(s.get("station_longitude") or 0)
        except (TypeError, ValueError):
            continue
        if not slat or not slon:
            continue
        if _haversine_km(lat, lon, slat, slon) <= umkreis_km:
            treff.append(s)
    return treff

def pegel_text_fuer_orte(orte):
    """Formatierter Pegel-Report für eine Liste von Orten (für /pegel)."""
    alle = fetch_pegel_aktiv()
    if not alle:
        return None
    bloecke = []
    for ort in orte:
        coords = _ort_koordinaten(ort)
        if not coords:
            continue
        naehe = _pegel_nahe_stationen(ort, alle, coords, PEGEL_KILOMETER_UMKREIS)
        if not naehe:
            continue
        ort_anzeige = _ort_anzeige_cap(ort)
        z = [f"<b>Pegel um {esc(ort_anzeige)} ({PEGEL_KILOMETER_UMKREIS} km):</b>"]
        for s in sorted(naehe, key=lambda x: (str(x.get("river_name") or ""), str(x.get("station_name") or ""))):
            stufe = _pegel_alarm_label(s.get("AlarmClassification"))
            wert = s.get("ts_value")
            einheit = s.get("ts_unitsymbol") or ""
            zeit = (str(s.get("timestamp") or ""))[11:16]
            zeile = f"• {esc(s.get('station_name') or '?')} ({esc(s.get('river_name') or '?')}): {esc(str(wert))} {esc(einheit)} um {esc(zeit)} Uhr"
            if stufe:
                zeile += f" — ⚠️ <b>{esc(stufe)}</b>"
            z.append(zeile)
        bloecke.append("\n".join(z))
    return "\n\n".join(bloecke) if bloecke else None

def check_pegel_for_users(users):
    """Läuft im Haupt-Loop: Pegel nahe beobachteter Orte prüfen.
    Alarm wenn AlarmClassification != ##NOAL## (Neu/Stufenwechsel, Dedup über pegel_state.json)."""
    now = time.time()
    state = _load_pegel_state()
    if now - state.get("last_check", 0) < PEGEL_CHECK_INTERVAL_MIN * 60:
        return
    state["last_check"] = now
    orte_map = {}
    for cid, ud in users.get("users", {}).items():
        if ud.get("silent"):
            continue
        for ort in ud.get("orte", []):
            orte_map.setdefault(ort.lower().strip(), set()).add(cid)
    if not orte_map:
        _save_pegel_state(state)
        return
    alle = fetch_pegel_aktiv()
    if not alle:
        _save_pegel_state(state)
        return
    seen = dict(state.get("seen", {}))
    aktive_keys = set()
    for ort_key, chat_ids in orte_map.items():
        coords = _ort_koordinaten(ort_key)
        if not coords:
            continue
        naehe = _pegel_nahe_stationen(ort_key, alle, coords, PEGEL_KILOMETER_UMKREIS)
        ort_anzeige = _ort_anzeige_cap(ort_key)
        for s in naehe:
            stufe = _pegel_alarm_label(s.get("AlarmClassification"))
            skey = f"pegel:{s.get('station_no')}:{ort_key}"
            if stufe:
                aktive_keys.add(skey)
                if seen.get(skey) != stufe:
                    seen[skey] = stufe
                    msg = (f"\U0001f30a <b>Pegel-Alarm — {esc(ort_anzeige)}</b>\n"
                           f"{esc(s.get('station_name') or '?')} ({esc(s.get('river_name') or '?')}): "
                           f"<b>{esc(str(s.get('ts_value')))} {esc(s.get('ts_unitsymbol') or '')}</b>\n"
                           f"{esc(stufe)} · Stand {esc((str(s.get('timestamp')) or '')[11:16])} Uhr")
                    kb_p = {"inline_keyboard": [[btn_karte_url(ort_anzeige), btn_navi_url(ort_anzeige)]]}
                    for cid in chat_ids:
                        ud = users.get("users", {}).get(str(cid), {})
                        if ud.get("silent"):
                            continue
                        send_to(cid, msg, reply_markup=kb_p)
                    send_to(ADMIN_ID, msg, reply_markup=kb_p)
            else:
                if skey in seen:
                    seen.pop(skey, None)
                    msg = (f"\U0001f513 <b>Pegel beruhigt — {esc(ort_anzeige)}</b>\n"
                           f"{esc(s.get('station_name') or '?')} ({esc(s.get('river_name') or '?')}): "
                           f"{esc(str(s.get('ts_value')))} {esc(s.get('ts_unitsymbol') or '')} — keine Alarmstufe mehr aktiv.")
                    for cid in chat_ids:
                        ud = users.get("users", {}).get(str(cid), {})
                        if ud.get("silent"):
                            continue
                        send_to(cid, msg)
                    send_to(ADMIN_ID, msg)
    seen = {k: v for k, v in seen.items() if k in aktive_keys}
    state["seen"] = seen
    _save_pegel_state(state)

# ═══ Sprachnachricht-Alarm (Piper TTS, opt-in via /stimme) ═══
PIPER_BIN = os.path.expanduser("~/.local/bin/piper")
PIPER_MODEL = os.path.expanduser("~/.config/fw_bot/voice/thorsten-high.onnx")
PIPER_TIMEOUT_S = 90

def piper_verfuegbar():
    return os.path.exists(PIPER_BIN) and os.path.exists(PIPER_MODEL)

def tts_text_erzeugen(text):
    """Text → Piper-WAV → ffmpeg-OGG/Opus. Gibt bytes oder None."""
    try:
        if not piper_verfuegbar():
            return None
        wav_path = "/tmp/fw_tts_%d.wav" % os.getpid()
        try:
            subprocess.run(
                [PIPER_BIN, "-m", PIPER_MODEL, "-f", wav_path],
                input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=PIPER_TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            logger.warning("Piper-Timeout")
            return None
        if not (os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000):
            return None
        ogg_path = wav_path.replace(".wav", ".ogg")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", wav_path,
                 "-codec:a", "libopus", "-b:a", "32k", "-vbr", "on", "-compression_level", "10", ogg_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
        except subprocess.TimeoutExpired:
            ogg_path = None
        data = None
        if ogg_path and os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 500:
            with open(ogg_path, "rb") as f:
                data = f.read()
        for pth in (wav_path, (ogg_path or "")):
            try:
                if pth and os.path.exists(pth):
                    os.remove(pth)
            except Exception:
                pass
        return (data if data and len(data) > 1000 else None)
    except Exception as e:
        logger.error(f"TTS Fehler: {e}")
        return None

def send_voice_ogg(chat_id, ogg_bytes):
    """sendVoice mit OGG/Opus (multipart, wie send_photo)."""
    if not BOT_TOKEN:
        return False
    boundary = "fwvoice" + str(os.getpid()) + str(int(time.time() * 1000))
    parts = [
        ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n" + str(chat_id) + "\r\n").encode(),
        ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"voice\"; filename=\"alarm.ogg\"\r\nContent-Type: audio/ogg\r\n\r\n").encode(),
        ogg_bytes,
        ("\r\n--" + boundary + "--\r\n").encode(),
    ]
    body = b"".join(parts)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=25)
        return True
    except Exception as e:
        logger.error(f"sendVoice Fehler (ID {chat_id}): {e}")
        return False

def alarm_sprechtext(e, fw_count, namen):
    """Kurzer klarer Sprechtext für den Alarm."""
    ort = (e.get("ort") or "").strip()
    stichwort = (e.get("stichwort") or "").strip()
    return f"Achtung Einsatz. {ort}. {stichwort}. {fw_count} Feuerwehren: {namen}."

def send_stimme_wenn_aktiv(chat_id, user_data, e, fw_count, namen):
    """Wenn User /stimme aktiv hat: Sprachnachricht zum Alarm (best effort, nie blockierend)."""
    if not user_data.get("stimme"):
        return
    try:
        text = alarm_sprechtext(e, fw_count, namen)
        ogg = tts_text_erzeugen(text)
        if ogg:
            send_voice_ogg(chat_id, ogg)
            logger.info(f"Sprachnachricht gesendet an {chat_id}")
        else:
            logger.warning(f"TTS Erzeugung fehlgeschlagen für {chat_id} — nur Text")
    except Exception as tts_err:
        logger.error(f"Sprachnachricht Fehler {chat_id}: {tts_err}")

# ═══ Stromausfall-Wache (Netz OÖ Versorgungsstatus, Gast-Login) ═══
STROM_REST = "https://status.netzooe.at/i1-mobileproxy/service/rest"
STROM_SITE = "{A1572015-4D5B-11E3-8058-005056A23A2E}"
STROM_QID_BEZIRKE = "{F7A2442A-A542-11E3-A0F1-005056A23A2E}"
STROM_QID_GEMEINDEN = "{5CB81F29-C776-11E6-98F7-005056A23A2E}"
STROM_CHECK_INTERVAL_MIN = 15
STROM_STATE_FILE = os.path.expanduser("~/.config/fw_bot/state/strom_state.json")
# Ort → Netz-OÖ-Bezirk (für die Störungskarte):
ORT_BEZIRK = {
    "offenhausen": "Wels-Land", "lambach": "Wels-Land", "gaspoltshofen": "Grieskirchen",
    "bad schallerbach": "Grieskirchen", "grieskirchen": "Grieskirchen", "gunskirchen": "Wels-Land",
    "wels": "Wels", "thalheim bei wels": "Wels-Land", "buchkirchen": "Wels-Land",
    "marchtrenk": "Wels-Land", "eferding": "Eferding", "vöcklabruck": "Vöcklabruck",
    "attnang-puchheim": "Vöcklabruck", "schwanenstadt": "Vöcklabruck", "lengau": "Braunau am Inn",
    "st. martin im innkreis": "Ried im Innkreis",
}

# Orte, die NICHT im Netz-OÖ-Versorgungsgebiet liegen (eigene Netzbetreiber mit
# eigenen Gebieten). Die Störungskarte deckt sie NICHT ab — der Bot weist beim
# Hinzufügen aktiv darauf hin. Details/Begründung: docs/NETZBETREIBER.md im Repo.
# Nur SICHERE Zuordnungen (Städte-Gebiete); 'Teile von'-Gemeinden (Buchkirchen,
# Gunskirchen, Marchtrenk, Steinhaus — Grenze eww/Netz OÖ unklar) bewusst NICHT
# markiert, um falsche Warnungen zu vermeiden.
STROM_FREMD_GEBIETE = {
    "linz": "LINZ NETZ (Linz AG)",
    "wels": "eww Wels",
    "thalheim bei wels": "eww Wels",
    "ried im innkreis": "Energie Ried",
    "ried": "Energie Ried",
}

def _strom_fremd_hinweis(ort):
    """Hinweistext für einen Ort außerhalb des Netz-OÖ-Versorgungsgebiets (oder '')."""
    betreiber = STROM_FREMD_GEBIETE.get(ort.lower().strip())
    if not betreiber:
        return ""
    return ("\n⚡ <b>Hinweis zu Strom-Daten:</b> '" + esc(ort) + "' gehört zum Versorgungsgebiet von "
            "<b>" + esc(betreiber) + "</b> — nicht zu Netz OÖ. Stromausfall-Überwachung ist für diesen Ort "
            "nicht möglich, da der Betreiber keine abfragbaren Störungsdaten veröffentlicht. "
            "Einsatz-, Unwetter- und alle übrigen Wachen funktionieren normal.")

def _load_strom_state():
    try:
        with open(STROM_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_strom_state(state):
    try:
        os.makedirs(os.path.dirname(STROM_STATE_FILE), exist_ok=True)
        with open(STROM_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Strom-State save Fehler: {e}")

def strom_fetch_bezirke():
    """Netz OÖ Störungskarte: Gast-Login + Bezirke-Query.
    Rückgabe: {bezirk_name: {"farbe": ..., "betroffen": int, "info": str}} oder None bei Fehler."""
    try:
        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        hdr = {"User-Agent": UA_NOMINATIM, "Content-Type": "application/json",
               "Origin": "https://status.netzooe.at", "Referer": "https://status.netzooe.at/"}
        pl = {"loginname": "netzWebGast", "password": None, "siteID": STROM_SITE, "appName": "netzstatus"}
        op.open(urllib.request.Request(STROM_REST + "/sessionCreateTokenStore",
            data=json.dumps(pl).encode(), headers=hdr), timeout=20)
        d2 = json.loads(op.open(urllib.request.Request(STROM_REST + "/getSessionToken",
            data=b"{}", headers=hdr), timeout=20).read().decode())
        req = urllib.request.Request(STROM_REST + "/queryExecuteComplete",
            data=json.dumps({"sessionToken": d2["token"], "siteID": STROM_SITE,
                             "queryID": STROM_QID_BEZIRKE, "queryParameter": None,
                             "loginname": "netzWebGast", "sideQuery": False}).encode(), headers=hdr)
        dd = json.loads(op.open(req, timeout=30).read().decode())
        cached = dd.get("queryResultCached", "")
        if not cached:
            return None
        j1 = json.loads(cached[:cached.index("}") + 1])
        rest = cached[cached.index("}") + 1:]
        j2 = json.loads(rest)
        erg = {}
        for row in j2.get("rows", []):
            cell = row.get("cell", [])
            if len(cell) < 4:
                continue
            name = unescape(str(cell[0]))
            betroffen_txt = unescape(str(cell[3]))
            m = re.search(r"betroffen/gesamt\):\s*([0-9.]+)", betroffen_txt.replace("\u00a0", " "))
            betroffen = int(m.group(1).replace(".", "")) if m else 0
            erg[name] = {"farbe": cell[1], "betroffen": betroffen, "info": betroffen_txt}
        return erg
    except Exception as e:
        logger.debug(f"Strom-Karte Fehler: {e}")
        return None

def strom_text_fuer_orte(orte):
    """/strom-Befehl: aktueller Störungsstatus für die Bezirke der User-Orte.
    Orte außerhalb des Netz-OÖ-Gebiets (eigene Netzbetreiber) bekommen einen klaren
    Hinweis statt 'keine Daten' — die übrigen Orte des Users liefern normal Daten."""
    alle = strom_fetch_bezirke()
    if not alle:
        return None
    bez = sorted({ORT_BEZIRK.get(o.lower().strip(), o.title()) for o in orte
                  if o.lower().strip() not in STROM_FREMD_GEBIETE})
    fremd = [o for o in orte if o.lower().strip() in STROM_FREMD_GEBIETE]
    zeilen = []
    for b in bez:
        hit = None
        for name, d in alle.items():
            if name.lower() == b.lower():
                hit = (name, d)
                break
        if hit:
            name, d = hit
            icon = "✅" if d["betroffen"] == 0 else "⚡"
            zeilen.append(f"{icon} <b>{esc(name)}</b> — {d['betroffen']} Kunden ohne Versorgung")
        else:
            zeilen.append(f"❓ {esc(b)} — keine Daten")
    for o in fremd:
        betreiber = STROM_FREMD_GEBIETE[o.lower().strip()]
        zeilen.append(f"🚫 {esc(o.title())} — Strom-Daten nicht verfügbar (Versorgungsgebiet {esc(betreiber)}, nicht Netz OÖ)")
    return "\n".join(zeilen)

def check_strom_for_users(users):
    """Strom-Wache: Meldung, wenn in einem Bezirk mit beobachtetem Ort >0 Kunden ohne Strom (Dedup 30 Min)."""
    now = time.time()
    state = _load_strom_state()
    if now - state.get("last_check", 0) < STROM_CHECK_INTERVAL_MIN * 60:
        return
    state["last_check"] = now
    bez_map = {}
    for cid, ud in users.get("users", {}).items():
        if not ud.get("registered") or ud.get("silent"):
            continue
        for ort in ud.get("orte", []):
            # Orte außerhalb des Netz-OÖ-Versorgungsgebiets: keine Strom-Wache möglich
            if ort.lower().strip() in STROM_FREMD_GEBIETE:
                continue
            b = ORT_BEZIRK.get(ort.lower().strip())
            if b:
                bez_map.setdefault(b, set()).add(cid)
    if not bez_map:
        _save_strom_state(state)
        return
    alle = strom_fetch_bezirke()
    if not alle:
        _save_strom_state(state)
        return
    seen = dict(state.get("störungen", {}))
    aktive = set()
    gesendet = 0
    for b, chat_ids in bez_map.items():
        hit = next((d for name, d in alle.items() if name.lower() == b.lower()), None)
        if hit and hit["betroffen"] > 0:
            aktive.add(b)
            if seen.get(b) != hit["betroffen"]:
                seen[b] = hit["betroffen"]
                msg = ("\u26a1 <b>Stromausfall-Wache — " + esc(b) + "</b>\n"
                       "Ohne Versorgung: <b>" + str(hit["betroffen"]) + " Kunden</b>\n"
                       "Quelle: Netz O\u00d6 St\u00f6rungskarte\n"
                       "\u2139\ufe0f Bei Aufz\u00fcgen, BMA oder Arbeitsstellen beachten.")
                for cid in chat_ids:
                    send_to(cid, msg)
                    gesendet += 1
        # Entwarnung:
        elif b in seen and hit is not None and hit["betroffen"] == 0:
            del seen[b]
            msg = ("\u2705 <b>Versorgung wieder her — " + esc(b) + "</b>\n"
                   "Alle Kunden wieder am Netz.")
            for cid in chat_ids:
                send_to(cid, msg)
                gesendet += 1
    state["störungen"] = seen
    _save_strom_state(state)
    if gesendet:
        logger.info(f"Strom-Wache: {gesendet} Meldungen versendet")

# ═══ Waldbrand-Wache (GeoSphere NWP am Ort → eigene Gefährdung) ═══
WALDBRAND_CHECK_INTERVAL_H = 3
WALDBRAND_STATE_FILE = os.path.expanduser("~/.config/fw_bot/state/waldbrand_state.json")
GEOSPHERE_TSS = "https://dataset.api.hub.geosphere.at/v1/timeseries/forecast/nwp-v2-1h-1km"

def _load_waldbrand_state():
    try:
        with open(WALDBRAND_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_waldbrand_state(state):
    try:
        os.makedirs(os.path.dirname(WALDBRAND_STATE_FILE), exist_ok=True)
        with open(WALDBRAND_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Waldbrand-State save Fehler: {e}")

def waldbrand_fetch_punkt(lat, lon):
    """GeoSphere-NWP-Forecast (T/Feuchte/Böen/Regen) am Punkt. Rückgabe dict oder None."""
    try:
        import urllib.parse
        params = "2t,2r,10fg,rain"
        qs = (f"?parameters={params}&lat_lon={urllib.parse.quote(str(lat))},{urllib.parse.quote(str(lon))}"
              f"&start=" + datetime.utcnow().strftime("%Y-%m-%dT%H:00Z"))
        u = GEOSPHERE_TSS + qs + "&end=" + (datetime.utcnow() + timedelta(hours=12)).strftime("%Y-%m-%dT%H:00Z")
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA_NOMINATIM}), timeout=25)
        d = json.loads(r.read().decode())
        feats = d.get("features", [])
        if not feats:
            return None
        pp = feats[0].get("properties", {}).get("parameters", {})
        def vals(k):
            arr = [v for v in (pp.get(k, {}).get("data") or []) if v is not None]
            return arr if (arr := arr) else []
        t = vals("2t"); rh = vals("2r"); fg = vals("10fg"); rn = vals("rain")
        if not t or not rh:
            return None
        return {"t_max": max(t), "rh_min": min(rh), "boeen_max": max(fg) if fg else 0.0,
                "rain_12h": round(sum(rn), 1) if rn else 0.0}
    except Exception as e:
        logger.debug(f"Waldbrand-Abfrage Fehler: {e}")
        return None

def waldbrand_stufe(d):
    """Eigene, dokumentierte Gefährdungsabschätzung aus GeoSphere-Wetter (kein offizieller FWI!):
    0 unauffällig / 1 erhöht / 2 kritisch."""
    score = 0
    if d["rh_min"] < 40: score += 1
    if d["rh_min"] < 30: score += 1
    if d["t_max"] >= 25: score += 1
    if d["rain_12h"] < 1.0: score += 2
    elif d["rain_12h"] < 3.0: score += 1
    if d["boeen_max"] >= 12.5: score += 1
    if score >= 4: return 2
    if score >= 2: return 1
    return 0

STUFE_TXT = {0: "unauff\u00e4llig", 1: "erh\u00f6ht", 2: "hoch"}

def check_waldbrand_for_users(users):
    """Waldbrand-Wache: max. Stufe über alle Orte je User; Meldung bei Wechsel auf 1/2 (3-h-Takt)."""
    now = time.time()
    state = _load_waldbrand_state()
    if now - state.get("last_check", 0) < WALDBRAND_CHECK_INTERVAL_H * 3600:
        return
    state["last_check"] = now
    ort_stufen = {}
    chat_map = {}
    for cid, ud in users.get("users", {}).items():
        if not ud.get("registered") or ud.get("silent"):
            continue
        for ort in ud.get("orte", []):
            okey = ort.lower().strip()
            chat_map.setdefault(okey, set()).add(cid)
            if okey in ort_stufen:
                continue
            coords = _ort_koordinaten(okey)
            if not coords:
                continue
            w = waldbrand_fetch_punkt(coords[0], coords[1])
            if not w:
                continue
            ort_stufen[okey] = (waldbrand_stufe(w), w)
    gesendet = 0
    stufen = dict(state.get("stufen") or {})
    state["stufen"] = stufen
    for okey, (stufe, w) in ort_stufen.items():
        alt = stufen.get(okey, 0)
        stufen[okey] = stufe
        if stufe != alt and stufe >= 1:
            ort_anz = _ort_anzeige_cap(okey)
            icon = "\U0001f9ea" if stufe == 1 else "\U0001f525"
            txt = (f"{icon} <b>Waldbrandgefahr {STUFE_TXT[stufe]} — {esc(ort_anz)}</b>\n"
                   f"Trockenheit + Wind erh\u00f6hen das Risiko (eigene Wetter-Absch\u00e4tzung, GeoSphere-Daten).\n"
                   f"12-h-Regen: {w['rain_12h']} mm \u2022 Luftfeuchte min: {w['rh_min']} % \u2022 B\u00f6en: {round(w['boeen_max']*3.6)} km/h\n"
                   f"Achtung bei B\u00f6schungsbr\u00e4nden, Stoppelbr\u00e4nden, hei\u00dfen Tagen.")
            for cid in chat_map[okey]:
                send_to(cid, txt)
                gesendet += 1
        elif stufe == 0 and alt >= 1:
            for cid in chat_map[okey]:
                send_to(cid, f"\U0001f343 <b>Waldbrandgefahr wieder normal — {_ort_anzeige_cap(okey)}</b>")
                gesendet += 1
    _save_waldbrand_state(state)
    if gesendet:
        logger.info(f"Waldbrand-Wache: {gesendet} Meldungen")

def waldbrand_text_fuer_orte(orte):
    """/waldbrand-Befehl: aktuelle Stufen am Ort (sofortige Abfrage)."""
    zeilen = []
    for ort in orte:
        okey = ort.lower().strip()
        coords = _ort_koordinaten(okey)
        if not coords:
            zeilen.append(f"❓ {esc(ort)} — unbekannter Ort")
            continue
        w = waldbrand_fetch_punkt(coords[0], coords[1])
        if not w:
            zeilen.append(f"❓ {esc(ort)} — keine Daten")
            continue
        st = waldbrand_stufe(w)
        icon = "\u2705" if st == 0 else ("\U0001f9ea" if st == 1 else "\U0001f525")
        zeilen.append(f"{icon} <b>{esc(ort.title())}</b>: Gefahr {STUFE_TXT[st]} "
                      f"(Feuchte {w['rh_min']} %, T max {round(w['t_max'])} \u00b0C, B\u00f6en {round(w['boeen_max']*3.6)} km/h, 12-h-Regen {w['rain_12h']} mm)")
    return "\n".join(zeilen)

# ═══ Bergwacht/Lawinen-Abfrage (/lawine — Lawinenwarndienst OÖ AT-04) ═══
LAWINEN_BASE = "https://static.lawinen-warnung.eu/bulletins"
LAWINEN_REGION = "AT-04"  # OÖ (Totes Gebirge, Pyhrgas, Dachstein, Sengsengebirge …)

def lawine_status(tage_zurueck=1):
    """Aktuelles OÖ-Lawinenbulletin (CAAML). Saison aus (Dez–Apr) → Hinweis."""
    from datetime import timedelta as _td
    for offset in range(0, tage_zurueck + 1):
        # Bulletin-Pfade nach Lokaldatum (Europe/Vienna) bilden — utcnow hätte nachts
        # (bis ~01/02 Uhr) das Vortags-Datum und fände den frischen Morgen-Bericht nicht.
        tag = (datetime.now() - _td(days=offset)).strftime("%Y-%m-%d")
        u = f"{LAWINEN_BASE}/{tag}/{tag}_{LAWINEN_REGION}_de_CAAMLv6.json"
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA_NOMINATIM}), timeout=20)
            d = json.loads(r.read().decode())
            return tag, d.get("bulletins", [])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            break
        except Exception:
            break
    return None, None

def lawine_text():
    tag, d = lawine_status(2)
    if not d:
        return ("\u2744\ufe0f <b>Lawinenlagebericht O\u00d6</b>\n"
                "Aktuell keine Berichte — der O\u00d6-Lawinenwarndienst berichtet nur im Winterhalbjahr (ca. Dezember bis April).")
    zeilen = [f"\u2744\ufe0f <b>Lawinenlage O\u00d6</b> \u2014 Bericht vom {esc(tag)}"]
    for b in d.get("bulletins", []):
        stufe = "?"
        for dr in b.get("dangerRatings", []):
            stufe = str(dr.get("mainValue", "?"))
        stufe_de = {"low": "1 \u2014 gering", "moderate": "2 \u2014 m\u00e4\u00dfig",
                    "considerable": "3 \u2014 erheblich", "high": "4 \u2014 gro\u00df", "very_high": "5 \u2014 sehr gro\u00df"}.get(stufe, stufe)
        icon = "\U0001f7e2" if stufe == "low" else ("\U0001f7e1" if stufe == "moderate" else "\U0001f534")
        regs = ", ".join(str(x.get("name")) for x in b.get("regions", []) if x.get("name"))
        if regs:
            zeilen.append(f"{icon} <b>{esc(regs)}</b>: Stufe {stufe_de}")
    zeilen.append("")
    zeilen.append("\u26a0\ufe0f Stufen \u00e4ndern sich \u00fcber H\u00f6henlagen \u2014 Details im Bericht: https://lawinen.report/")
    return "\n".join(zeilen)


LAWINEN_CHECK_INTERVAL_H = 6
LAWINEN_STATE_FILE = os.path.expanduser("~/.config/fw_bot/state/lawinen_state.json")

def _load_lawinen_state():
    try:
        with open(LAWINEN_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_lawinen_state(state):
    try:
        os.makedirs(os.path.dirname(LAWINEN_STATE_FILE), exist_ok=True)
        with open(LAWINEN_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Lawinen-State save Fehler: {e}")

def lawine_hoechste_stufe(d):
    """Max. Gefahrenstufe (int) über alle Bulletins des Tages."""
    order = {"low": 1, "moderate": 2, "considerable": 3, "high": 4, "very_high": 5}
    max_w = 0
    for b in d:
        for dr in b.get("dangerRatings", []):
            v = order.get(str(dr.get("mainValue", "")), 0)
            if v > max_w:
                max_w = v
    return max_w

# Lawinen-Regionen OÖ (AT-04) — Zentren + Radius (Haversine-Kopplung an beobachtete Orte).
# Region-Namen exakt wie im CAAML (regionID aus AT-04-Bulletin, Feb 2026):
LAWINEN_REGION_ZENTREN = {
    "AT-04-01": {"name": "Dachstein, Gosaukamm", "lat": 47.50, "lon": 13.60, "km": 20},
    "AT-04-02": {"name": "Kalmberg, Katergebirge", "lat": 47.68, "lon": 13.80, "km": 15},
    "AT-04-03": {"name": "Totes Gebirge Nord", "lat": 47.72, "lon": 14.23, "km": 20},
    "AT-04-04": {"name": "Phyrgas, Haller Mauern", "lat": 47.82, "lon": 14.55, "km": 15},
    "AT-04-05": {"name": "Kasbergblock", "lat": 47.80, "lon": 13.95, "km": 15},
    "AT-04-06": {"name": "Sengsengebirge", "lat": 47.72, "lon": 14.35, "km": 15},
    "AT-04-07": {"name": "Zimnitzmassiv, Höllengebirge", "lat": 47.72, "lon": 13.75, "km": 15},
    "AT-04-08": {"name": "Traunstein, Eibenberg", "lat": 47.79, "lon": 13.80, "km": 12},
}
# Fallback-Order wenn regionID fehlt (Name-basiert):
LAWINEN_NAME_ZENTREN = {
    "dachstein, gosaukamm": "AT-04-01", "kalmberg, katergebirge": "AT-04-02",
    "totes gebirge nord": "AT-04-03", "phyrgas, haller mauern": "AT-04-04",
    "kasbergblock": "AT-04-05", "sengsengebirge": "AT-04-06",
    "zimnitzmassiv, höllengebirge": "AT-04-07", "traunstein, eibenberg": "AT-04-08",
}

def _lawinen_region_fuer_ort(lat, lon):
    """Region-ID, wenn der Ort in/nähe einer OÖ-Lawinen-Region liegt (Haversine), sonst None."""
    for rid, z in LAWINEN_REGION_ZENTREN.items():
        if _haversine_km(lat, lon, z["lat"], z["lon"]) <= z["km"]:
            return rid
    return None

def check_lawinen_for_users(users):
    """Lawinen-Wache (ortsgekoppelt): Meldung NUR an User, deren beobachteter Ort in einer
    lawinengefährdeten Zone liegt UND deren Region auf Stufe 3+ steht. Dedup Tag+Region+Stufe."""
    now = time.time()
    state = _load_lawinen_state()
    if now - state.get("last_check", 0) < LAWINEN_CHECK_INTERVAL_H * 3600:
        return
    state["last_check"] = now
    tag, d = lawine_status(1)
    if not d:
        state["bericht"] = None
        _save_lawinen_state(state)
        return
    # Region → max Stufe je Bulletin-Gruppe:
    region_stufen = {}
    for b in d:
        order = {"low": 1, "moderate": 2, "considerable": 3, "high": 4, "very_high": 5}
        stufe_b = 0
        for dr in b.get("dangerRatings", []):
            v = order.get(str(dr.get("mainValue", "")), 0)
            if v > stufe_b:
                stufe_b = v
        for r in b.get("regions", []):
            rid = r.get("regionID") or LAWINEN_NAME_ZENTREN.get(str(r.get("name", "")).lower().strip())
            if rid:
                region_stufen[rid] = max(region_stufen.get(rid, 0), stufe_b)
    state["bericht"] = {"tag": tag, "region_stufen": region_stufen}
    gesendet = 0
    stufe_de = {3: "erheblich", 4: "gro\u00df", 5: "sehr gro\u00df"}
    gemeldet = set(state.get("gemeldet", []))
    for cid, ud in users.get("users", {}).items():
        if not ud.get("registered"):
            continue
        for ort in ud.get("orte", []):
            okey = ort.lower().strip()
            coords = _ort_koordinaten(okey)
            if not coords:
                continue
            rid = _lawinen_region_fuer_ort(coords[0], coords[1])
            if not rid:
                continue
            stufe = region_stufen.get(rid, 0)
            if stufe >= 3:
                token = f"{tag}:{rid}:{stufe}"
                if token in gemeldet:
                    continue
                gemeldet.add(token)
                z = LAWINEN_REGION_ZENTREN[rid]
                icon = "\U0001f534" if stufe >= 4 else "\u26a0\ufe0f"
                txt = (f"{icon} <b>Lawinenwarnung — {esc(z['name'])}</b>\n"
                       f"Gefahrenstufe {stufe} ({stufe_de.get(stufe, '?')}) \u2014 Bericht vom {esc(tag)}\n"
                       f"Betrifft deine beobachtete Zone: {esc(ort.title())}\n"
                       f"Details: https://lawinen.report/")
                send_to(cid, txt)
                state["gemeldet"] = list(gemeldet)
                _save_lawinen_state(state)
    state["gemeldet"] = list(gemeldet)
    _save_lawinen_state(state)

def lawine_text_ort(ort):
    """/lawine <Ort>: Gefahrenstufe für den beobachteten Ort (falls in Lawinen-Zone), sonst Hinweis."""
    coords = _ort_koordinaten(ort.lower().strip())
    if not coords:
        return f"❓ Ort {esc(ort)} konnte nicht geortet werden."
    rid = _lawinen_region_fuer_ort(coords[0], coords[1])
    if not rid:
        return (f"\u2705 {esc(ort.title())} liegt nicht in einer Lawinen-Zone des O\u00d6-Lawinenwarndiensts "
                f"(keine Bergregion im Umkreis).")
    tag, d = lawine_status(1)
    if not d:
        return ("\u2744\ufe0f Der O\u00d6-Lawinenwarndienst berichtet nur im Winterhalbjahr "
                "(ca. Dezember bis April) — für {0} ist aktuell kein Bericht da.".format(esc(ort.title())))
    order = {"low": 1, "moderate": 2, "considerable": 3, "high": 4, "very_high": 5}
    stufe_de = {1: "1 \u2014 gering", 2: "2 \u2014 m\u00e4\u00dfig", 3: "3 \u2014 erheblich",
                4: "4 \u2014 gro\u00df", 5: "5 \u2014 sehr gro\u00df"}
    zeilen = [f"\u2744\ufe0f <b>Lawinenlage für {esc(ort.title())}</b> (Bericht vom {esc(tag)})"]
    gefunden = False
    for b in d:
        reg_namen = [str(r.get("name", "")) for r in b.get("regions", [])]
        reg_ids = [r.get("regionID") or LAWINEN_NAME_ZENTREN.get(str(r.get("name", "")).lower().strip()) for r in b.get("regions", [])]
        if rid not in reg_ids:
            continue
        gefunden = True
        st = 0
        for dr in b.get("dangerRatings", []):
            v = order.get(str(dr.get("mainValue", "")), 0)
            if v > st:
                st = v
        icon = "\U0001f7e2" if st <= 1 else ("\U0001f7e1" if st == 2 else "\U0001f534")
        zeilen.append(f"{icon} <b>{esc(LAWINEN_REGION_ZENTREN[rid]['name'])}</b>: Stufe {stufe_de.get(st, '?')}")
    if not gefunden:
        zeilen.append("Keine Stufenangabe für deine Region im aktuellen Bericht.")
    zeilen.append("")
    zeilen.append("\u26a0\ufe0f Stufen \u00e4ndern sich \u00fcber H\u00f6henlagen \u2014 Details: https://lawinen.report/")
    return "\n".join(zeilen)

# ═══ Sirenenprobe (Zivilschutz-Probealarm) ═══
SIRENEN_STATE_FILE = os.path.join(STATE_DIR, "sirenen_state.json")

def _sirenen_termin(jahr):
    """Erster Samstag im Oktober des Jahres (offizielle bundesweite Regel)."""
    d = date(jahr, 10, 1)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return d

def sirenen_text():
    """/sirene — nächster Zivilschutz-Probealarm + Signalablauf."""
    heute = date.today()
    jahr = heute.year
    termin = _sirenen_termin(jahr)
    if termin < heute:
        termin = _sirenen_termin(jahr + 1)
    jahr_termin = termin.year
    tage = (termin - heute).days
    if tage == 0:
        wann = "\U0001f534 <b>HEUTE!</b> 12:00\u201312:45 Uhr"
    elif tage == 1:
        wann = "\U0001f7e1 <b>Morgen!</b> 12:00\u201312:45 Uhr"
    else:
        wann = f"am <b>{termin.strftime('%d.%m.%Y')}</b> (Samstag), 12:00\u201312:45 Uhr \u2014 in {tage} Tagen"
    txt = (
        "\U0001f9ef <b>Sirenenprobe \u2014 Zivilschutz-Probealarm</b>\n"
        f"Nächster Termin: {wann}\n"
        f"(Erster Samstag im Oktober, bundesweit \u2014 {jahr_termin}: {termin.strftime('%d.%m.%Y')})\n\n"
        "<b>Signalablauf 12:00\u201312:45:</b>\n"
        "\u2022 \u201eSirenenprobe\u201c \u2014 15 s Dauerton\n"
        "\u2022 \u201eWarnung\u201c \u2014 auf- und abschwellender Heulton\n"
        "\u2022 \u201eAlarm\u201c \u2014 1 Min auf- und abschwellender Heulton\n"
        "\u2022 \u201eEntwarnung\u201c \u2014 1 Min Dauerton\n\n"
        "\U0001f4f1 Begleitend kommt eine AT-Alert-Testmeldung aufs Handy.\n"
        "Mehr: https://www.zivilschutz.at/"
    )
    return txt

def _load_sirenen_state():
    try:
        with open(SIRENEN_STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
        # Migration: früher String {"gesendet": "token"} → Liste:
        if isinstance(st.get("gesendet"), str):
            st["gesendet"] = [st["gesendet"]]
        return st
    except Exception:
        return {}

def _save_sirenen_state(st):
    os.makedirs(os.path.dirname(SIRENEN_STATE_FILE), exist_ok=True)
    with open(SIRENEN_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)

def check_sirenen_for_users(users):
    """Auto-Erinnerung (2× pro Probealarm): (1) Abend vorher ab 18:00, (2) am Probe-Tag ab 11:00
    (= 1 Stunde vor Start). Dedup je Etappe — läuft mit dem Hauptloop, 0 Requests."""
    heute = date.today()
    termin = _sirenen_termin(heute.year)
    if termin < heute:
        termin = _sirenen_termin(heute.year + 1)
    tage = (termin - heute).days
    if tage == 1:
        art, fruehestens, token_praefix = "vorabend", 18, "vorabend"
    elif tage == 0:
        art, fruehestens, token_praefix = "tag", 11, "tag"
    else:
        return
    stunde = datetime.now().hour
    if stunde < fruehestens:
        return
    state = _load_sirenen_state()
    token = f"{token_praefix}:{termin.isoformat()}"
    gesendet = set(state.get("gesendet", []))
    if token in gesendet:
        return
    if art == "vorabend":
        txt = (
            "\U0001f9ef <b>Morgen ist Sirenenprobe!</b>\n"
            f"Zivilschutz-Probealarm am <b>{termin.strftime('%d.%m.%Y')}</b>, 12:00\u201312:45 Uhr \u2014 "
            "in ganz \u00d6sterreich. Signale: \u201eSirenenprobe\u201c, \u201eWarnung\u201c, \u201eAlarm\u201c, \u201eEntwarnung\u201c "
            "+ AT-Alert-Testmeldung aufs Handy.\n"
            "Details: /sirene"
        )
        kopf = f"Sirenen-Vorabend-Erinnerung"
    else:
        txt = (
            "\U0001f9ef <b>Heute 12:00 Uhr ist Sirenenprobe!</b>\n"
            "Zivilschutz-Probealarm startet in 1 Stunde (12:00\u201312:45, ganz \u00d6sterreich). "
            "Signale: \u201eSirenenprobe\u201c, \u201eWarnung\u201c, \u201eAlarm\u201c, \u201eEntwarnung\u201c "
            "+ AT-Alert-Testmeldung aufs Handy.\n"
            "Details: /sirene"
        )
        kopf = "Sirenen-1-Stunden-Erinnerung"
    n = 0
    for cid, ud in users.get("users", {}).items():
        if ud.get("registered"):
            try:
                send_to(cid, txt)
                n += 1
            except Exception as _se:
                logger.error(f"Sirenen-Erinnerung fehlgeschlagen {cid}: {_se}")
    if n:
        gesendet.add(token)
        state["gesendet"] = list(gesendet)
        _save_sirenen_state(state)
        logger.info(f"{kopf} an {n} Nutzer gesendet (Termin {termin})")

# ═══ /testalarm ═══
def send_testalarm(chat_id):
    """Simulierter Probe-Alarm: prüft die Alarm-Zustellung, ohne echten Einsatz zu brauchen."""
    betreff = "\U0001f6e9\ufe0f <b>TESTALARM — Probe der Alarm-Kette</b>"
    msg = (
        f"{betreff}\n"
        f"\U0001f4cb \U0001f7e2 Test — Funktionstest der Alarm-Kette\n"
        f"\U0001f4cd Probealarm (kein echter Einsatz) (TEST)\n"
        f"\u23f1\ufe0f Alarm: {datetime.now().strftime('%d.%m. %H:%M')} (sofort)\n"
        f"\U0001f50d Beobachtet: Funktionstest\n\n"
        f"\u2705 Diese Nachricht beweist: Alarme kommen bei dir an. "
        f"Eine Sprachnachricht dazu bekommst du bei jedem echten Alarm, wenn du /stimme aktiv hast.")
    send_to(chat_id, msg)
    logger.info(f"Testalarm gesendet an {chat_id}")

# ═══ Persönlicher Rückblick (/rueckblick) ═══
def rueckblick_text(cid_str, ud, monate=1):
    """Persönlicher Einsatzrückblick der letzten N Monate aus dem Alarm-Log."""
    jetzt = datetime.now()
    vor_n = jetzt - timedelta(days=30 * monate)
    orte_lower = [o.lower() for o in ud.get("orte", [])]
    if not orte_lower:
        return None
    eintraege = []
    for z in range(monate + 1):
        m = jetzt - timedelta(days=30 * z)
        log_path = os.path.join(STATE_DIR, "alarme_%04d-%02d.json" % (m.year, m.month))
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    eintraege.extend(json.load(f))
            except Exception:
                pass
    gef = {}
    for ein in eintraege:
        try:
            dt = datetime.fromisoformat(ein["datum"])
        except Exception:
            continue
        if dt < vor_n:
            continue
        if ein.get("ort", "").lower() not in orte_lower:
            continue
        if cid_str not in [str(c) for c in ein.get("chat_ids", [])]:
            continue
        typ = ein.get("typ", "?")
        gef[typ] = gef.get(typ, 0) + 1
    gesamt = sum(gef.values())
    if gesamt == 0:
        return ("\U0001f4ca <b>Dein Rückblick</b> (letzte %d Monate)\n\n"
                "Keine Einsätze in deinen Orten in diesem Zeitraum. Ruhig! \U0001f692" % monate)
    teile = ["• %dx %s" % (n, esc(t)) for t, n in sorted(gef.items(), key=lambda x: -x[1])]
    meist = sorted(gef.items(), key=lambda x: -x[1])[0][0]
    zeilen = "\n".join(teile[:4])
    if len(teile) > 4:
        zeilen += f"\n• … (+{len(teile) - 4} weitere)"
    return ("\U0001f4ca <b>Dein Rückblick</b> (letzte %d Monate)\n\n"
            "\U0001f692 <b>%d</b> Alarme in deinen Orten (%s)\n%s\n\n"
            "Häufigster Typ: %s" % (monate, gesamt, esc(", ".join(o.capitalize() for o in orte_lower)),
                                    zeilen, esc(meist)))

def help_text(user_data, is_admin):
    name = user_data.get("username", "?")
    orte = user_data.get("orte", [])
    einsatz_watches = user_data.get("einsatz_watches", [])
    watch_count = len(orte) + len(einsatz_watches)

    # Rechte-Anzeige
    if is_admin:
        role = "\U0001f451 Admin"
        perms = "Vollzugriff \u2014 Alle Befehle, Benutzerverwaltung"
    else:
        role = "\U0001f464 Benutzer"
        perms = "Eigene Orte beobachten, Eins\u00e4tze abfragen"

    msg = (
        f"\U0001f6f0\ufe0f <b>Feuerwehr-Monitor Bot</b>\n"
        f"Angemeldet als: {name}  |  Rolle: {role}  |  Beobachtungen: {watch_count}\n"
    )

    msg += (
        f"\n\U0001f6a8 <b>Einsätze ansehen</b>\n"
        f"\U0001f680 /start — Bot aktivieren / Begrüßung\n"
        f"/anleitung — Wie funktioniert der Bot? (Daten, Regeln, Limits)\n"
        f"/lage — Alle laufenden Einsätze in Oberösterreich (mit 📍-Karte &amp; ⏱️-Beobachten-Buttons je Einsatz)\n"
        f"/warnungen [Ort] — Aktive Unwetter-Warnungen (GeoSphere Austria); ohne Ort: für deine beobachteten Orte\n"
        f"/offenhausen — Letzte Einsätze der Heimat-Feuerwehr ({FF_NAME})\n"
        f"/heute — Einsätze von heute für deine Orte\n"
        f"/statistik — Statistik der letzten 12 Monate (+ Diagramm als Bild)\n"
        f"/bezirk &lt;Kürzel&gt; — Einsätze von heute in einem Bezirk (z.B. /bezirk WL)\n"
        f"/brand &lt;Ort oder Kürzel&gt; — Laufende Brände anzeigen (z.B. /brand Lengau oder /brand WL)\n"
        f"/technisch &lt;Ort oder Kürzel&gt; — Technische Einsätze anzeigen (Unfälle, Ölspuren, Türöffnungen …)\n"
        f"/personenrettung &lt;Ort oder Kürzel&gt; — Personenrettungen anzeigen\n"
        f"/unwetter &lt;Ort oder Kürzel&gt; — Unwetter-Einsätze anzeigen\n"
        f"/sonstiges &lt;Ort oder Kürzel&gt; — Sonstige Einsätze anzeigen (Bäume, Bergungen …)\n"
        f"/umkreis [km] — Laufende Einsätze im Umkreis deiner beobachteten Orte (Standard 15 km)\n"
        f"/training — Übungen der Heimat-Feuerwehr (12 Monate, von einsaetze.at)\n"
        f"\n\U0001f4cd <b>Beobachten (meine Orte)</b>\n"
        f"/ort &lt;Ort&gt; — Ort <b>dauerhaft</b> beobachten — Alarm bei jedem Einsatz (z.B. /ort Lengau)\n"
        f"/ort &lt;Ort&gt; &lt;Typ&gt; — Ort nur für einen Einsatztyp beobachten: brand, technisch, personenrettung, unwetter oder sonstige (z.B. /ort Lengau brand)\n"
        f"/unort &lt;Ort&gt; — Dauerhafte Beobachtung beenden\n"
        f"/unortall — Alle dauerhaften Beobachtungen auf einmal beenden\n"
        f"\n\u23f1\ufe0f <b>Beobachten (laufender Einsatz)</b>\n"
        f"/einsatz &lt;Ort&gt; — Nur den <b>jetzt laufenden</b> Einsatz beobachten — endet automatisch nach dem Abschlussbericht (z.B. /einsatz Lengau)\n"
        f"/uneinsatz &lt;Ort&gt; — Temporäre Beobachtung beenden\n"
        f"/meinebeobachtungen — Alle meine Beobachtungen anzeigen\n"
        f"\n\U0001f514 <b>Ruhe &amp; Kontrolle</b>\n"
        f"/stumm — Stiller Modus an/aus (keine Alarme, Befehle bleiben nutzbar)\n"
        f"/stumm 22-07 — Stillfenster: zwischen 22 und 7 Uhr werden Alarme gesammelt und morgens als Sammel-Meldung zugestellt (/stumm 0 löscht das Fenster, /stumm ohne Argument zeigt den Status)\n"
        f"/wochen — Wochenrückblick ein-/ausschalten (sonntags 20:00 eine Zusammenfassung deiner Orte)\n"
        f"/qr_code — QR-Code mit dem Bot-Link zum Weiterschicken an Kameraden\n"
        f"\U0001f464 <b>Konto &amp; Datenschutz</b>\n"
        f"/registrieren &lt;Name&gt; — Benutzernamen setzen/ändern\n"
        f"/datenschutz — Welche Daten speichert der Bot?\n"
        f"/vergessen — Kompletten Zugang löschen (Bestätigung + 2 Wochen Bedenkzeit + letzte Nachfrage)\n"
        f"/testalarm — Probealarm: prüft ob Alarme bei dir ankommen\n"
        f"/pegel — Wasserstände der Pegel im Umkreis deiner Orte (Hochwasser-Wache)\n"
        f"/strom — Stromausfälle in den Bezirken deiner Orte (Netz OÖ)\n"
        f"/waldbrand — Waldbrand-Gefährdung an deinen Orten (Wetter-Abschätzung)\n"
        f"/lawine — Lawinenlagebericht für ganz OÖ (Totes Gebirge, Dachstein, Sengsengebirge …)\n"
        f"/lawine <Ort> — Gefahr am Berg für EINEN Ort (z. B. /lawine Gosau)\n"
        f"      ❄️ Automatische Warnung NUR wenn dein beobachteter Ort in einer Lawinen-Zone liegt\n"        f"/sirene — Nächster Sirenenprobe-Termin (Zivilschutz-Probealarm, 1× jährlich)\n"
        f"/rueckblick — Dein persönlicher Einsatzrückblick (optional: /rueckblick 6 für 6 Monate)\n"
        f"/stimme — Sprachnachricht-Alarm ein/aus (Alarm zusätzlich am Ohr)\n"
        f"/abbruch — Laufende Löschung abbrechen, alles zurückholen\n"
        f"/fehler &lt;Text&gt; — Fehler/Problem an den Admin melden\n"
        f"/wunsch &lt;Wunsch&gt; — Wunsch oder Idee für den Bot dem Admin schreiben\n"
        f"/quellen — Welche Datenquellen nutzt der Bot? (Offenlegung + Hinweise)\n"
        f"/meinedaten — Deine gespeicherten Daten als Übersicht (DSGVO-Auskunft)\n"
        f"/id — Deine Telegram Chat-ID anzeigen\n"
        f"/hilfe — Diese Hilfe"
    )
    if is_admin:
        msg += (
            f"\n\n\U0001f451 <b>Admin — Benutzer verwalten</b>\n"
            f"/aufnehmen &lt;ID&gt; [Name] — Benutzer hinzufügen (mit Name = sofort registriert)\n"
            f"/entfernen &lt;ID&gt; — Benutzer komplett entfernen \u26d4\ufe0f\n"
            f"/benutzer — Alle Benutzer anzeigen\n"
            f"/verwalten &lt;ID&gt; ort &lt;Ort&gt; — Orts-Beobachtung für anderen setzen\n"
            f"/verwalten &lt;ID&gt; unort &lt;Ort&gt; — Sie wieder entfernen\n"
            f"/verwalten &lt;ID&gt; einsatz &lt;Ort&gt; — Einsatz-Beobachtung für anderen setzen\n"
            f"/verwalten &lt;ID&gt; uneinsatz &lt;Ort&gt; — Sie wieder entfernen\n"
            f"/rundruf &lt;Text&gt; — Nachricht an alle Benutzer\n"
            f"/serverstatus — Bot-Status: Laufzeit, Benutzer, Datenquellen-Check, Speicher\n"
            f"\n\U0001f451 <b>Admin — Sperren</b>\n"
            f"/sperren &lt;ID&gt; [Stunden] — ID sperren (ohne Angabe: dauerhaft)\n"
            f"/freigeben &lt;ID&gt; — Sperre aufheben\n"
            f"\n\U0001f451 <b>Admin — Löschungen &amp; Fehler</b>\n"
            f"/widerruf — Laufende Lösch-Anträge mit Restzeit anzeigen\n"
            f"/abbruch &lt;ID&gt; — Löschung eines Users abbrechen (restauriert ihn)\n"
            f"/fehler liste — Alle protokollierten Fehlermeldungen\n"
            f"/wunsch liste — Alle protokollierten Wünsche"
        )
    else:
        msg += (
            f"\n\n\U0001f512 <b>Hinweis:</b> Du kannst nur deine eigenen Orte beobachten. "
            f"Benutzerverwaltung (hinzufügen, entfernen, Beobachtungen für andere setzen) "
            f"ist dem Admin vorbehalten. Versuche, den Admin zu entfernen, führen zu einem automatischen Bann."
        )
    return msg

# ═══ Bot Command Handler ═══
def handle_bot_commands():
    if not BOT_TOKEN or not ADMIN_ID:
        return
    try:
        offset = 0
        if os.path.exists(OFFSET_FILE):
            with open(OFFSET_FILE, "r") as f:
                try:
                    offset = int(f.read().strip() or "0")
                except ValueError:
                    offset = 0
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=8"
        resp = urllib.request.urlopen(url, timeout=12)
        data = json.loads(resp.read())
        if not data.get("ok"):
            return
        for update in data.get("result", []):
            offset = update["update_id"] + 1
            # Inline-Buttons (callback_query) zuerst — haben keine "message"
            cq = update.get("callback_query")
            if cq:
                try:
                    handle_callback(cq)
                except Exception as cb_err:
                    logger.error(f"Callback-Fehler: {cb_err}")
                continue
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = msg.get("chat", {}).get("id")
            if chat_id is None:
                continue

            cid_str = str(chat_id)

            # ── Befehls-Aliasse: alte/englische Formen → deutsche Kanonform ──
            # (Damit alte Eingaben weiter funktionieren; angezeigt werden NUR deutsche Befehle)
            _ALIAS = {"/help": "/hilfe", "/status": "/lage", "/today": "/heute",
                      "/stats": "/statistik", "/mywatches": "/meinebeobachtungen",
                      "/silent": "/stumm", "/register": "/registrieren",
                      "/add": "/aufnehmen", "/remove": "/entfernen", "/list": "/benutzer",
                      "/user": "/verwalten", "/ban": "/sperren", "/unban": "/freigeben",
                      "/broadcast": "/rundruf", "/loeschen": "/vergessen", "/löschen": "/vergessen"}
            _first = text.split(None, 1)[0].lower() if text else ""
            if _first in _ALIAS:
                text = _ALIAS[_first] + text[len(_first):]
                _first = text.split(None, 1)[0]

            # ── Admin-Blacklist-Check: GEBANNTE IDs werden komplett ignoriert ──
            # users.json bans + blacklist.json (präventiv, auch für IDs die
            # den Bot noch nie gestartet haben). Auch /start wird still
            # verworfen — keine Antwort, kein Anlegen, keine Alarme, keine Meldung.
            if chat_id != ADMIN_ID:
                grund = blocked_reason(cid_str)
                if grund:
                    logger.info(f"Gebannte ID ignoriert: {chat_id} ({grund})")
                    continue

            # ── Unbekannte User: automatisch als (noch) unregistrierte User anlegen ──
            # JEDER darf den Bot starten — Zugriff auf User-Befehle nach /registrieren,
            # Admin-Befehle bleiben ausschließlich dem Admin (ADMIN_ID) vorbehalten.
            if cid_str not in users["users"]:
                # ── Kapazitäts-Limit: volle User-DB → keine neuen Kontakte mehr anlegen ──
                # Admin ist immer ausgenommen (init_users legt ihn ohnehin wieder an).
                if len(users["users"]) >= MAX_USERS and chat_id != ADMIN_ID:
                    logger.warning(f"Kapazitäts-Limit erreicht ({len(users['users'])} Einträge) — neuer Kontakt {chat_id} abgelehnt.")
                    send_to(chat_id, (
                        "\U0001f6d1 <b>Leider sind alle Pl\u00e4tze belegt.</b>\n\n"
                        f"Dieser Bot ist aktuell mit der maximalen Anzahl von {MAX_USERS} Benutzern "
                        "ausgelastet \u2014 neue Anmeldungen sind gerade nicht m\u00f6glich.\n\n"
                        "\U0001f513 <b>Deine M\u00f6glichkeiten:</b>\n"
                        "\u2022 Schau sp\u00e4ter wieder vorbei \u2014 wenn Pl\u00e4tze frei werden (z. B. durch "
                        "L\u00f6schungen), kannst du dich erneut melden.\n"
                        "\u2022 Selbst hosten: Der Bot ist open source \u2014 du kannst deine eigene Instanz "
                        "auf einem Raspberry Pi betreiben (Projekt: github.com/TechFlipsi/FlipsiPager)."))
                    continue
                first_name = msg.get("from", {}).get("first_name", "?")
                logger.info(f"Neuer Bot-Kontakt: Chat-ID {chat_id} (First name: {first_name})")
                users["users"][cid_str] = {
                    "username": "",
                    "is_admin": False,
                    "registered": False,
                    "added_at": datetime.now().isoformat(),
                    "orte": [],
                    "einsatz_watches": [],
                }
                save_users(users)
                # Admin-Info: JEDER neue Bot-Kontakt wird gemeldet
                # (nicht erst bei /registrieren) — Der Admin will sehen, wer den Bot startet.
                send_to(ADMIN_ID, (
                    f"\U0001f465 \U0001f195 \U0001f539 <b>Neuer Bot-Kontakt</b>\n"
                    f"\U0001f194 ID: <code>{chat_id}</code>\n"
                    f"\U0001f464 Name: {esc(first_name)}\n"
                    f"\u2139\ufe0f Hat den Bot gestartet, ist aber noch nicht registriert."
                ))
                # Kein continue: Flow läuft weiter → nicht-registrierter Zweig
                # antwortet sofort mit Willkommen + /registrieren-Aufforderung.

            # ── Banned User Check ──
            user_data = users["users"].get(cid_str, {})
            ban_until = user_data.get("ban_until")
            if ban_until:
                try:
                    ban_dt = datetime.fromisoformat(ban_until)
                    if datetime.now() < ban_dt:
                        remaining = ban_dt - datetime.now()
                        hours = int(remaining.total_seconds() // 3600)
                        mins = int((remaining.total_seconds() % 3600) // 60)
                        send_to(chat_id, f"\U0001f6ab\ufe0f Du bist gebannt. Noch {hours}h {mins}min bis zur Aufhebung.")
                        continue
                    else:
                        # Ban abgelaufen → automatisch entbannen
                        users["users"][cid_str]["ban_until"] = None
                        users["users"][cid_str]["registered"] = True
                        save_users(users)
                        send_to(chat_id, "\u2705 Dein Bann ist abgelaufen. Du bist wieder freigegeben.")
                        user_data = users["users"][cid_str]
                        continue  # User muss Command erneut senden
                except Exception:
                    # Bei ung\u00fcltigem ban_until: Bann aufheben (sicherer Default)
                    users["users"][cid_str]["ban_until"] = None
                    save_users(users)
                    logger.warning(f"Ung\u00fcltiger ban_until Wert f\u00fcr {cid_str}: {ban_until}")
                    send_to(chat_id, "\u26a0\ufe0f Dein Bann-Status war fehlerhaft und wurde zur\u00fcckgesetzt.")
                    continue

            is_admin = user_data.get("is_admin", False)
            is_registered = user_data.get("registered", False)

            # ── Lösch-Antrag-Handler (VOR dem nicht-registr-Zweig!) ──
            # Nach Bestätigung ist der User registered=False — der /abbruch MUSS trotzdem
            # erreichbar bleiben, sonst kann niemand seine Lösch-Beantragung abbrechen.
            # ── Admin: Lösch-Liste + Einzel-Abbruch (VOR allem anderen) ──
            if int(chat_id) == int(ADMIN_ID) and (text == "/widerruf" or text == "/loeschungen" or text.startswith("/abbruch ")):
                antraege = load_loeschungen()
                if text in ("/widerruf", "/loeschungen"):
                    if not antraege:
                        send_to(chat_id, "\u2705 Keine laufenden Lösch-Anträge.")
                        continue
                    zeilen = ["\U0001f5d1\ufe0f <b>Laufende Lösch-Anträge</b>\n"]
                    for lcid, at in sorted(antraege.items()):
                        ud_b = at.get("user_data", {})
                        uname = (ud_b.get("username") or "?")
                        try:
                            verbleib = (datetime.fromisoformat(at["delete_at"]) - datetime.now())
                            h = int(verbleib.total_seconds() // 3600)
                            mi = int((verbleib.total_seconds() % 3600) // 60)
                            rest = f"{h}h {mi}min verbleibend"
                        except Exception:
                            rest = "Frist abgelaufen (wird bei Kontakt ausgeführt)"
                        zeilen.append(f"  \U0001f6ab {lcid} ({esc(uname)}) \u2014 {rest}")
                    zeilen.append("\n\U0001f6e9\ufe0f Abbrechen einer einzelnen Löschung: /abbruch &lt;ID&gt;")
                    send_to(chat_id, "\n".join(zeilen))
                    continue
                parts_a = text.split()
                try:
                    a_id = int(parts_a[1])
                except (ValueError, IndexError):
                    send_to(chat_id, "Usage: /abbruch &lt;ID&gt; (oder /widerruf für die Liste)")
                    continue
                a_str = str(a_id)
                if a_str not in antraege:
                    send_to(chat_id, f"\u2139\ufe0f Für ID {a_id} läuft keine Löschung.")
                    continue
                backup = antraege.pop(a_str)
                save_loeschungen(antraege)
                if restore_user_data(a_str, backup):
                    logger.info(f"Admin-Abbruch der Löschung: {a_str} (von Admin {chat_id})")
                    send_to(chat_id, f"\u2705 Löschung von ID {a_id} ABGEBROCHEN \u2014 User vollständig restauriert (Benutzername, Beobachtungen, Zugang).")
                    try:
                        send_to(a_id, "\u2705 Deine ausstehende Löschung wurde vom Administrator abgebrochen.\nDein Zugang, dein Benutzername und alle deine Beobachtungen sind wiederhergestellt. Du bekommst ab sofort wieder deine Alarme. \U0001f692")
                    except Exception:
                        pass
                else:
                    send_to(chat_id, f"\u26a0\ufe0f Abbruch für {a_id} fehlgeschlagen — bitte Log prüfen.")
                continue

            # ── Eigen-Abbruch + pendant-/vergessen ──
            if cid_str in load_loeschungen() and text in ("/abbruch", "/vergessen", "/vergessen status", "/loeschen", "/löschen", "/loeschen status"):
                antraege_d = load_loeschungen()
                at = antraege_d.get(cid_str)
                verbleib = (datetime.fromisoformat(at["delete_at"]) - datetime.now())
                h = int(verbleib.total_seconds() // 3600)
                m_ins = int((verbleib.total_seconds() % 3600) // 60)
                if text == "/abbruch":
                    antraege_d.pop(cid_str)
                    save_loeschungen(antraege_d)
                    ok = restore_user_data(cid_str, at)
                    if ok:
                        logger.info(f"LOESCHUNG abgebrochen + restauriert: {chat_id}")
                        send_to(chat_id, (
                            "\u2705 <b>Löschung ABGEBROCHEN — alles ist zurück!</b>\n\n"
                            "Dein Benutzername, deine Beobachtungen und dein kompletter Zugang "
                            "sind wiederhergestellt. Du bekommst ab sofort wieder deine Alarme. "
                            "Willkommen zurück! \U0001f692"))
                        send_to(ADMIN_ID, f"\u2139\ufe0f Löschung von User {chat_id} wurde ABGEBROCHEN — User vollständig restauriert.")
                    else:
                        send_to(chat_id, "\u26a0\ufe0f Abbruch-Fehler — bitte Admin benachrichtigen.")
                        send_to(ADMIN_ID, f"\u26a0\ufe0f Restore fehlgeschlagen beim Abbruch von {chat_id}!")
                    continue
                else:  # /loeschen während pendenter Frist
                    send_to(chat_id, (
                        f"\u23f3 <b>L\u00f6schung bereits best\u00e4tigt \u2014 du stehst auf der L\u00f6schungsliste.</b>\n"
                        f"Letzte Nachfrage des Bots in ca. {h}h {m_ins}min.\n"
                        f"Zum Abbrechen und ALLES zur\u00fcckholen: /abbruch"))
                    continue

            # ── Nicht registrierte User ──
            if not is_registered:
                if text == "/start":
                    send_to(chat_id, (
                        "\U0001f6f0\ufe0f <b>Feuerwehr-Monitor Bot</b>\n\n"
                        "Ich \u00fcberwache Feuerwehr-Eins\u00e4tze in Ober\u00f6sterreich und benachrichtige dich sofort, wenn in deinem beobachteten Ort ein Einsatz stattfindet.\n\n"
                        "<b>Was ich kann:</b>\n"
                        "\U0001f50d Orte beobachten und bei Eins\u00e4tzen alarmieren\n"
                        "\U0001f4ca Aktuelle Eins\u00e4tze in ganz O\u00d6 abfragen\n"
                        f"\U0001f692 Letzte Eins\u00e4tze der Heimat-Feuerwehr ({FF_NAME}) anzeigen\n\n"
                        "\u26a0\ufe0f <b>Wichtig:</b> Ich bin ein privates, inoffizielles Projekt \u2014 auf mich darf man sich NICHT zu 100 % verlassen. Verlasse dich im Notfall NIEMALS allein auf den Bot: Offizielle Alarmierung (Sirene, Funk, Pager) geht immer vor.\n\n"
                        "<b>Erster Schritt:</b>\n"
                        "Bitte vergebe einen Benutzernamen mit /registrieren &lt;Name&gt;\n"
                        "Beispiel: /registrieren Max"
                    ))
                elif text.startswith("/registrieren"):
                    parts = text.split(None, 1)
                    if len(parts) < 2:
                        send_to(chat_id, "Bitte vergebe einen Benutzernamen:\n/registrieren &lt;Name&gt;\nBeispiel: /registrieren Max")
                        continue
                    new_name = parts[1].strip()[:50]
                    if not new_name:
                        send_to(chat_id, "Der Benutzername darf nicht leer sein.")
                        continue
                    # Pr\u00fcfen ob Name bereits vergeben ist (case-insensitive)
                    name_taken = False
                    for uid, ud in users["users"].items():
                        if ud.get("username", "").lower() == new_name.lower() and uid != cid_str:
                            name_taken = True
                            break
                    if name_taken:
                        send_to(chat_id, f"\u26a0\ufe0f Der Benutzername '{esc(new_name)}' ist bereits vergeben.\nBitte w\u00e4hle einen anderen Namen.")
                        continue
                    users["users"][cid_str]["username"] = new_name
                    users["users"][cid_str]["registered"] = True
                    save_users(users)
                    logger.info(f"Neuer User registriert: {new_name} ({chat_id})")
                    send_to(ADMIN_ID, f"\U0001f4e5 Neuer User: {esc(new_name)} (ID {chat_id}) hat sich registriert.")
                    send_to(chat_id, (
                        f"\u2705 Willkommen, {esc(new_name)}! Du bist jetzt registriert.\n\n"
                        f"Mit /ort &lt;Ort&gt; kannst du Orte dauerhaft beobachten.\nMit /einsatz &lt;Ort&gt; beobachtest du nur den aktuellen Einsatz.\n"
                        f"Sende /hilfe f\u00fcr alle Befehle."
                    ))
                elif text == "/id":
                    send_to(chat_id, f"\U0001f194 Deine Chat-ID: {chat_id}")
                elif text.startswith("/"):
                    send_to(chat_id, "\u26a0\ufe0f Du bist berechtigt, aber noch nicht registriert.\nBitte vergebe zuerst einen Benutzernamen: /registrieren &lt;Name&gt;")
                else:
                    send_to(chat_id, "\u26a0\ufe0f Bitte registriere dich zuerst: /registrieren &lt;Name&gt;")
                continue

            # ── Registrierte User: Befehle ──
            if text == "/start":
                name = user_data.get("username") or "?"
                orte = user_data.get("orte", [])
                einsatz_watches = user_data.get("einsatz_watches", [])
                watch_count = len(orte) + len(einsatz_watches)
                silent = user_data.get("silent", False)
                if is_admin:
                    role_tag = " \U0001f451"
                else:
                    role_tag = ""
                silent_line = f"\n\U0001f515 Stiller Modus: <b>AKTIV</b> (keine Alarme)" if silent else ""
                send_to(chat_id, (
                    f"\U0001f44b Willkommen zurück, {esc(name)}{role_tag}!\n"
                    f"Aktive Beobachtungen: {watch_count}{silent_line}\n\n"
                    f"⚠️ Zur Erinnerung: Inoffizielles Hobby-Projekt — verlasse dich im Notfall nie allein auf den Bot (Sirene/Funk/Notruf 122 gehen immer vor).\n\n"
                    f"Sende /hilfe für alle Befehle."
                ))
            elif text == "/hilfe":
                send_to(chat_id, help_text(user_data, is_admin))

            elif text == "/testalarm":
                send_testalarm(chat_id)
                if user_data.get("stimme"):
                    try:
                        ogg = tts_text_erzeugen("Testalarm. Das ist ein Funktionstest der Sprachalarm-Kette.")
                        if ogg:
                            send_voice_ogg(chat_id, ogg)
                    except Exception as e:
                        logger.warning(f"TTS-Test fehlgeschlagen {chat_id}: {e}")

            elif text == "/pegel":
                try:
                    orte_u = user_data.get("orte", [])
                    if not orte_u:
                        send_to(chat_id, "\u2139\ufe0f Beobachte zuerst Orte mit /ort — Pegel werden rund um deine Orte gesucht.")
                        continue
                    send_to(chat_id, "\U0001f30a Pegel werden geladen\u2026")
                    rep = pegel_text_fuer_orte(orte_u)
                    if rep:
                        send_to(chat_id, rep)
                    else:
                        send_to(chat_id, "\U0001f30a Keine Pegel im 20-km-Umkreis deiner Orte.\n"
                                         "Hinweis: Die Pegel-Wache deckt Ober\u00f6sterreich ab (Hydro O\u00d6) — "
                                         "Orte au\u00dferhalb O\u00d6 (z.\u202fB. Nieder\u00f6sterreich) haben keine Pegel-Abdeckung.")
                except Exception as pe:
                    logger.error(f"/pegel Fehler: {pe}")
                    send_to(chat_id, "\u26a0\ufe0f Pegel-Abruf fehlgeschlagen.")

            elif text == "/strom":
                try:
                    orte_u = user_data.get("orte", [])
                    if not orte_u:
                        send_to(chat_id, "\u2139\ufe0f Beobachte zuerst Orte mit /ort — Strom-St\u00f6rungen werden f\u00fcr deine Bezirke gesucht.")
                        continue
                    send_to(chat_id, "\u26a1 St\u00f6rungsstatus wird geladen\u2026")
                    rep = strom_text_fuer_orte(orte_u)
                    if rep:
                        send_to(chat_id, "\u26a1 <b>Strom-Versorgung (Netz O\u00d6)</b>\n" + rep)
                    else:
                        send_to(chat_id, "\u26a1 St\u00f6rungskarte gerade nicht erreichbar \u2014 sp\u00e4ter erneut versuchen.")
                except Exception as strom_cmd_err:
                    logger.error(f"/strom Fehler: {strom_cmd_err}")
                    send_to(chat_id, "\u26d4 Fehler bei der St\u00f6rungsabfrage.")
            elif text == "/waldbrand":
                try:
                    orte_u = user_data.get("orte", [])
                    if not orte_u:
                        send_to(chat_id, "\u2139\ufe0f Beobachte zuerst Orte mit /ort — Waldbrandgefahr wird f\u00fcr deine Orte gesch\u00e4tzt.")
                        continue
                    send_to(chat_id, "\U0001f9ea Wetterdaten werden geladen\u2026")
                    rep = waldbrand_text_fuer_orte(orte_u)
                    send_to(chat_id, "\U0001f332 <b>Waldbrand-Gef\u00e4hrdung</b> (eigene Absch\u00e4tzung aus GeoSphere-Wetter)\n" + rep)
                except Exception as wb_cmd_err:
                    logger.error(f"/waldbrand Fehler: {wb_cmd_err}")
                    send_to(chat_id, "\u26d4 Fehler bei der Waldbrand-Abfrage.")
            elif text == "/lawine" or text.startswith("/lawine "):
                try:
                    arg = text[len("/lawine"):].strip()
                    if arg:
                        send_to(chat_id, lawine_text_ort(arg))
                    else:
                        send_to(chat_id, lawine_text())
                except Exception as lw_err:
                    logger.error(f"/lawine Fehler: {lw_err}")
                    send_to(chat_id, "\u26d4 Lawinenbericht gerade nicht erreichbar.")

            elif text == "/sirene":
                try:
                    send_to(chat_id, sirenen_text())
                except Exception as sir_err:
                    logger.error(f"/sirene Fehler: {sir_err}")
                    send_to(chat_id, "\u26d4 Sireneninfo fehlgeschlagen.")

            elif text == "/rueckblick":
                try:
                    monate = 1
                    teile = text.split()
                    if len(teile) >= 2 and teile[1].isdigit():
                        monate = max(1, min(12, int(teile[1])))
                    txt_r = rueckblick_text(cid_str, user_data, monate=monate)
                    if txt_r:
                        send_to(chat_id, txt_r)
                    else:
                        send_to(chat_id, "\u2139\ufe0f Beobachte zuerst Orte mit /ort — dann zeig ich dir deine Einsatzstatistik.")
                except Exception as re_:
                    logger.error(f"/rueckblick Fehler: {re_}")
                    send_to(chat_id, "\u26a0\ufe0f Rückblick fehlgeschlagen.")

            elif text == "/stimme":
                if user_data.get("stimme"):
                    user_data["stimme"] = False
                    save_users(users)
                    send_to(chat_id, "\U0001f507 Sprachnachrichten <b>deaktiviert</b>.\nAlarme kommen weiterhin als Text.")
                else:
                    if not piper_verfuegbar():
                        send_to(chat_id, "\u26a0\ufe0f Sprachausgabe ist gerade nicht verfügbar (TTS-Modul fehlt auf dem Server).")
                        continue
                    user_data["stimme"] = True
                    save_users(users)
                    send_to(chat_id, (
                        "\U0001f50a Sprachnachrichten <b>aktiviert</b>!\n\n"
                        "Bei jedem neuen Alarm bekommst du zus\u00e4tzlich eine kurze Sprachnachricht "
                        "(Ort, Stichwort, Feuerwehren) \u2014 praktisch am Lenkrad.\n\n"
                        "Deaktivieren: /stimme"))
                    logger.info(f"Sprachalarm aktiviert für {chat_id}")

            elif text == "/anleitung":
                send_to(chat_id, anleitung_text())

            elif text == "/datenschutz":
                send_to(chat_id, datenschutz_text())

            elif text in ("/vergessen", "/loeschen", "/löschen"):
                # Stufe 1: Warnung + Bestätigungs-Token
                antraege = load_loeschungen()
                if cid_str == str(ADMIN_ID):
                    send_to(chat_id, "\u26d4\ufe0f Der Admin-Konto kann nicht über /loeschen entfernt werden (Schutz vor versehentlicher System-Löschung).\nWenn du wirklich alles löschen willst: benutze /remove &lt;deine ID&gt; als Admin.")
                    continue
                if cid_str in antraege:
                    at = antraege[cid_str]
                    verbleib = (datetime.fromisoformat(at["delete_at"]) - datetime.now())
                    h = int(verbleib.total_seconds() // 3600)
                    m = int((verbleib.total_seconds() % 3600) // 60)
                    send_to(chat_id, (
                        f"\u23f3 L\u00f6schung bereits beantragt und best\u00e4tigt.\n"
                        f"Endg\u00fcltige L\u00f6schung in ca. {h}h {m}min.\n"
                        f"Zum Abbrechen: /abbruch"))
                    continue
                token = str(datetime.now().timestamp())[-4:]
                users["users"][cid_str]["loesch_token"] = token
                save_users(users)
                send_to(chat_id, (
                    f"\u26a0\ufe0f <b>WARNUNG: Komplette L\u00f6schung deines Zugangs</b>\n\n"
                    f"Das l\u00f6scht ALLES, was zu deiner Chat-ID ({chat_id}) geh\u00f6rt:\n"
                    f"\u2022 Dein Benutzername\n"
                    f"\u2022 Alle beobachteten Orte\n"
                    f"\u2022 Alle tempor\u00e4ren Einsatz-Beobachtungen\n"
                    f"\u2022 Deinen kompletten Zugang (du bist dann NEU registriert bei R\u00fcckkehr)\n\n"
                    f"Es bleiben KEINE Daten \u00fcbrig.\n\n"
                    f"<b>So l\u00e4uft der Ablauf:</b>\n"
                    f"1\ufe0f\u20e3 Du best\u00e4tigst hier mit Token \u2014 damit stehst du auf der L\u00f6schungsliste.\n"
                    f"2\ufe0f\u20e3 <b>2 Wochen</b> Bedenkzeit: Dein Zugang ist pausiert, aber alles bleibt erhalten. Jederzeit abbrechbar mit /abbruch.\n"
                    f"3\ufe0f\u20e3 Nach den 2 Wochen fragt dich der Bot sicherheitshalber NOCHMALS, ob du wirklich gel\u00f6scht werden willst.\n"
                    f"4\ufe0f\u20e3 Erst wenn du diese letzte Frage erneut mit ja beantwortest, wird ALLES endg\u00fcltig gel\u00f6scht.\n\n"
                    f"<b>Best\u00e4tigung (Schritt 1):</b> Wenn du sicher bist, sende:\n"
                    f"<code>/vergessen ja {token}</code>\n\n"
                    f"\u2139\ufe0f Wenn du die L\u00f6schung NICHT best\u00e4tigst, passiert nichts."))

            elif (text.startswith("/vergessen ja") or text.startswith("/vergessen best")
                  or text.startswith("/loeschen ja") or text.startswith("/löschen ja")):
                # ZWEI-STUFEN-LÖSCHUNG: Stufe 1 (Token 1) = auf die Löschungsliste,
                # Stufe 2 (Token 2 nach 2 Wochen) = endgültige Löschung.
                parts = text.split()
                antraege_e = load_loeschungen()
                at_self = antraege_e.get(cid_str)
                if len(parts) >= 3 and at_self and at_self.get("reask_token") \
                        and parts[2].strip() == at_self.get("reask_token"):
                    # STUFE 2: endgültige Löschung nach 2. ja-Bestätigung
                    execute_delete(cid_str)
                    antraege_e.pop(cid_str, None)
                    save_loeschungen(antraege_e)
                    logger.warning(f"LOESCHUNG ENDGÜLTIG (Stufe 2 ja): {chat_id} — 2 Wochen Wartezeit bestanden, 2x ja")
                    send_to(ADMIN_ID, (
                        f"\U0001f5d1\ufe0f <b>Benutzer endgültig gelöscht</b>\n"
                        f"Nutzer {esc((at_self.get('user_data', {}) or {}).get('username') or '?')} "
                        f"(ID {chat_id}) hat sich AUCH NACH DEN 2 WOCHEN Wartezeit f\u00fcrs L\u00f6schen entschieden "
                        f"(2. ja-Best\u00e4tigung).\n"
                        f"Benutzername, Beobachtungen und Zugang sind jetzt vollst\u00e4ndig entfernt."))
                    # Hinweis an die (nun gelöschte) chat_id — Zustellung meist erfolgreich
                    send_to(chat_id, (
                        "\u2705 Deine L\u00f6schung ist <b>abgeschlossen</b>.\n"
                        "Alle deine Daten wurden endgültig entfernt. "
                        "Falls du wiederkommen willst: einfach /start senden und mit /registrieren neu anmelden. \U0001f44b"))
                    continue
                usertoken = parts[2].strip() if len(parts) >= 3 else ""
                stored = users["users"][cid_str].get("loesch_token")
                if stored and stored == usertoken:
                    # Token passt — Löschung BESTÄTIGEN (Stufe 1 von 2: auf die Löschungsliste)
                    backup = backup_user_data(cid_str)
                    antraege = load_loeschungen()
                    antraege[cid_str] = backup
                    save_loeschungen(antraege)
                    # Sofort: User aus live-Userdatei deaktivieren (kann nichts mehr machen)
                    users["users"][cid_str]["registered"] = False
                    users["users"][cid_str]["orte"] = []
                    users["users"][cid_str]["einsatz_watches"] = []
                    users["users"][cid_str].pop("loesch_token", None)
                    save_users(users)
                    clear_state(os.path.join(STATE_DIR, f"user_{chat_id}.json"))
                    logger.warning(f"LOESCHUNG Stufe 1 bestätigt (Löschungsliste): {chat_id} — Nachfrage nach 2 Wochen, endgültig erst nach 2. ja")
                    send_to(chat_id, (
                        f"\u2705 Best\u00e4tigt \u2014 du stehst jetzt auf der <b>L\u00f6schungsliste</b>.\n\n"
                        f"\U0001f4c5 Letzte Nachfrage kommt am "
                        f"{datetime.fromisoformat(backup['delete_at']).strftime('%d.%m.%Y um %H:%M')} Uhr "
                        f"(2 Wochen Bedenkzeit).\n\n"
                        f"Dein Zugang ist ab jetzt pausiert \u2014 du kriegst keine Alarme mehr und kannst keine Befehle nutzen. "
                        f"Deine Daten (Benutzername, Beobachtungen) bleiben bis zur endg\u00fcltigen L\u00f6schung vollst\u00e4ndig erhalten.\n\n"
                        f"\U0001f504 Zum Abbrechen &amp; vollst\u00e4ndigen Wiederherstellen: /abbruch\n"
                        f"Beantwortest du die letzte Nachfrage mit ja, werden alle Daten endg\u00fcltig gel\u00f6scht."))
                    send_to(ADMIN_ID, (
                        f"\U0001f5d1\ufe0f <b>Benutzer m\u00f6chte gel\u00f6scht werden (Schritt 1)</b>\n"
                        f"User: {chat_id}\n"
                        f"Auf der L\u00f6schungsliste \u2014 letzte Nachfrage in 2 Wochen.\n"
                        f"Bei der zweiten ja-Best\u00e4tigung wird endg\u00fcltig gel\u00f6scht. Abbruch jederzeit via /abbruch &lt;ID&gt;."))
                else:
                    send_to(chat_id, (
                        "\u26d4\ufe0f Token stimmt nicht \u00fcberein.\n"
                        "Gib zuerst /loeschen ein, dann kopiere den token aus der Warnung\n"
                        "und sende: /vergessen ja &lt;token&gt;"))
                continue

            elif text == "/abbruch" or text.startswith("/abbruch "):
                # Lösch-Antrag abbrechen + restaurieren (jederzeit bis zur endgültigen Löschung)
                antraege = load_loeschungen()
                if cid_str not in antraege:
                    send_to(chat_id, "\u2139\ufe0f Es gibt keine laufende L\u00f6schung, die abgebrochen werden k\u00f6nnte.")
                    continue
                backup = antraege.pop(cid_str)
                save_loeschungen(antraege)
                ok = restore_user_data(cid_str, backup)
                if ok:
                    logger.info(f"LOESCHUNG abgebrochen + restauriert: {chat_id}")
                    ud_restored = users["users"].get(cid_str, {})
                    orte_count = len(ud_restored.get("orte", []))
                    send_to(chat_id, (
                        "\u2705 <b>L\u00f6schung ABGEBROCHEN \u2014 alles ist zur\u00fcck!</b>\n\n"
                        f"Dein Benutzername, deine {orte_count} Beobachtung(en) und dein kompletter Zugang "
                        "sind wiederhergestellt. Als w\u00e4re nichts gewesen.\n\n"
                        "Du bekommst ab sofort wieder deine Alarme. Willkommen zur\u00fcck! \U0001f692"))
                    send_to(ADMIN_ID, f"\u2139\ufe0f L\u00f6schung von User {chat_id} WURDE ABGEBROCHEN \u2014 User vollst\u00e4ndig restauriert.")
                else:
                    send_to(chat_id, "\u26a0\ufe0f Abbruch-Fehler \u2014 bitte Admin benachrichtigen.")
                    send_to(ADMIN_ID, f"\u26a0\ufe0f Restore fehlgeschlagen bei Abbruch des Users {chat_id} \u2014 manuelles Eingreifen n\u00f6tig!")
                continue

            elif text.startswith("/fehler"):
                # /fehler <Text>  — Fehlermeldung an Admin melden (User)
                # /fehler liste    — Log anzeigen (nur Admin)
                parts = text.split(None, 1)
                if len(parts) >= 2 and parts[1].lower() in ("list", "log", "alle"):
                    if not is_admin:
                        send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann die Log anzeigen.")
                        continue
                    lines = fehlermeldungen_lesen()
                    if lines is None:
                        send_to(chat_id, "\u26a0\ufe0f Fehler beim Lesen der Log-Datei.")
                        continue
                    if not lines:
                        send_to(chat_id, "\u2705 Keine Fehlermeldungen vorhanden.")
                        continue
                    send_to(chat_id, "\U0001f4dc <b>Fehlermeldungen (letzte 30)</b>\n" + "\n".join(esc(l) for l in lines))
                    continue
                if len(parts) < 2 or not parts[1].strip():
                    send_to(chat_id, (
                        "Usage: /fehler &lt;Beschreibung&gt;\n"
                        "Beispiel: /fehler Keine Alarm für Gmunden erhalten, obwohl Einsatz läuft\n\n"
                        "Deine Meldung geht an den Administrator und wird protokolliert."))
                    continue
                ftext = parts[1].strip()[:FEHLER_MAX_LEN]
                uname = (user_data.get("username") or "?")
                ok = log_fehlermeldung(cid_str, uname, ftext)
                send_to(chat_id, (
                    f"\u2705 Meldung protokolliert.\n"
                    f"\U0001f4dd '{esc(ftext[:120])}{'...' if len(ftext) > 120 else ''}'\n"
                    f"Der Administrator wurde informiert. Danke!"))
                send_to(ADMIN_ID, (
                    f"\U0001f6e0\ufe0f <b>Fehlermeldung von {esc(uname)} (ID {chat_id})</b>\n"
                    f"{esc(ftext)}\n\n"
                    f"\U0001f4c1 Protokolliert in fehlermeldungen.log"))
                if not ok:
                    send_to(ADMIN_ID, "\u26a0\ufe0f Achtung: Die Log-Datei konnte NICHT geschrieben werden!")

            elif text.startswith("/wunsch"):
                # /wunsch <Text>  — Funktionswunsch an Admin (User)
                # /wunsch liste    — Log anzeigen (nur Admin)
                parts = text.split(None, 1)
                if len(parts) >= 2 and parts[1].lower() in ("list", "liste", "log", "alle"):
                    if not is_admin:
                        send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann die W\u00fcnsche-Liste anzeigen.")
                        continue
                    wlines = wuensche_lesen()
                    if wlines is None:
                        send_to(chat_id, "\u26a0\ufe0f Fehler beim Lesen der W\u00fcnsche-Log.")
                        continue
                    if not wlines:
                        send_to(chat_id, "\u2705 Noch keine W\u00fcnsche vorhanden.")
                        continue
                    send_to(chat_id, "\U0001f4dc <b>W\u00fcnsche (letzte 30)</b>\n" + "\n".join(esc(l) for l in wlines))
                    continue
                if len(parts) < 2 or not parts[1].strip():
                    send_to(chat_id, (
                        "Usage: /wunsch <Wunsch>\n"
                        "Beispiel: /wunsch W\u00e4re cool wenn der Bot auch Eins\u00e4tze in Bayern anzeigen k\u00f6nnte\n\n"
                        "Dein Wunsch oder deine Idee geht direkt an den Administrator und wird protokolliert. "
                        "Sag mir einfach, was dir noch fehlt \u2014 neue Funktionen, \u00c4nderungen, alles willkommen!"))
                    continue
                wtext = parts[1].strip()[:WUNSCH_MAX_LEN]
                uname = (user_data.get("username") or "?")
                ok = log_wunsch(cid_str, uname, wtext)
                send_to(chat_id, (
                    f"\u2705 Wunsch protokolliert.\n"
                    f"\U0001f4dd '{esc(wtext[:120])}{'...' if len(wtext) > 120 else ''}'\n"
                    f"Der Administrator hat deine Idee bekommen. Danke!"))
                send_to(ADMIN_ID, (
                    f"\U0001f4a1 <b>Funktionswunsch von {esc(uname)} (ID {chat_id})</b>\n"
                    f"{esc(wtext)}\n\n"
                    f"\U0001f4c1 Protokolliert in wuensche.log"))
                if not ok:
                    send_to(ADMIN_ID, "\u26a0\ufe0f Achtung: Die W\u00fcnsche-Log konnte NICHT geschrieben werden!")

            elif text.startswith("/registrieren"):
                parts = text.split(None, 1)
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /registrieren &lt;Name&gt;\nBeispiel: /registrieren Max")
                    continue
                new_name = parts[1].strip()[:50]
                if not new_name:
                    send_to(chat_id, "Der Benutzername darf nicht leer sein.")
                    continue
                # Pr\u00fcfen ob Name bereits vergeben ist (case-insensitive)
                name_taken = False
                for uid, ud in users["users"].items():
                    if (ud.get("username") or "").lower() == new_name.lower() and uid != cid_str:
                        name_taken = True
                        break
                if name_taken:
                    send_to(chat_id, f"\u26a0\ufe0f Der Benutzername '{esc(new_name)}' ist bereits vergeben.\nBitte w\u00e4hle einen anderen Namen.")
                    continue
                users["users"][cid_str]["username"] = new_name
                save_users(users)
                send_to(chat_id, f"\u2705 Dein Benutzername wurde zu '{esc(new_name)}' ge\u00e4ndert.")

            elif text == "/id":
                send_to(chat_id, f"\U0001f194 Deine Chat-ID: {chat_id}")

            elif text == "/quellen" or text.startswith("/quellen "):
                # /quellen — Transparenz: Alle Datenquellen des Bots (Offenlegung, Legalität)
                send_to(chat_id, (
                    "\U0001f4da <b>Datenquellen dieses Bots</b>\n\n"
                    "Der Bot ist ein privates, inoffizielles Projekt \u2014 er liest ausschlie\u00dflich "
                    "\u00f6ffentlich zug\u00e4ngliche Quellen aus:\n\n"
                    "\U0001f692 <b>Feuerwehr-Eins\u00e4tze O\u00d6:</b> \u00d6ffentliche Einsatzseite des "
                    "O\u00f6. Landes-Feuerwehrverbandes \u2014 einsaetze.ooelfv.at\n"
                    f"\U0001f3d7 <b>{FF_NAME}-Historie</b> \u2014 einsaetze.at\n"
                    "\u26c8\ufe0f <b>Unwetter-Warnungen</b> \u2014 GeoSphere Austria (WarnAPI, amtliche "
                    "Warnungen; Daten gemeinfrei CC0 1.0) \u2014 warnungen.zamg.at / geosphere.at\n"
                    "🌊 <b>Pegel/Hochwasser</b> \u2014 Hydrographischer Dienst des Landes O\u00d6 "
                    "(Open Government Data, CC BY 3.0 AT) \u2014 hydro.ooe.gv.at\n"
                    "⚡ <b>Stromausf\u00e4lle</b> \u2014 \u00f6ffentliche St\u00f6rungskarte des Netzbetreibers "
                    "Netz Ober\u00f6sterreich \u2014 netzooe.at\n"
                    "❄️ <b>Lawinenlage</b> \u2014 Lawinenwarndienst des Landes O\u00d6 \u2014 "
                    "lawinenwarndienst-ooe.at\n"
                    "\U0001f4cd <b>Orts-Koordinaten</b> \u2014 OpenStreetMap (Nominatim, ODbL) \u2014 "
                    "openstreetmap.org\n\n"
                    "\u26a0\ufe0f Der Bot ist <b>kein offizielles Produkt</b> dieser Stellen und steht in "
                    "keiner Verbindung zu ihnen. Alle Angaben ohne Gew\u00e4hr \u2014 im Notfall gilt immer "
                    "die offizielle Alarmierung (Sirene, Funk, Pager, Notruf 122)."))

            elif text == "/warnungen" or text.startswith("/warnungen "):
                # /warnungen [Ort|Bezirks-Kürzel] — aktive amtliche Unwetter-Warnungen (GeoSphere)
                arg_w = text.split(None, 1)[1].strip()[:60] if text.startswith("/warnungen ") else ""
                ziel_orte = []
                if arg_w:
                    if len(arg_w) <= 3 and arg_w.isalpha():
                        # Bezirks-Kürzel: alle beobachteten Orte im Bezirk — Fallback: eigener Ort
                        try:
                            tag_w = parse_einsaetze_full(fetch_ooelfv(SOURCE_URL_TAG)) or []
                            ziel_orte = sorted({e.get("ort", "") for e in tag_w if such_bezirk_match(e, arg_w)})
                        except Exception:
                            ziel_orte = []
                    else:
                        ziel_orte = [arg_w]
                else:
                    ud_w = users["users"][cid_str]
                    ziel_orte = list(ud_w.get("orte", [])) + list(ud_w.get("einsatz_watches", []))
                if not ziel_orte:
                    send_to(chat_id, f"Usage: /warnungen &lt;Ort&gt;\nBeispiel: /warnungen {FF_NAME}\nOhne Ort: aktive Warnungen für deine beobachteten Orte.")
                    continue
                gefundene = []
                for oz in ziel_orte[:12]:
                    coords_w = _ort_koordinaten(oz)
                    if not coords_w:
                        continue
                    for w in fetch_unwetter(coords_w[0], coords_w[1]):
                        gefundene.append((oz, w))
                # Bezirks-/Ortsfilter anwenden (Ort-Teilmatch wie die Einsatz-Suche)
                such_w = arg_w.lower()
                if such_w and not (len(such_w) <= 3 and such_w.isalpha()):
                    gefundene = [(oz, w) for (oz, w) in gefundene if such_w in oz.lower() or such_w in _norm_q(oz)]
                if not gefundene:
                    send_to(chat_id, "\u2705 Keine aktiven Unwetter-Warnungen" + (f" für {esc(arg_w)}" if arg_w else " für deine beobachteten Orte.") + " (GeoSphere Austria).")
                    continue
                msg_w = "⛈️ <b>Aktive Unwetter-Warnungen</b> (GeoSphere Austria)\n\n"
                for oz, w in gefundene:
                    msg_w += (f"{_warnstufe_emoji(int(w['stufe']))} <b>{esc(w['warntyp'])}</b> (Stufe {w['stufe']}) — {esc(oz)}\n"
                              f"  {esc(w['begin'])} bis {esc(w['end'])}\n  {esc(w['text'])}\n\n")
                msg_w += "ℹ️ Beobachtete Orte werden automatisch auf Warnungen geprüft (ab Stufe 2 kommt der Alarm)."
                send_to(chat_id, msg_w, reply_markup=zeilen_keyboard([oz for oz, _ in gefundene[:12]]))

            elif text == "/lage":
                try:
                    html = fetch_ooelfv(SOURCE_URL)
                    einsaetze = parse_einsaetze_full(html)
                    if einsaetze:
                        m = re.search(r"Einsätze:\s*(\d+),\s*Feuerwehren:\s*(\d+)", html)
                        n = m.group(1) if m else "?"
                        msg_text = f"\U0001f4ca <b>Aktuelle Einsätze (OÖ): {n}</b>\n\n"
                        for e in einsaetze:
                            fw_count = len(e["feuerwehren"])
                            fw0 = e["feuerwehren"][0] if e["feuerwehren"] else {}
                            zeit = fw0.get("start", "?")
                            msg_text += f"{esc(e['typ'])} <b>{esc(e['ort'])}</b> ({esc(e['bezirk'])}): {esc(e['stichwort'])} — {fw_count} FW, ab {zeit}\n"
                        kb = zeilen_keyboard([e["ort"] for e in einsaetze])
                        send_to(chat_id, msg_text, reply_markup=kb)
                    else:
                        send_to(chat_id, "\u2705 Keine laufenden Einsätze in OÖ.")
                except Exception:
                    send_to(chat_id, "\u26a0\ufe0f Fehler beim Abruf.")

            elif text == "/offenhausen":
                try:
                    # Org-ID fehlt in der Config → automatisch über den FF-Index suchen
                    # (gleiches Verfahren wie bei /training, sonst ginge der Befehl
                    # bei der Default-Konfiguration ohne org_id kaputt).
                    org2 = FF_ORG_ID or find_einsaetze_at_org_id(FF_NAME)
                    if not org2:
                        send_to(chat_id, (
                            f"\u26a0\ufe0f Keine einsaetze.at-Org-ID für {esc(FF_NAME)} gefunden \u2014 "
                            "Historie-Befehl deaktiviert.\n"
                            "Org-ID in ~/.config/fw_bot/fw_bot.conf ([feuerwehr] org_id) nachtragen."))
                        continue
                    url2 = "https://www.einsaetze.at/organizations/%s" % org2
                    req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req2, timeout=15) as resp2:
                        html2 = resp2.read().decode("utf-8", errors="replace")
                    ops = _rsc_operations(html2)
                    cat_de = {"BRAND": "Brand", "TEE": "Technisch", "PERSON": "Personenrettung",
                              "UNWETTER": "Unwetter", "SONSTIGE": "Sonstige", "SELBST": "Übung"}
                    msg_text = f"\U0001f692 <b>{esc(FF_NAME)} — Letzte Einsätze</b>\n\n"
                    count = 0
                    for o in ops:
                        if count >= 5:
                            break
                        try:
                            d = datetime.strptime(o["dateKey"], "%Y-%m-%d").strftime("%d.%m.%Y")
                        except (KeyError, ValueError):
                            continue
                        zk = cat_de.get(o.get("categoryKey", ""), "Sonstige")
                        zeit = o.get("time", "");
                        ende = o.get("endTime") or ""
                        span = f"{zeit}–{ende}" if ende else zeit
                        msg_text += f"\U0001f4c5 {d}, {span} — {zk}: {esc(o.get('title', 'Einsatz'))}\n"
                        count += 1
                    if count == 0:
                        msg_text += "Keine Einsätze gefunden."
                    send_to(chat_id, msg_text)
                except Exception:
                    send_to(chat_id, "\u26a0\ufe0f Fehler beim Abruf.")

            elif text.startswith("/ort"):
                parts = text.split(None, 1)
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /ort &lt;Ort&gt; [Filter]\nBeispiel: /ort Lengau\nOptional: /ort Lengau brand (nur Brand-Einsätze)")
                    continue
                rest = parts[1].strip()
                gef_typ = None
                TYP_FILTERS = {"brand": "Brand", "technisch": "Technisch", "personenrettung": "Personenrettung", "unwetter": "Unwetter", "sonstige": "Sonstige"}
                # Optionales letztes Wort = Typ-Filter
                rest_parts = rest.rsplit(None, 1)
                if len(rest_parts) == 2 and rest_parts[1].lower() in TYP_FILTERS:
                    ort = rest_parts[0].strip()[:100]
                    gef_typ = TYP_FILTERS[rest_parts[1].lower()]
                else:
                    ort = rest[:100]
                orte = users["users"][cid_str].get("orte", [])
                existing_lower = [w.lower() for w in orte]
                # Ortsvorschläge bei Tippfehlern (einsaetze.at-Index) — vor der Duplikat-Prüfung,
                # Vorschlag-Buttons legen den Kandidaten mit GLEICHER Filterlogik an.
                if gef_typ is None and ort.lower() not in [n.lower() for n in _lade_ort_index()] and ort.lower() not in existing_lower:
                    vorsch = [v for v in _ort_vorschlaege(ort) if v.lower() != ort.lower()]
                    if vorsch:
                        reihen = []
                        for v in vorsch:
                            row = []
                            bv = btn_beobachten(v, dauerhaft=True)
                            if bv:
                                row.append({"text": "⭐ " + v, "callback_data": bv["callback_data"]})
                            row.append(btn_karte_url(v))
                            reihen.append(row)
                        send_to(chat_id, (
                            f"\u2753 Ort '{esc(ort)}' ist nicht in der Feuerwehr-Liste.\n"
                            f"Meintest du einen davon? (Klick = dauerhaft beobachten)"),
                            reply_markup={"inline_keyboard": reihen})
                        continue
                if ort.lower() in existing_lower:
                    # Ort existiert — falls ein Filter mitgegeben wurde, diesen updaten
                    if gef_typ:
                        ot = users["users"][cid_str].setdefault("ort_typen", {})
                        if ot.get(ort) == gef_typ:
                            send_to(chat_id, "\U0001f4cd '%s' wird bereits mit Filter '%s' beobachtet." % (esc(ort), gef_typ))
                        else:
                            ot[ort] = gef_typ
                            save_users(users)
                            send_to(chat_id, "\u2705 Filter für '%s' gesetzt: <b>nur %s</b>." % (esc(ort), gef_typ))
                    else:
                        send_to(chat_id, f"\u2139\ufe0f '{ort}' wird bereits beobachtet.")
                    continue
                if len(orte) >= MAX_ORTS_PER_USER:
                    register_limit_violation(cid_str, chat_id, f"Orts-Limit (max. {MAX_ORTS_PER_USER} /ort)")
                    continue
                if len(orte) + len(users["users"][cid_str].get("einsatz_watches", [])) >= MAX_WATCHES_PER_USER:
                    register_limit_violation(cid_str, chat_id, f"Gesamt-Limit (max. {MAX_WATCHES_PER_USER} Beobachtungen)")
                    continue
                orte.append(ort)
                users["users"][cid_str]["orte"] = orte
                if gef_typ:
                    users["users"][cid_str].setdefault("ort_typen", {})[ort] = gef_typ
                save_users(users)
                logger.info(f"Ort hinzugefügt: {ort} von User {chat_id}" + (f" (Filter: {gef_typ})" if gef_typ else ""))
                zusatz = f"\nFilter: <b>nur {esc(gef_typ)}</b>" if gef_typ else ""
                # Sofortiger Unwetter-Status für den neuen Ort (damit klar ist: nur kein Einsatz ≠ Ruhe)
                unw_text = ""
                try:
                    c_neu = _ort_koordinaten(ort)
                    if c_neu:
                        warns_neu = fetch_unwetter(c_neu[0], c_neu[1])
                        if warns_neu:
                            zeilen = []
                            for w in warns_neu:
                                zeilen.append(f"{_warnstufe_emoji(int(w['stufe']))} <b>{esc(w['warntyp'])}</b> (Stufe {w['stufe']}), {esc(w['begin'])} bis {esc(w['end'])}: {esc(w['text'])}")
                            unw_text = "\n⛈️ <b>Aktive Unwetter-Warnungen in " + esc(ort) + ":</b>\n" + "\n".join(zeilen)
                except Exception:
                    pass
                send_to(chat_id, f"\u2705 '{esc(ort)}' wird jetzt <b>dauerhaft</b> beobachtet.{zusatz}\nEinsätze UND Unwetter-Warnungen werden gemeldet.\nOrte: {len(orte)}{ unw_text }" + _strom_fremd_hinweis(ort))

            elif text.startswith("/einsatz"):
                parts = text.split(None, 1)
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /einsatz &lt;Ort&gt;\nBeispiel: /einsatz Lengau\nBeobachtet nur den aktuell laufenden Einsatz — wird nach Abschluss automatisch entfernt.")
                    continue
                ort = parts[1].strip()[:100]
                einsatz_watches = users["users"][cid_str].get("einsatz_watches", [])
                existing_lower = [w.lower() for w in einsatz_watches]
                # Ortsvorschläge auch bei /einsatz
                if ort.lower() not in [n.lower() for n in _lade_ort_index()] and ort.lower() not in existing_lower:
                    vorsch_e = [v for v in _ort_vorschlaege(ort) if v.lower() != ort.lower()]
                    if vorsch_e:
                        reihen_e = []
                        for v in vorsch_e:
                            row_e = []
                            bv_e = btn_beobachten(v)
                            if bv_e:
                                row_e.append({"text": "⏱️ " + v, "callback_data": bv_e["callback_data"]})
                            row_e.append(btn_karte_url(v))
                            reihen_e.append(row_e)
                        send_to(chat_id, (
                            f"\u2753 Ort '{esc(ort)}' ist nicht in der Feuerwehr-Liste.\n"
                            f"Meintest du einen davon? (Klick = laufenden Einsatz beobachten)"),
                            reply_markup={"inline_keyboard": reihen_e})
                        continue
                if ort.lower() in existing_lower:
                    send_to(chat_id, f"\u2139\ufe0f '{ort}' wird bereits als Einsatz beobachtet.")
                    continue
                if len(einsatz_watches) >= MAX_EINSATZ_WATCHES_PER_USER:
                    register_limit_violation(cid_str, chat_id, f"Einsatz-Limit (max. {MAX_EINSATZ_WATCHES_PER_USER} /einsatz)")
                    continue
                if len(users["users"][cid_str].get("orte", [])) + len(einsatz_watches) >= MAX_WATCHES_PER_USER:
                    register_limit_violation(cid_str, chat_id, f"Gesamt-Limit (max. {MAX_WATCHES_PER_USER} Beobachtungen)")
                    continue
                einsatz_watches.append(ort)
                users["users"][cid_str]["einsatz_watches"] = einsatz_watches
                save_users(users)
                logger.info(f"Einsatz-Beobachtung hinzugefügt: {ort} von User {chat_id}")
                ew_count = len(einsatz_watches)
                send_to(chat_id, f"\u2705 '{esc(ort)}' wird f\u00fcr den <b>aktuellen Einsatz</b> beobachtet.\nWird nach Abschlussbericht automatisch entfernt.\nTempor\u00e4re Einsatz-Beobachtungen: {ew_count}")

            elif text == "/unortall":
                if is_admin:
                    users["users"][cid_str]["orte"] = [FF_NAME]
                    users["users"][cid_str]["einsatz_watches"] = []
                    ot = users["users"][cid_str].get("ort_typen", {})
                    if ot:
                        ot.pop(FF_NAME, None)
                        users["users"][cid_str]["ort_typen"] = ot
                    save_users(users)
                    send_to(chat_id, f"\u2705 Alle dauerhaften Beobachtungen entfernt ({esc(FF_NAME)} bleibt aktiv), temporäre Einsatz-Beobachtungen gelöscht.")
                else:
                    users["users"][cid_str]["orte"] = []
                    users["users"][cid_str]["einsatz_watches"] = []
                    users["users"][cid_str].pop("ort_typen", None)
                    save_users(users)
                    send_to(chat_id, "\u2705 Alle Beobachtungen entfernt.")

            elif text.startswith("/unort"):
                parts = text.split(None, 1)
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /unort &lt;Ort&gt;")
                    continue
                ort = parts[1].strip()
                if is_admin and ort.lower() == FF_NAME.lower():
                    send_to(chat_id, f"\u26d4\ufe0f '{esc(FF_NAME)}' ist die Stammfeuerwehr und kann nicht entfernt werden.")
                    continue
                orte = users["users"][cid_str].get("orte", [])
                removed = False
                for i, w in enumerate(orte):
                    if w.lower() == ort.lower():
                        orte.pop(i)
                        removed = True
                        break
                if removed:
                    users["users"][cid_str]["orte"] = orte
                    ot = users["users"][cid_str].get("ort_typen", {})
                    for k in list(ot.keys()):
                        if k.lower() == ort.lower():
                            ot.pop(k)
                    save_users(users)
                    logger.info(f"Ort entfernt: {ort} von User {chat_id}")
                    send_to(chat_id, f"\u2705 '{esc(ort)}' wird nicht mehr beobachtet.")
                else:
                    send_to(chat_id, f"\u2139\ufe0f '{esc(ort)}' war nicht als Ort beobachtet.")

            elif text.startswith("/uneinsatz"):
                parts = text.split(None, 1)
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /uneinsatz &lt;Ort&gt;")
                    continue
                ort = parts[1].strip()
                einsatz_watches = users["users"][cid_str].get("einsatz_watches", [])
                removed = False
                for i, w in enumerate(einsatz_watches):
                    if w.lower() == ort.lower():
                        einsatz_watches.pop(i)
                        removed = True
                        break
                if removed:
                    users["users"][cid_str]["einsatz_watches"] = einsatz_watches
                    save_users(users)
                    logger.info(f"Einsatz-Beobachtung entfernt: {ort} von User {chat_id}")
                    send_to(chat_id, f"\u2705 Einsatz-Beobachtung '{esc(ort)}' entfernt.")
                else:
                    send_to(chat_id, f"\u2139\ufe0f '{esc(ort)}' war nicht als Einsatz beobachtet.")

            elif text == "/meinebeobachtungen":
                orte = users["users"][cid_str].get("orte", [])
                einsatz_watches = users["users"][cid_str].get("einsatz_watches", [])
                ort_typen = users["users"][cid_str].get("ort_typen", {})
                # Selbstheilung: temporäre Einsatz-Beobachtungen aufräumen, deren
                # Einsatz längst beendet ist (z. B. wenn der Beendet-Zweig durch
                # einen Neustart verpasst wurde). Live-Prüfung: aktuell-Liste ODER
                # Tag-Liste ohne Endzeit = läuft noch; sonst entfernen + Bericht.
                bereinigt = []
                if einsatz_watches:
                    try:
                        html_akt = fetch_ooelfv(SOURCE_URL)
                        liste_akt = parse_einsaetze_full(html_akt) or []
                        aktive_orte = [e.get("ort", "").lower() for e in liste_akt]
                        aktive_fw_namen = [fw["name"].lower() for e in liste_akt for fw in e.get("feuerwehren", [])]
                        tag_e_mb = parse_einsaetze_full(get_tag_html()) or []
                        laufende_neu = []
                        for w in einsatz_watches:
                            wl = w.lower()
                            laeuft_no = any(wl in ort for ort in aktive_orte) or any(wl in n for n in aktive_fw_namen)
                            if not laeuft_no:
                                # Tag-Liste: Einsatz heute vorhanden OHNE Endzeit = läuft noch
                                for te in tag_e_mb:
                                    if any(wl in fw["name"].lower() for fw in te.get("feuerwehren", [])) and any(not fw.get("end") for fw in te.get("feuerwehren", [])):
                                        laeuft_no = True
                                        break
                            if laeuft_no:
                                laufende_neu.append(w)
                            else:
                                bereinigt.append(w)
                        if bereinigt:
                            einsatz_watches = laufende_neu
                            users["users"][cid_str]["einsatz_watches"] = einsatz_watches
                            save_users(users)
                            logger.info(f"/meinebeobachtungen: {len(bereinigt)} beendete Einsatz-Watch(es) entfernt: {bereinigt} (User {cid_str})")
                    except Exception as mb_err:
                        logger.debug(f"/meinebeobachtungen Aufräumen Fehler: {mb_err}")
                total = len(orte) + len(einsatz_watches)
                if total == 0:
                    if bereinigt:
                        send_to(chat_id, "🧹 Beendete Einsatz-Beobachtungen wurden aufgeräumt: " + esc(", ".join(bereinigt)) + ".\nDu hast aktuell keine Beobachtungen.\nMit /ort &lt;Ort&gt; einen Ort dauerhaft beobachten.\nMit /einsatz &lt;Ort&gt; nur den aktuellen Einsatz beobachten.")
                    else:
                        send_to(chat_id, "\U0001f4cb Du hast aktuell keine Beobachtungen.\nMit /ort &lt;Ort&gt; einen Ort dauerhaft beobachten.\nMit /einsatz &lt;Ort&gt; nur den aktuellen Einsatz beobachten.")
                else:
                    msg = f"\U0001f4cb <b>Deine Beobachtungen ({total}):</b>\n\n"
                    if orte:
                        msg += f"<b>Orte (dauerhaft):</b>\n"
                        for i, w in enumerate(orte):
                            tag = " \U0001f451" if (is_admin and w.lower() == FF_NAME.lower()) else ""
                            filt = ort_typen.get(w)
                            suffix = " <i>(nur %s)</i>" % esc(filt) if filt else ""
                            msg += f"  {i+1}. {esc(w)}{tag}{suffix}\n"
                    if einsatz_watches:
                        msg += f"\n<b>Einsätze (temporär):</b>\n"
                        for i, w in enumerate(einsatz_watches):
                            msg += f"  {i+1}. {esc(w)} \u23f3\n"
                    if bereinigt:
                        msg += "\n🧹 Beendet und entfernt: " + esc(", ".join(bereinigt)) + " (Einsatz ist fertig)"
                    send_to(chat_id, msg)

            elif text == "/stumm" or text.startswith("/stumm "):
                arg = text.split(None, 1)
                arg1 = arg[1].strip().lower() if len(arg) >= 2 else ""
                if arg1 in ("off", "aus"):
                    users["users"][cid_str]["silent"] = False
                    save_users(users)
                    send_to(chat_id, "\u2705 Stiller Modus <b>ausgeschaltet</b>. Du bekommst wieder Alarm-Nachrichten.")
                elif arg1 == "0":
                    users["users"][cid_str].pop("quiet_hours", None)
                    save_users(users)
                    send_to(chat_id, "\U0001f315 Stillfenster <b>gelöscht</b>. Alarme kommen wieder rund um die Uhr direkt an.")
                elif arg1 and "-" in arg1:
                    zeiten = arg1.split("-", 1)
                    ok_f = False
                    try:
                        a, b = int(zeiten[0]), int(zeiten[1])
                        ok_f = 0 <= a <= 23 and 0 <= b <= 23 and a != b
                    except ValueError:
                        ok_f = False
                    if not ok_f:
                        send_to(chat_id, "\u26a0\ufe0f Ungültiges Fenster. Format: /stumm 22-07 (Stunde 0-23).\nBeispiel: /stumm 22-07 = keine Alarme zwischen 22 und 7 Uhr.")
                    else:
                        users["users"][cid_str]["quiet_hours"] = "%d-%d" % (a, b)
                        save_users(users)
                        send_to(chat_id, "\U0001f319 Stillfenster gesetzt: <b>%02d:00 bis %02d:00</b>.\nIm Fenster werden Alarme <b>gesammelt</b> und dir nach dem Fenster als Sammel-Meldung zugestellt.\nLöschen mit /stumm 0" % (a, b))
                elif arg1 and arg1 not in ("off", "aus"):
                    # Status anzeigen wenn unbekanntes Argument
                    silent = users["users"][cid_str].get("silent", False)
                    qh = users["users"][cid_str].get("quiet_hours")
                    q_txt = qh if qh else "keins"
                    s_txt = "AKTIV" if silent else "AUS"
                    send_to(chat_id, "\U0001f515 Stiller Modus: <b>%s</b>\n\U0001f319 Stillfenster: <b>%s</b>\n\n/stumm = stiller Modus an\n/stumm aus = stiller Modus aus\n/stumm 22-07 = Stillfenster setzen\n/stumm 0 = Stillfenster löschen" % (s_txt, esc(q_txt)))
                else:
                    users["users"][cid_str]["silent"] = True
                    save_users(users)
                    send_to(chat_id, "\U0001f515 Stiller Modus <b>eingeschaltet</b>. Du bekommst keine Alarm-Nachrichten mehr.\nAlle Befehle bleiben nutzbar.\nAusschalten mit: /stumm aus")

            elif text == "/heute":
                orte = users["users"][cid_str].get("orte", [])
                einsatz_watches = users["users"][cid_str].get("einsatz_watches", [])
                all_watches = orte + einsatz_watches
                if not all_watches:
                    send_to(chat_id, "\u2139\ufe0f Du hast keine beobachteten Orte.\nMit /ort &lt;Ort&gt; kannst du Orte hinzufügen.")
                    continue
                try:
                    tag_html = fetch_ooelfv(SOURCE_URL_TAG)
                    tag_einsaetze = parse_einsaetze_full(tag_html)
                    if not tag_einsaetze:
                        send_to(chat_id, "Keine Einsätze heute für deine beobachteten Orte.")
                        continue
                    matched_today = []
                    for e in tag_einsaetze:
                        for watch in all_watches:
                            if einsatz_matches_watch(e, watch):
                                matched_today.append(e)
                                break
                    if not matched_today:
                        send_to(chat_id, "Keine Einsätze heute für deine beobachteten Orte.")
                        continue
                    msg = f"\U0001f4c5 <b>Einsätze heute für deine Orte ({len(matched_today)}):</b>\n\n"
                    for e in matched_today:
                        fw0 = e["feuerwehren"][0] if e["feuerwehren"] else {}
                        start = fw0.get("start", "?")
                        # Endzeit: letzte FW mit end-Zeit
                        endzeiten = [fw["end"] for fw in e["feuerwehren"] if fw.get("end")]
                        end_zeit = endzeiten[-1] if endzeiten else None
                        if end_zeit:
                            end_display = end_zeit.split()[-1] if " " in end_zeit else end_zeit
                            dauer = calc_dauer(start, end_zeit)
                            end_line = f"Ende: {end_display}"
                        else:
                            dauer = calc_dauer(start)
                            end_line = "läuft"
                        start_display = start.split()[-1] if " " in start else start
                        msg += (
                            f"{esc(e['typ'])} — <b>{esc(e['ort'])}</b> ({esc(e['bezirk'])})\n"
                            f"  Stichwort: {esc(e['stichwort'])}\n"
                            f"  Start: {start_display} | {end_line} | Dauer: {dauer}\n"
                            f"  FW: {esc(fw_namen(e['feuerwehren']))}\n\n"
                        )
                    send_to(chat_id, msg)
                except Exception:
                    send_to(chat_id, "\u26a0\ufe0f Fehler beim Abruf der heutigen Einsätze.")

            elif text == "/statistik" or text.startswith("/statistik "):
                arg_ort = text.split(None, 1)[1].strip()[:100] if text.startswith("/statistik ") else ""
                if arg_ort:
                    # Statistik für einen einzelnen Ort (z.B. /statistik Lengau)
                    send_to(chat_id, f"\U0001f4ca <b>Einsatzstatistik {esc(arg_ort)}</b> (letzte 12 Monate)\nLade Daten von einsaetze.at …")
                    s = fetch_einsaetze_at_stats(arg_ort)
                    if not s or not s.get("gesamt"):
                        send_to(chat_id, f"\u2139\ufe0f Keine Einsatzdaten für {esc(arg_ort)} gefunden (letztes Jahr).\nHinweis: Die Feuerwehr muss auf einsaetze.at gelistet sein.")
                        continue
                    total_stats, per_ort, all_watches = s, {arg_ort: s}, [arg_ort]
                else:
                    orte = users["users"][cid_str].get("orte", [])
                    einsatz_watches = users["users"][cid_str].get("einsatz_watches", [])
                    all_watches = orte + einsatz_watches
                    if not all_watches:
                        send_to(chat_id, "\u2139\ufe0f Du hast keine beobachteten Orte.\nMit /ort &lt;Ort&gt; kannst du Orte hinzufügen.")
                        continue
                    send_to(chat_id, "\U0001f4ca <b>Einsatzstatistik</b> (letzte 12 Monate)\nLade Daten von einsaetze.at …")
                    total_stats = {"gesamt": 0, "Brand": 0, "Technisch": 0, "Personenrettung": 0, "Sonstige": 0}
                    found_any = False
                    per_ort = {}
                    for ort in all_watches:
                        s = fetch_einsaetze_at_stats(ort)
                        if s and s["gesamt"] > 0:
                            found_any = True
                            per_ort[ort] = s
                            for key in total_stats:
                                total_stats[key] += s[key]
                    if not found_any:
                        send_to(chat_id, "\u2139\ufe0f Keine Einsatzdaten für deine beobachteten Orte gefunden (letztes Jahr).")
                        continue
                msg = (
                    f"\U0001f4ca <b>Einsatzstatistik — letzte 12 Monate</b>\n"
                    + (f"Ort: {esc(arg_ort)}\n\n" if arg_ort else f"Beobachtete Orte: {len(all_watches)}\n\n")
                    + f"<b>Gesamt: {total_stats['gesamt']}</b>\n"
                    + f"\U0001f534 Brand: {total_stats['Brand']}\n"
                    + f"\U0001f535 Technisch: {total_stats['Technisch']}\n"
                    + f"\U0001f7e1 Personenrettung: {total_stats['Personenrettung']}\n"
                    + f"\U0001f7e2 Sonstige: {total_stats['Sonstige']}\n"
                )
                if len(per_ort) > 1:
                    msg += "\n<b>Pro Ort:</b>\n"
                    for ort, s in per_ort.items():
                        msg += f"  {esc(ort)}: {s['gesamt']} (Brand {s['Brand']}, Tech {s['Technisch']}, Pers {s['Personenrettung']}, Sonst {s['Sonstige']})\n"
                send_to(chat_id, msg)
                # PNG-Diagramm wenn Pillow verfügbar
                try:
                    import io as _io
                    from PIL import Image, ImageDraw
                    cats = [("Brand", None), ("Technisch", None), ("Personenrettung", None), ("Sonstige", None)]
                    mx = max([total_stats[c[0]] for c in cats] + [1])
                    bW, bH = 560, 80 + 70 * len(cats)
                    img = Image.new("RGB", (bW, bH), (18, 18, 24))
                    from PIL import ImageDraw
                    dr = ImageDraw.Draw(img)
                    y = 30
                    max_bar = float(max([total_stats[c[0]] for c in cats] + [1]))
                    for name, emoji in cats:
                        val = total_stats[name]
                        w = int((bW - 200) * (val / max_bar)) if val else 2
                        dr.text((20, y + 8), "%s: %d" % (name, val), fill=(240, 240, 240))
                        dr.rectangle([170, y, 170 + w, y + 26], fill=(235, 70, 50) if name == "Brand" else (50, 120, 235) if name == "Technisch" else (235, 190, 50) if name == "Personenrettung" else (80, 200, 90))
                        y += 70
                    dr.text((20, 8), "Einsatzstatistik 12 Monate", fill=(255, 255, 255))
                    buf = _io.BytesIO()
                    img.save(buf, format="PNG")
                    send_photo(chat_id, buf.getvalue(), "Einsatzstatistik 12 Monate")
                except Exception as chart_err:
                    logger.debug(f"Statistik-Diagramm übersprungen: {chart_err}")

            elif text == "/brand" or text.startswith("/brand ") or text == "/technisch" or text.startswith("/technisch ") or text == "/personenrettung" or text.startswith("/personenrettung ") or text == "/unwetter" or text.startswith("/unwetter ") or text == "/sonstiges" or text.startswith("/sonstiges "):
                # Typ-Abfrage: /brand [Ort|Bezirk-KKZ], /technisch ..., /sonstiges ...
                TYP_ABFRAGEN = {
                    "/brand": ("Brand", "🔴", "Brände"),
                    "/technisch": ("Technisch", "🔵", "Technische Einsätze"),
                    "/personenrettung": ("Personenrettung", "🟡", "Personenrettungen"),
                    "/unwetter": ("Unwetter", "🟠", "Unwetter-Einsätze"),
                    "/sonstiges": ("Sonstige", "🟢", "Sonstige Einsätze"),
                }
                cmd_typ = text.split(None, 1)[0]
                such_typ, emoji, plural = TYP_ABFRAGEN[cmd_typ]
                such = text.split(None, 1)[1].strip()[:100] if text.startswith(cmd_typ + " ") else ""
                such_lower = such.lower()
                such_ist_bezirk = len(such_lower) <= 3 and such_lower.isalpha()
                if not such_lower:
                    send_to(chat_id, "Usage: %s &lt;Ort oder Bezirks-Kürzel&gt;\nBeispiele: /brand Lengau — laufende Brände in Lengau\n/brand WL — alle laufenden Brände im Bezirk Wels-Land" % cmd_typ)
                    continue
                try:
                    einsaetze_a = parse_einsaetze_full(fetch_ooelfv(SOURCE_URL))
                except Exception:
                    einsaetze_a = []
                if not einsaetze_a:
                    # Aktuell-Seite leer -> Tag-Seite (auch beendete des heutigen Tages)
                    try:
                        einsaetze_a = parse_einsaetze_full(get_tag_html())
                    except Exception:
                        einsaetze_a = []
                if such_ist_bezirk:
                    treffer = [e for e in einsaetze_a if such_typ in e.get("typ", "") and such_bezirk_match(e, such_lower)]
                else:
                    treffer = [e for e in einsaetze_a if such_typ in e.get("typ", "") and (such_lower in e.get("ort", "").lower() or any(such_lower in fw["name"].lower() for fw in e.get("feuerwehren", [])))]
                if not treffer:
                    if such_ist_bezirk:
                        send_to(chat_id, "\u2705 Es gibt aktuell keine %s im Bezirk %s." % (plural, esc(such.upper())))
                    else:
                        send_to(chat_id, "\u2705 Es gibt aktuell keine %s in %s." % (plural, esc(such)))
                    continue
                if such_ist_bezirk:
                    msg = "%s <b>%s heute im Bezirk %s (%d):</b>\n\n" % (emoji, plural, esc(such.upper()), len(treffer))
                else:
                    msg = "%s <b>%s in %s oder Umgebung (%d):</b>\n\n" % (emoji, plural, esc(such), len(treffer))
                for e in treffer:
                    fw0 = e["feuerwehren"][0] if e["feuerwehren"] else {}
                    start_d = fw0.get("start", "?").split()[-1] if fw0.get("start") else "?"
                    msg += "%s <b>%s</b> (%s): %s\n  FW: %s, ab %s\n\n" % (esc(e["typ"]), esc(e["ort"]), esc(e["bezirk"]), esc(e["stichwort"]), esc(fw_namen(e["feuerwehren"])), esc(start_d))
                send_to(chat_id, msg, reply_markup=zeilen_keyboard([e["ort"] for e in treffer]))

            elif text == "/umkreis" or text.startswith("/umkreis "):
                # /umkreis [km] — laufende Einsätze im Radius um die beobachteten Orte
                args = text.split(None, 1)
                radius_km = 15
                if len(args) >= 2:
                    try:
                        radius_km = max(1, min(100, int(args[1].strip())))
                    except ValueError:
                        send_to(chat_id, "Usage: /umkreis [km]\nBeispiel: /umkreis 20 — laufende Einsätze im 20-km-Umkreis deiner Orte")
                        continue
                orte_user = users["users"][cid_str].get("orte", []) + users["users"][cid_str].get("einsatz_watches", [])
                if not orte_user:
                    send_to(chat_id, "\u2139\ufe0f Du hast keine beobachteten Orte. Mit /ort &lt;Ort&gt; zuerst Orte hinzufügen.")
                    continue
                punkte = []
                for o in orte_user:
                    c = _ort_koordinaten(o)
                    if c:
                        punkte.append((o, c[0], c[1]))
                if not punkte:
                    send_to(chat_id, "\u26a0\ufe0f Konnte für keine deiner Orte Koordinaten ermitteln.")
                    continue
                send_to(chat_id, "\U0001f4cdSuche laufende Einsätze im Umkreis …")
                try:
                    einsaetze_all_um = parse_einsaetze_full(fetch_ooelfv(SOURCE_URL))
                except Exception:
                    send_to(chat_id, "\u26a0\ufe0f Fehler beim Abruf der aktuellen Einsätze.")
                    continue
                treffer_um = []
                for e in einsaetze_all_um:
                    c_e = _ort_koordinaten(e.get("ort", ""))
                    if not c_e:
                        continue
                    for (o_n, la, lo) in punkte:
                        d = _haversine_km(la, lo, c_e[0], c_e[1])
                        if d <= radius_km:
                            treffer_um.append((d, o_n, e))
                            break
                if not treffer_um:
                    send_to(chat_id, f"\u2705 Keine laufenden Einsätze im {radius_km}-km-Umkreis deiner Orte.")
                    continue
                treffer_um.sort(key=lambda x: x[0])
                msg = f"\U0001f4cd <b>Laufende Einsätze im Umkreis {radius_km} km</b>\n\n"
                for d, o_n, e in treffer_um:
                    fw0 = e["feuerwehren"][0] if e["feuerwehren"] else {}
                    msg += f"{esc(e['typ'])} <b>{esc(e['ort'])}</b>: {esc(e['stichwort'])}\n  {d:.0f} km von {esc(o_n)} · FW: {esc(fw_namen(e['feuerwehren']))}\n\n"
                send_to(chat_id, msg, reply_markup=zeilen_keyboard([e["ort"] for _, _, e in treffer_um]))

            elif text.startswith("/bezirk"):
                parts = text.split(None, 1)
                kz = parts[1].strip().upper()[:12] if len(parts) >= 2 else ""
                if not kz:
                    send_to(chat_id, "Usage: /bezirk &lt;Kürzel&gt;\nBeispiel: /bezirk WL (Wels-Land)")
                    continue
                try:
                    tag_html = fetch_ooelfv(SOURCE_URL_TAG)
                    tag_einsaetze = parse_einsaetze_full(tag_html)
                    hit = [e for e in tag_einsaetze if such_bezirk_match(e, kz)]
                    if not hit:
                        send_to(chat_id, "\u2705 Keine Einsätze heute im Bezirk %s." % esc(kz))
                        continue
                    msg = "\U0001f4c5 <b>Einsätze heute im Bezirk %s (%d):</b>\n\n" % (esc(kz), len(hit))
                    for e in hit:
                        fw0 = e["feuerwehren"][0] if e["feuerwehren"] else {}
                        start = fw0.get("start", "?")
                        start_d = start.split()[-1] if " " in start else start
                        msg += "%s — <b>%s</b>: %s\n  FW: %s, ab %s\n\n" % (esc(e["typ"]), esc(e["ort"]), esc(e["stichwort"]), esc(fw_namen(e["feuerwehren"])), esc(start_d))
                    send_to(chat_id, msg, reply_markup=zeilen_keyboard([e["ort"] for e in hit]))
                except Exception:
                    send_to(chat_id, "\u26a0\ufe0f Fehler beim Abruf der Bezirks-Einsätze.")

            elif text == "/training":
                send_to(chat_id, f"\U0001f3af <b>Übungen {esc(FF_NAME)}</b>\nLade Übungs-Historie von einsaetze.at …")
                org_id = find_einsaetze_at_org_id(FF_NAME)
                if not org_id:
                    send_to(chat_id, f"\u26a0\ufe0f Keine Verbindung zu einsaetze.at für {esc(FF_NAME)} gefunden.")
                    continue
                try:
                    url_t = "https://www.einsaetze.at/organizations/%s?kategorie=SELBST" % org_id
                    req_t = urllib.request.Request(url_t, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req_t, timeout=15) as resp:
                        html_t = resp.read().decode("utf-8", errors="replace")
                    ops = _rsc_operations(html_t)
                    cutoff_t = (datetime.now() - timedelta(days=365)).date()
                    ueb = []
                    for o in ops:
                        try:
                            d = datetime.strptime(o.get("dateKey", ""), "%Y-%m-%d").date()
                        except (ValueError, TypeError):
                            continue
                        if d >= cutoff_t:
                            ueb.append((d, str(o.get("title", "") or o.get("name", "") or "Übung")))
                    ueb.sort(reverse=True)
                    if not ueb:
                        send_to(chat_id, "\U0001f468\u200d\U0001f680 Keine Übungsdaten gefunden (einsaetze.at liefert für Übungen manchmal keine Daten — bekannte Einschränkung).")
                        continue
                    msg_t = "\U0001f3af <b>Übungen %s</b> (12 Monate: %d)\n\nFür die letzten %d Übungen:\n" % (esc(FF_NAME), len(ueb), min(10, len(ueb)))
                    for d, tit in ueb[:10]:
                        msg_t += "\U0001f4c5 %s — %s\n" % (d.strftime("%d.%m.%Y"), esc(tit))
                    send_to(chat_id, msg_t)
                except Exception as ex:
                    logger.error(f"/training Fehler: {ex}")
                    send_to(chat_id, "\u26a0\ufe0f Fehler beim Abruf der Übungsdaten.")

            elif text == "/qr_code":
                send_to(chat_id, "\U0001f4f2 Erstelle QR-Code …")
                try:
                    import qrcode
                    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=2)
                    q.add_data("https://t.me/feuerwehroff_bot")
                    q.make(fit=True)
                    import io
                    buf_qr = io.BytesIO()
                    q.make_image(fill_color="black", back_color="white").save(buf_qr, format="PNG")
                    ok_qr = send_photo(chat_id, buf_qr.getvalue(),
                                       "\U0001f517 Feuerwehr-Monitor Bot \u2014 weitergeben und scannen: https://t.me/feuerwehroff_bot")
                    if not ok_qr:
                        send_to(chat_id, "\u26a0\ufe0f QR-Code konnte nicht gesendet werden.")
                except ImportError:
                    send_to(chat_id, "\u26a0\ufe0f QR-Bibliothek fehlt auf dem Server — Admin wurde informiert.")
                    logger.error("qrcode-Paket fehlt für /qr_code (pip3 install --user qrcode)")
                except Exception as ex:
                    logger.error(f"/qr_code Fehler: {ex}")
                    send_to(chat_id, "\u26a0\ufe0f QR-Code konnte nicht erzeugt werden.")

            elif text == "/wochen":
                wk = users["users"][cid_str].get("week_digest", False)
                wk_neu = not wk
                users["users"][cid_str]["week_digest"] = wk_neu
                save_users(users)
                if wk_neu:
                    send_to(chat_id, "\u2705 Wochenrückblick <b>aktiviert</b>.\nJeden Sonntag um 20:00 bekommst du eine Zusammenfassung der Einsätze in deinen Orten der letzten 7 Tage.\nAusschalten mit /wochen")
                else:
                    send_to(chat_id, "\u2705 Wochenrückblick <b>deaktiviert</b>.")

            # ── Admin-Befehle ──
            elif text.startswith("/aufnehmen"):
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                parts = text.split()
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /aufnehmen &lt;ID&gt; [Name]\nBeispiel: /add 123456789 Lara")
                    continue
                try:
                    new_id = int(parts[1])
                except ValueError:
                    send_to(chat_id, "Ung\u00fcltige Chat-ID. Muss eine Zahl sein.")
                    continue
                if new_id <= 0:
                    send_to(chat_id, "Ung\u00fcltige Chat-ID. Muss positiv sein.")
                    continue
                new_id_str = str(new_id)
                if new_id == ADMIN_ID:
                    send_to(chat_id, "\u2139\ufe0f Das bist du selbst, Admin.")
                    continue
                if new_id_str in users["users"]:
                    send_to(chat_id, f"\u2139\ufe0f ID {new_id} ist bereits berechtigt.")
                    continue
                # ── Kapazitäts-Limit auch für Admin-Anlagen ──
                if len(users["users"]) >= MAX_USERS:
                    send_to(chat_id, (
                        f"\U0001f6d1 Kapazitäts-Limit erreicht ({len(users['users'])}/{MAX_USERS} Einträge).\n"
                        "Lösche zuerst Benutzer (z. B. mit /entfernen), um neue anzulegen \u2014 "
                        "oder erhöhe MAX_USERS im Skript."))
                    continue
                if len(parts) >= 3:
                    uname = " ".join(parts[2:])[:50]
                    users["users"][new_id_str] = {
                        "username": uname, "is_admin": False,
                        "orte": [], "einsatz_watches": [], "registered": True,
                        "added_at": datetime.now().isoformat()
                    }
                    save_users(users)
                    logger.info(f"User hinzugefügt: {new_id} ({uname})")
                    send_to(chat_id, f"\u2705 Benutzer {new_id} hinzugef\u00fcgt.\nName: {esc(uname)}\nDer Benutzer ist sofort einsatzbereit.")
                    send_to(new_id, f"\U0001f389 Du wurdest für den Feuerwehr-Monitor Bot freigeschaltet!\nSende /start für die Befehlsliste.")
                else:
                    users["users"][new_id_str] = {
                        "username": "", "is_admin": False,
                        "orte": [], "einsatz_watches": [], "registered": False,
                        "added_at": datetime.now().isoformat()
                    }
                    save_users(users)
                    logger.info(f"User hinzugefügt (unregistriert): {new_id}")
                    send_to(chat_id, f"\u2705 Benutzer {new_id} hinzugefügt.\nDer Benutzer muss sich beim ersten /start mit /registrieren &lt;Name&gt; registrieren.")

            elif text.startswith("/entfernen"):
                parts = text.split()
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /entfernen &lt;ID&gt;")
                    continue
                try:
                    rm_id = int(parts[1])
                except ValueError:
                    send_to(chat_id, "Ung\u00fcltige Chat-ID. Muss eine Zahl sein.")
                    continue
                # ── Admin-ID-Schutz VOR is_admin-Check (gilt für ALLE User) ──
                if rm_id == ADMIN_ID:
                    # Admin kann sich nicht selbst bannen
                    if chat_id == ADMIN_ID:
                        send_to(chat_id, "\u2139\ufe0f Du kannst dich nicht selbst entfernen, Admin.")
                        continue
                    # ── Auto-Ban bei Admin-Remove-Versuch ──
                    admin_remove_attempts = users["users"][cid_str].get("admin_remove_attempts", 0)
                    admin_remove_attempts += 1
                    users["users"][cid_str]["admin_remove_attempts"] = admin_remove_attempts
                    save_users(users)

                    if admin_remove_attempts >= 3:
                        # AUTO-BANN: Admin-Rang entziehen, 24h Bann
                        ban_until_dt = datetime.now() + timedelta(hours=24)
                        users["users"][cid_str]["ban_until"] = ban_until_dt.isoformat()
                        users["users"][cid_str]["is_admin"] = False
                        users["users"][cid_str]["registered"] = False
                        users["users"][cid_str]["orte"] = []
                        users["users"][cid_str]["einsatz_watches"] = []
                        users["users"][cid_str]["admin_remove_attempts"] = 0
                        save_users(users)
                        clear_state(os.path.join(STATE_DIR, f"user_{chat_id}.json"))
                        attacker_name = users["users"][cid_str].get("username", "?")
                        logger.warning(f"AUTO-BANN: User {chat_id} ({attacker_name}) hat 3x versucht den Admin zu entfernen. 24h Bann aktiv.")
                        send_to(chat_id, "\U0001f6ab\ufe0f <b>AUTOMATISCHER BANN</b>\nDu hast 3x versucht, den Admin zu entfernen.\nDu wurdest f\u00fcr 24 Stunden gebannt und hast alle Rechte verloren.\nNach Ablauf bist du wieder freigegeben.")
                        # Admin benachrichtigen
                        send_to(ADMIN_ID, f"\U0001f6a8 <b>SICHERHEITS-ALARM</b>\nUser {chat_id} ({esc(attacker_name)}) hat 3x versucht, dich zu entfernen.\nWurde automatisch f\u00fcr 24h gebannt + Admin-Rechte entzogen.")
                    else:
                        send_to(chat_id, f"\u26d4\ufe0f Die Admin-ID kann NICHT entfernt werden! Sch\u00f6ner Versuch \U0001f60f\n\u26a0\ufe0f Warnung {admin_remove_attempts}/3 \u2014 Bei 3 Versuchen wirst du automatisch f\u00fcr 24h gebannt.")
                        if admin_remove_attempts == 1:
                            attacker_name = users["users"][cid_str].get("username", "?")
                            send_to(ADMIN_ID, f"\u26a0\ufe0f Sicherheits-Hinweis: User {chat_id} ({esc(attacker_name)}) hat versucht, dich zu entfernen. (1/3)")
                    continue
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                rm_str = str(rm_id)
                if rm_str not in users["users"]:
                    send_to(chat_id, f"\u2139\ufe0f ID {rm_id} ist nicht berechtigt.")
                    continue
                rm_name = users["users"][rm_str].get("username", "?")
                del users["users"][rm_str]
                save_users(users)
                clear_state(os.path.join(STATE_DIR, f"user_{rm_id}.json"))
                logger.info(f"User entfernt: {rm_id} ({rm_name})")
                send_to(chat_id, f"\u2705 Benutzer {rm_id} ({esc(rm_name)}) entfernt.")
                send_to(rm_id, "\U0001f6ab\ufe0f Deine Berechtigung für den Feuerwehr-Monitor Bot wurde entfernt.")

            elif text == "/benutzer":
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                all_users = users["users"]
                msg = f"\U0001f4cb <b>Benutzer ({len(all_users)}):</b>\n"
                sorted_users = sorted(all_users.items(), key=lambda x: (not x[1].get("is_admin", False), x[0]))
                for i, (cid, ud) in enumerate(sorted_users):
                    name = ud.get("username", "")
                    admin_tag = " \U0001f451 ADMIN" if ud.get("is_admin") else ""
                    reg_tag = "" if ud.get("registered") else " (nicht registriert)"
                    orte = ud.get("orte", [])
                    ews = ud.get("einsatz_watches", [])
                    watch_parts = []
                    if orte: watch_parts.append(f"Orte: {', '.join(orte)}")
                    if ews: watch_parts.append(f"Einsätze: {', '.join(ews)}")
                    watch_str = f"[{'; '.join(watch_parts)}]" if (orte or ews) else "[keine Beobachtungen]"
                    msg += f"  {i+1}. {cid} — {esc(name or '?')}{admin_tag}{reg_tag} {watch_str}\n"
                send_to(chat_id, msg)

            elif text.startswith("/verwalten"):
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                parts = text.split()
                if len(parts) < 3:
                    send_to(chat_id, "Usage: /verwalten &lt;ID&gt; ort &lt;Ort&gt;\n     /verwalten &lt;ID&gt; unort &lt;Ort&gt;\n     /verwalten &lt;ID&gt; einsatz &lt;Ort&gt;\n     /verwalten &lt;ID&gt; uneinsatz &lt;Ort&gt;")
                    continue
                try:
                    target_id = int(parts[1])
                except ValueError:
                    send_to(chat_id, "Ung\u00fcltige Chat-ID.")
                    continue
                target_str = str(target_id)
                if target_str not in users["users"]:
                    send_to(chat_id, f"\u2139\ufe0f Benutzer {target_id} nicht gefunden.")
                    continue
                action = parts[2].lower()
                if action == "ort":
                    if len(parts) < 4:
                        send_to(chat_id, "Usage: /verwalten &lt;ID&gt; ort &lt;Ort&gt;")
                        continue
                    ort = " ".join(parts[3:])
                    tw = users["users"][target_str].get("orte", [])
                    target_uname = users["users"][target_str].get("username", "?")
                    if ort.lower() in [w.lower() for w in tw]:
                        send_to(chat_id, f"\u2139\ufe0f '{esc(ort)}' wird von {esc(target_uname)} bereits beobachtet.")
                        continue
                    tw.append(ort)
                    users["users"][target_str]["orte"] = tw
                    save_users(users)
                    tname = users["users"][target_str].get("username", "?")
                    send_to(chat_id, f"\u2705 Ort '{esc(ort)}' f\u00fcr {esc(tname)} ({target_id}) gesetzt.")
                    if users["users"][target_str].get("registered"):
                        send_to(target_id, f"\U0001f441\ufe0f Der Admin hat '{esc(ort)}' zu deinen Orten hinzugef\u00fcgt.")
                elif action == "unort":
                    if len(parts) < 4:
                        send_to(chat_id, "Usage: /verwalten &lt;ID&gt; unort &lt;Ort&gt;")
                        continue
                    ort = " ".join(parts[3:])
                    if target_id == ADMIN_ID and ort.lower() == FF_NAME.lower():
                        send_to(chat_id, f"\u26d4\ufe0f '{esc(FF_NAME)}' ist die Stammfeuerwehr und kann nicht entfernt werden.")
                        continue
                    tw = users["users"][target_str].get("orte", [])
                    removed = False
                    for i, w in enumerate(tw):
                        if w.lower() == ort.lower():
                            tw.pop(i)
                            removed = True
                            break
                    if removed:
                        users["users"][target_str]["orte"] = tw
                        save_users(users)
                        tname = users["users"][target_str].get("username", "?")
                        send_to(chat_id, f"\u2705 Ort '{esc(ort)}' f\u00fcr {esc(tname)} ({target_id}) entfernt.")
                        if users["users"][target_str].get("registered"):
                            send_to(target_id, f"\U0001f441\ufe0f Der Admin hat '{esc(ort)}' aus deinen Orten entfernt.")
                    else:
                        tname2 = users["users"][target_str].get("username", "?")
                        send_to(chat_id, f"\u2139\ufe0f '{esc(ort)}' war von {esc(tname2)} nicht als Ort beobachtet.")
                elif action == "einsatz":
                    if len(parts) < 4:
                        send_to(chat_id, "Usage: /verwalten &lt;ID&gt; einsatz &lt;Ort&gt;")
                        continue
                    ort = " ".join(parts[3:])
                    tw = users["users"][target_str].get("einsatz_watches", [])
                    target_uname = users["users"][target_str].get("username", "?")
                    if ort.lower() in [w.lower() for w in tw]:
                        send_to(chat_id, f"\u2139\ufe0f '{esc(ort)}' wird von {esc(target_uname)} bereits als Einsatz beobachtet.")
                        continue
                    tw.append(ort)
                    users["users"][target_str]["einsatz_watches"] = tw
                    save_users(users)
                    tname = users["users"][target_str].get("username", "?")
                    send_to(chat_id, f"\u2705 Einsatz-Beobachtung '{esc(ort)}' f\u00fcr {esc(tname)} ({target_id}) gesetzt.")
                    if users["users"][target_str].get("registered"):
                        send_to(target_id, f"\U0001f441\ufe0f Der Admin hat '{esc(ort)}' als tempor\u00e4re Einsatz-Beobachtung hinzugef\u00fcgt.")
                elif action == "uneinsatz":
                    if len(parts) < 4:
                        send_to(chat_id, "Usage: /verwalten &lt;ID&gt; uneinsatz &lt;Ort&gt;")
                        continue
                    ort = " ".join(parts[3:])
                    tw = users["users"][target_str].get("einsatz_watches", [])
                    removed = False
                    for i, w in enumerate(tw):
                        if w.lower() == ort.lower():
                            tw.pop(i)
                            removed = True
                            break
                    if removed:
                        users["users"][target_str]["einsatz_watches"] = tw
                        save_users(users)
                        tname = users["users"][target_str].get("username", "?")
                        send_to(chat_id, f"\u2705 Einsatz-Beobachtung '{esc(ort)}' f\u00fcr {esc(tname)} ({target_id}) entfernt.")
                        if users["users"][target_str].get("registered"):
                            send_to(target_id, f"\U0001f441\ufe0f Der Admin hat Einsatz-Beobachtung '{esc(ort)}' entfernt.")
                    else:
                        tname2 = users["users"][target_str].get("username", "?")
                        send_to(chat_id, f"\u2139\ufe0f '{esc(ort)}' war von {esc(tname2)} nicht als Einsatz beobachtet.")
                else:
                    send_to(chat_id, "Usage: /verwalten &lt;ID&gt; ort &lt;Ort&gt;\n     /verwalten &lt;ID&gt; unort &lt;Ort&gt;\n     /verwalten &lt;ID&gt; einsatz &lt;Ort&gt;\n     /verwalten &lt;ID&gt; uneinsatz &lt;Ort&gt;")

            elif text.startswith("/sperren"):
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                # /sperren                      → Blacklist anzeigen
                # /sperren <ID>                 → ID dauerhaft bannen
                # /sperren <ID> <Stunden>h      → ID zeitweise bannen (z.B. /sperren 123 48h)
                # /freigeben <ID>               → Bann aufheben
                parts = text.split()
                if len(parts) < 2 or parts[1].lower() in ("list", "alle"):
                    bl = load_blacklist()
                    aktive = {}
                    for cid, until in bl.get("ids", {}).items():
                        if until is None:
                            aktive[cid] = None
                            continue
                        try:
                            if datetime.now() < datetime.fromisoformat(until):
                                aktive[cid] = until
                        except Exception:
                            pass
                    if not aktive:
                        send_to(chat_id, "\U0001f512 Blacklist ist leer.")
                        continue
                    zeilen = []
                    for cid, until in sorted(aktive.items()):
                        uname = users["users"].get(cid, {}).get("username") or "?"
                        bis = "dauerhaft" if until is None else str(until)[:16].replace("T", " ")
                        zeilen.append(f"  \U0001f6ab {cid} ({esc(uname)}) \u2014 {bis}")
                    send_to(chat_id, "\U0001f512 <b>Blacklist</b>\n" + "\n".join(zeilen))
                    continue
                try:
                    ban_id = int(parts[1])
                except ValueError:
                    send_to(chat_id, "Ung\u00fcltige Chat-ID.\nUsage: /sperren &lt;ID&gt; [Stunden]")
                    continue
                if ban_id <= 0:
                    send_to(chat_id, "Ung\u00fcltige Chat-ID. Muss positiv sein.")
                    continue
                if ban_id == ADMIN_ID:
                    send_to(chat_id, "\U0001f921 Sich selbst bannen? Netter Versuch.\nMach des ned, Admin.")
                    continue
                ban_id_str = str(ban_id)
                ban_until = None
                if len(parts) >= 3:
                    dauer = parts[2].lower().rstrip("h")
                    try:
                        stunden = float(dauer)
                        if stunden <= 0:
                            raise ValueError
                        ban_until = (datetime.now() + timedelta(hours=stunden)).isoformat()
                    except ValueError:
                        send_to(chat_id, "Ung\u00fcltige Dauer. Format: Stunden + h, z.B. /sperren 123456789 48h")
                        continue
                bl = load_blacklist()
                bl["ids"][ban_id_str] = ban_until
                save_blacklist(bl)
                uname = users["users"].get(ban_id_str, {}).get("username")
                bis = "dauerhaft" if ban_until is None else str(ban_until)[:16].replace("T", " ")
                logger.info(f"Admin-Bann: {ban_id} ({uname or 'unbekannt'}) \u2014 {bis}")
                ban_msg = f"\U0001f6ab <b>ID {ban_id} gebannt</b> \u2014 {bis}\n"
                if uname:
                    ban_msg += f"\U0001f464 Name: {esc(uname)}\n"
                ban_msg += ("Die ID wird ab jetzt komplett ignoriert \u2014 keine Meldungen,\n"
                            "keine Alarme, keine Kontakt-Benachrichtigung.")
                send_to(chat_id, ban_msg)
                # Falls der User eingetragen+registriert ist: einmalig informieren
                if ban_id_str in users["users"] and users["users"][ban_id_str].get("registered"):
                    send_to(ban_id, "\U0001f6ab Du wurdest vom Feuerwehr-Monitor Bot gebannt.\nBefehle und Einsatzmeldungen sind deaktiviert.")
                # users.json bleibt unangetastet — die Blacklist ist die alleinige Quelle.

            elif text.startswith("/freigeben"):
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                parts = text.split()
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /freigeben &lt;ID&gt;")
                    continue
                try:
                    ub_id = int(parts[1])
                except ValueError:
                    send_to(chat_id, "Ung\u00fcltige Chat-ID.")
                    continue
                ub_id_str = str(ub_id)
                bl = load_blacklist()
                if ub_id_str in bl.get("ids", {}):
                    bl["ids"].pop(ub_id_str)
                    save_blacklist(bl)
                    send_to(chat_id, f"\u2705 ID {ub_id} ist von der Blacklist entfernt.")
                    logger.info(f"Admin-Unban: {ub_id}")
                else:
                    send_to(chat_id, f"\u2139\ufe0f ID {ub_id} war nicht auf der Blacklist.")

            elif text.startswith("/rundruf"):
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                parts = text.split(None, 1)
                if len(parts) < 2:
                    send_to(chat_id, "Usage: /rundruf &lt;Text&gt;")
                    continue
                broadcast_text = parts[1][:4000]
                admin_name = users["users"][str(ADMIN_ID)].get("username", "Admin")
                count = 0
                skipped_banned = 0
                bl_ids = load_blacklist().get("ids", {})
                for cid, ud in users["users"].items():
                    if ud.get("registered") and int(cid) != ADMIN_ID:
                        if cid in bl_ids or (lambda bu: bool(bu) and (lambda d: d is not None and datetime.now() < d)(datetime.fromisoformat(bu) if bu else None))(ud.get("ban_until")):
                            skipped_banned += 1
                            continue
                        send_to(int(cid), f"\U0001f4e2 <b>Rundruf von {esc(admin_name)}:</b>\n{esc(broadcast_text)}")
                        count += 1
                note = f" ({skipped_banned} gebannt übersprungen)" if skipped_banned else ""
                send_to(ADMIN_ID, f"\u2705 Rundfunk gesendet an {count} Benutzer.{note}")

            elif text == "/serverstatus":
                if not is_admin:
                    send_to(chat_id, "\u26d4\ufe0f Nur der Admin kann das.")
                    continue
                def _uptime_str():
                    try:
                        fields = open("/proc/self/stat").read().rsplit(")", 1)[1].split()
                        ticks = float(fields[19])
                        btime = 0.0
                        with open("/proc/stat") as f:
                            for line in f:
                                if line.startswith("btime"):
                                    btime = float(line.split()[1])
                                    break
                        secs = max(0, int(time.time() - (btime + ticks / 100.0)))
                        return "%dh %02dm" % (secs // 3600, (secs % 3600) // 60)
                    except Exception:
                        return "?"
                reg_n = sum(1 for u in users["users"].values() if u.get("registered"))
                ges_orte = sum(len(u.get("orte", [])) for u in users["users"].values())
                ges_ew = sum(len(u.get("einsatz_watches", [])) for u in users["users"].values())
                bl_n = len(load_blacklist().get("ids", {}))
                lz_ok = False
                try:
                    lz = fetch_ooelfv(SOURCE_URL)
                    lz_ok = bool(parse_einsaetze_full(lz)) or bool(re.search(r"Einsätze:\s*\d+,\s*Feuerwehren:\s*\d+", lz or ""))
                except Exception:
                    lz_ok = False
                try:
                    import shutil as _shutil
                    frei_gb = _shutil.disk_usage(STATE_DIR).free / (1024 ** 3)
                except Exception:
                    frei_gb = -1
                kb_size = os.path.getsize(USERS_FILE) // 1024 if os.path.exists(USERS_FILE) else 0
                status_q = "✅ OK" if lz_ok else "⚠️ keine auswertbaren Daten"
                msg_st = (
                    "\U0001f5a5\ufe0f <b>Serverstatus — Feuerwehr-Bot</b>\n"
                    f"\u23f1\ufe0f Laufzeit: {_uptime_str()}\n"
                    f"\U0001f465 Benutzer: {len(users['users'])} ({reg_n} registriert)\n"
                    f"\U0001f4cd Beobachtungen: {ges_orte} dauerhaft, {ges_ew} temporär\n"
                    f"\U0001f6ab Blacklist: {bl_n} Einträge\n"
                    f"\U0001f9ed OOELFV-Quelle: {status_q} (Canary-Streak: {_canary_streak})\n"
                    f"\U0001f41d Python {sys.version.split()[0]}\n"
                    + (f"\U0001f4be Frei: {frei_gb:.1f} GB\n" if frei_gb >= 0 else "")
                    + f"\U0001f4c4 users.json: {kb_size} KB\n"
                    f"\U0001f4cc Version: v9 (Inline-Buttons, /warnungen, Ortsvorschläge)"
                )
                send_to(chat_id, msg_st)

            elif text == "/meinedaten":
                ud_md = users["users"][cid_str]
                daten = {
                    "benutzername": ud_md.get("username") or "(nicht gesetzt)",
                    "rolle": "Admin" if is_admin else "Benutzer",
                    "registriert": "ja" if ud_md.get("registered") else "nein",
                    "dabei_seit": (ud_md.get("added_at") or "?")[:10],
                    "dauerhaft_beobachtete_orte": ud_md.get("orte", []),
                    "temporaere_einsatz_beobachtungen": ud_md.get("einsatz_watches", []),
                    "ort_filter": ud_md.get("ort_typen", {}),
                    "stiller_modus": bool(ud_md.get("silent")),
                    "stillfenster": ud_md.get("quiet_hours") or "(keins)",
                    "wochenrueckblick": bool(ud_md.get("wochen") or ud_md.get("week_digest")),
                }
                daten_json = json.dumps(daten, ensure_ascii=False, indent=1)
                msg_md = (
                    "\U0001f4cb <b>Deine gespeicherten Daten (DSGVO-Auskunft)</b>\n\n"
                    "<code>" + esc(daten_json) + "</code>\n\n"
                    "ℹ️ Mehr speichert der Bot nicht. Löschung jederzeit per /vergessen."
                )
                send_to(chat_id, msg_md)

            elif text and text.startswith("/"):
                send_to(chat_id, "Unbekannter Befehl. /hilfe für alle Befehle.")

        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except Exception as e:
        logger.debug(f"Bot command check error: {e}")
        # Offset trotzdem speichern um doppelte Verarbeitung zu vermeiden
        try:
            with open(OFFSET_FILE, "w") as f:
                f.write(str(offset))
        except Exception:
            pass

# ═══ Onboarding: Anleitung + Datenschutz einmalig pro ID ═══
def send_onboarding_if_needed():
    """Nach der Registrierung bekommen neue Nutzer einmalig automatisch die
    Anleitung + die Datenschutz-Info (einmal pro ID, Feld intro_sent in
    users.json). /anleitung und /datenschutz bleiben jederzeit verfügbar."""
    changed = False
    for cid_str, ud in list(users["users"].items()):
        if not ud.get("registered") or ud.get("intro_sent"):
            continue
        if cid_str == str(ADMIN_ID):
            continue  # Admin kennt die Texte — kein Auto-Versand
        if blocked_reason(cid_str):
            continue
        try:
            ok = send_to(int(cid_str), (
                "\U0001f4da <b>Wissenswertes für den Start</b>\n\n"
                "Du erhältst jetzt automatisch die Anleitung und die "
                "Datenschutz-Information. Beides kannst du jederzeit "
                "selbst wieder ansehen: /anleitung und /datenschutz."))
            ok = send_to(int(cid_str), anleitung_text()) and ok
            ok = send_to(int(cid_str), datenschutz_text()) and ok
            if not ok:
                # Versand unvollstaendig -> im naechsten Zyklus erneut versuchen
                logger.warning(f"Onboarding unvollständig (ID {cid_str}) — Retry im nächsten Zyklus")
                continue
            ud["intro_sent"] = True
            logger.info(f"Onboarding gesendet (einmalig, Anleitung+Datenschutz): {cid_str}")
            changed = True
        except Exception as e:
            logger.error(f"Onboarding-Fehler (ID {cid_str}): {e}")
    if changed:
        save_users(users)

# ═══ Main Loop ═══
def main():
    reg_count = sum(1 for u in users["users"].values() if u.get("registered"))
    logger.info(f"Einsatzmonitor-Watcher v9 gestartet — Multi-User System (Buttons, Warnungen, Vorschläge)")
    logger.info(f"Poll-Intervall: {POLL_INTERVAL} Sekunden")
    logger.info(f"Benutzer: {len(users['users'])} ({reg_count} registriert)")
    if BOT_TOKEN:
        logger.info(f"Telegram Bot aktiv — Admin-ID: {ADMIN_ID}")
        setup_telegram_commands()
    else:
        logger.warning("Telegram Bot NICHT aktiv — Token fehlt")
    if ADMIN_ID:
        send_to(ADMIN_ID, "\U0001f6f0\ufe0f Feuerwehr-Monitor Bot online")

    first_cycle = True
    while True:
        try:
            _tag_cache[0] = None
            handle_bot_commands()
            # Lösch-Wächter: Admin-Info, wenn ein User aus users.json verschwindet
            check_user_removals()
            # Zwei-Stufen-Löschung: letzte Nachfrage nach 2 Wochen + Auto-Abbruch bei Nichtreaktion
            check_loesch_nachfragen()
            # Onboarding: neue Nutzer bekommen Anleitung + Datenschutz einmalig pro ID
            send_onboarding_if_needed()
            # Unwetter-Bewachung: beobachtete Orte auf aktive Warnungen prüfen (interner 10-Min-Takt)
            try:
                check_unwetter_for_users(load_users())
            except Exception as unw_err:
                logger.debug(f"Unwetter-Check Fehler: {unw_err}")
            # Pegel-Wache: Hochwasser-/Alarmstufen rund um beobachtete Orte (15-Minuten-Takt)
            try:
                check_pegel_for_users(load_users())
            except Exception as pegel_err:
                logger.debug(f"Pegel-Check Fehler: {pegel_err}")
            # Strom-Wache: Netz-OÖ-Störungen in den Bezirken beobachteter Orte (15-Minuten-Takt)
            try:
                check_strom_for_users(load_users())
            except Exception as strom_err:
                logger.debug(f"Strom-Check Fehler: {strom_err}")
            # Waldbrand-Wache: Gefährdung aus GeoSphere-Wetter an den Orten (3-Stunden-Takt)
            try:
                check_waldbrand_for_users(load_users())
            except Exception as wb_err:
                logger.debug(f"Waldbrand-Check Fehler: {wb_err}")
            # Lawinen-Wache: OÖ-Lawinenlage ab Stufe 3 (6-Stunden-Takt, 1 Meldung je Berichtstag)
            try:
                check_lawinen_for_users(load_users())
            except Exception as lw_w_err:
                logger.debug(f"Lawinen-Check Fehler: {lw_w_err}")
            # Sirenen-Erinnerung: Abend vor dem Zivilschutz-Probealarm (1x/Jahr, pure Datumsmathematik)
            try:
                check_sirenen_for_users(load_users())
            except Exception as sir_w_err:
                logger.debug(f"Sirenen-Check Fehler: {sir_w_err}")
            # Wochenrückblick: sonntags 20:00 für User mit /wochen aktiv
            send_week_digests()
            html = fetch_ooelfv(SOURCE_URL)
            einsaetze_all = parse_einsaetze_full(html)
            try:
                _parser_canary(html, einsaetze_all)
            except Exception:
                pass

            # Per-User Checks
            admin_offenhausen_active = False
            for cid_str, ud in list(users["users"].items()):
                if not ud.get("registered"):
                    continue
                # Gebannte IDs: KEINE Watch-Checks (keine Alarme/Updates/Abschlussberichte)
                if blocked_reason(cid_str):
                    continue
                cid = int(cid_str)
                check_user_watches(cid, ud, einsaetze_all, suppress=first_cycle)
                # InkyPi: Admin Stamm-FF aktiv?
                if cid == ADMIN_ID and FF_NAME in ud.get("orte", []):
                    for e in einsaetze_all:
                        if einsatz_matches_watch(e, FF_NAME):
                            admin_offenhausen_active = True
                            break

            if admin_offenhausen_active:
                trigger_inkypi_feuerwehr()

            first_cycle = False
        except Exception as e:
            logger.error(f"Main loop error: {e}")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()