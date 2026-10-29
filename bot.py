#!/usr/bin/env python3
"""px.market canlı satış botu.

px.market'in herkese açık satış akışını (/api/v2/feed/latest) belirli aralıklarla
okur, yeni satışları Telegram kanalına @PixelMarketLIVE tarzında gönderir:

    🔄 GAME ITEM SOLD
    Illuminati #173
    💰 Pixel Market Price
    0.28 TON

Sadece Python 3.9+ standart kütüphanesi kullanır, pip kurulumu gerekmez.

Ortam değişkenleri (token'ı ASLA koda yazma):
    BOT_TOKEN      BotFather'dan alınan token            (zorunlu)
    CHANNEL_ID     @kanal_adi veya -100... sayısal id     (zorunlu)
    POLL_SECONDS   kaç saniyede bir kontrol (varsayılan 20)
    FEED_LIMIT     her seferde kaç satış çekilir (varsayılan 20)
    APP_ID         hangi oyunların satışları, virgülle: varsayılan "16,2" = Pixel World + VOID (boş = hepsi)
    MIN_PRICE_TON  bu fiyatın altındaki satışları atla (varsayılan 0)
    STATE_FILE     görülen satışların tutulduğu dosya (varsayılan state.json)
    POST_OLD       1 ise ilk açılışta akıştaki eski satışları da gönderir
    DRY_RUN        1 ise Telegram'a göndermez, sadece ekrana yazar
    DEBUG          1 ise akıştan gelen ilk kaydı ham haliyle ekrana basar
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import escape

API = "https://px.market/api/v2"
FEED_URL = API + "/feed/latest?limit={limit}"
SITE = "https://px.market"
NANO = 1_000_000_000

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1004408043162")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "20"))
FEED_LIMIT = int(os.environ.get("FEED_LIMIT", "20"))
APP_IDS = {a.strip() for a in os.environ.get("APP_ID", "16,2").split(",") if a.strip()}  # boş = tüm oyunlar
# Forum grubunda her oyunun gittiği konu (topic): oyun no -> konu no.
# Konu no = konunun linkindeki son sayı (t.me/c/4408043162/<konu no>). Listede yoksa General'e gider.
TOPICS = {"16": "5", "2": "8"}  # Pixel world LIVE, VOID LIVE
for _pair in os.environ.get("TOPICS", "").split(","):  # örn. TOPICS=16:3,2:5
    if ":" in _pair:
        _app, _topic = _pair.split(":", 1)
        TOPICS[_app.strip()] = _topic.strip()
# px.market oyun numaraları -> mesajda görünen ad
GAMES = {
    "2": "VOID", "3": "Not Pixel", "4": "Notcoin", "5": "Disk Trickster", "6": "Lost Dogs",
    "7": "Glance", "8": "Runners", "9": "Hitoku", "11": "TON Battleground", "13": "KokoronoKI",
    "15": "TON Poker", "16": "Pixel World",
}
MIN_PRICE_TON = float(os.environ.get("MIN_PRICE_TON", "0"))
ITEM_URL = os.environ.get("ITEM_URL", SITE)  # {id} = productId içindeki sayı, örn. https://px.market/item/{id}
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
POST_OLD = os.environ.get("POST_OLD") == "1"
DRY_RUN = os.environ.get("DRY_RUN") == "1"
DEBUG = os.environ.get("DEBUG") == "1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (px-satis-botu)",
    "Accept": "application/json",
}


# --- Akıştaki alan adları -------------------------------------------------
# Gerçek cevap (2026-10-29): {"ok":true,"data":{"items":[{"id","eventType":"price_change",
# "productId":"gameItem_86991","productName","productImage","productNumber","price"(TON),
# "oldPrice","category","appId":16,"collection","timestamp"}]}}. Listeler sırayla denenir.
# Noktalı yol iç içe alanları okur: "item.name" -> kayit["item"]["name"].
FIELDS = {
    "id": ["id", "uuid", "eventId", "txHash", "hash"],
    "type": ["eventType", "type", "action", "kind"],
    "price": ["price", "amount", "priceNano", "salePrice", "item.price", "nft.price"],
    "name": ["productName", "item.name", "nft.name", "gameItem.name", "name", "title", "item.title", "model"],
    "serial": ["productNumber", "item.number", "item.serial", "nft.number", "number", "serial", "index", "item.index"],
    "image": ["productImage", "item.image", "item.imageUrl", "nft.image", "gameItem.image", "image", "imageUrl", "img", "photo"],
    "item_id": ["productId", "item.id", "itemId", "nft.id", "gameItem.id", "item.uuid", "itemUuid", "nftAddress", "address"],
    "app_id": ["appId", "item.appId", "gameId", "game.id", "item.gameId"],
    "collection": ["item.collection", "collection", "collectionName", "item.collectionName", "collection.name"],
    "link": ["url", "link", "item.url"],
}

# Akıştaki olay tipleri: "purchase" = satış, "price_change" = fiyat değişti, "list" = satışa kondu.
# Sadece satışlar gönderilir.
SALE_TYPES = {"purchase"}
TYPES_SEEN = set()


def pick(obj, key):
    for path in FIELDS[key]:
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, ""):
            # {"name": "Doge"} gibi nesne geldiyse içindeki adı al
            if isinstance(cur, dict):
                cur = cur.get("name") or cur.get("title") or cur.get("id")
            return cur
    return None


def to_ton(value):
    """Nano birimi (TON*1e9) ya da düz TON değerini TON'a çevirir."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("amount") or value.get("value") or value.get("ton")
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    # 1 milyondan büyükse nano kabul et (1e6 TON'luk satış olmayacağı varsayımı)
    return v / NANO if v >= 1_000_000 else v


def fmt_ton(v):
    if float(v).is_integer():
        return str(int(v))
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".00"
    elif len(s.split(".")[1]) == 1:
        s += "0"
    return s


# --- HTTP ------------------------------------------------------------------
def http_json(url, data=None):
    body = None
    headers = dict(HEADERS)
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_feed():
    data = http_json(FEED_URL.format(limit=FEED_LIMIT))
    if isinstance(data, dict):
        for k in ("items", "data", "feed", "events", "results", "list"):
            if isinstance(data.get(k), list):
                return data[k]
            if isinstance(data.get(k), dict):
                for k2 in ("items", "list", "events"):
                    if isinstance(data[k].get(k2), list):
                        return data[k][k2]
        return []
    return data if isinstance(data, list) else []


def tg(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        return http_json(url, payload)
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors="replace")
        print(f"[telegram] {method} hata {e.code}: {err}", flush=True)
        if e.code == 429:  # çok hızlı gönderim, Telegram'ın dediği kadar bekle
            try:
                wait = json.loads(err)["parameters"]["retry_after"]
            except Exception:
                wait = 5
            time.sleep(wait + 1)
            return tg(method, payload)
        return None


# --- Durum (görülen satışlar + son fiyatlar) -------------------------------
def load_state():
    try:
        with open(STATE_FILE) as f:
            d = json.load(f)
            return {"seen": d.get("seen", []), "day": d.get("day", {})}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen": [], "day": {}}


def save_state(state):
    state["seen"] = state["seen"][-2000:]
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


# --- Mesaj -----------------------------------------------------------------
def event_key(ev):
    eid = pick(ev, "id")
    if eid is not None:
        return str(eid)
    # id yoksa içerikten anahtar üret
    return json.dumps(ev, sort_keys=True)[:300]


def is_sale(ev):
    return str(pick(ev, "type")).lower() in SALE_TYPES


def item_link(ev):
    pid = str(pick(ev, "item_id") or "")
    num = pid.rsplit("_", 1)[-1]
    return ITEM_URL.replace("{id}", num).replace("{productId}", pid)


# Oyuna göre başlık rengi
GAME_ICONS = {"2": "🟣", "16": "🟦"}
_usd = {"rate": None, "at": 0}


def ton_usd():
    """TON/USD kuru, 5 dakikada bir yenilenir. Alınamazsa None."""
    if time.time() - _usd["at"] > 300:
        _usd["at"] = time.time()
        try:
            d = http_json("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd")
            _usd["rate"] = float(d["the-open-network"]["usd"])
        except Exception:
            pass
    return _usd["rate"]


def hashtag(text):
    tag = "".join(ch for ch in str(text) if ch.isalnum())
    return "#" + tag if tag else ""


def build_message(ev):
    app = str(pick(ev, "app_id"))
    name = str(pick(ev, "name") or "Item")
    serial = pick(ev, "serial")
    collection = pick(ev, "collection")
    price = to_ton(pick(ev, "price"))
    game = GAMES.get(app, "Not Games")

    lines = [f"{GAME_ICONS.get(app, '🎮')} <b>{escape(game.upper())}</b>  ·  SOLD", ""]
    title = f"<b>{escape(name)}</b>" + (f"  <code>#{escape(str(serial))}</code>" if serial is not None else "")
    lines.append(title)
    if collection and str(collection).lower() != name.lower():
        lines.append(f"🗂 <i>{escape(str(collection))}</i>")
    lines.append("━━━━━━━━━━━━")

    price_line = f"💎 <b>{fmt_ton(price)} TON</b>"
    rate = ton_usd()
    if rate:
        price_line += f"  <i>≈ ${price * rate:,.2f}</i>"
    lines.append(price_line)
    if price >= 100:
        lines.append("🐳 <b>Whale sale!</b>")
    elif price >= 10:
        lines.append("🔥 <b>Big sale!</b>")

    tags = " ".join(t for t in (hashtag(game), hashtag(collection or name)) if t)
    lines += ["", tags]
    return "\n".join(lines)


def post(ev, text):
    image = pick(ev, "image")
    target = {"chat_id": CHANNEL_ID}
    topic = TOPICS.get(str(pick(ev, "app_id")))
    if topic:
        target["message_thread_id"] = int(topic)
    if DRY_RUN:
        print("-" * 40)
        print(f"[hedef] {target}  [resim] {image}")
        print(text, flush=True)
        return True
    if image:
        # bazı eşyaların görseli .mp4 animasyon
        method, field = ("sendAnimation", "animation") if str(image).lower().endswith(".mp4") else ("sendPhoto", "photo")
        r = tg(method, {
            **target, field: image, "caption": text,
            "parse_mode": "HTML",
        })
        if r and r.get("ok"):
            return True
    # resim yoksa ya da Telegram resmi alamadıysa düz mesaj
    r = tg("sendMessage", {
        **target, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    return bool(r and r.get("ok"))


# --- Ana döngü -------------------------------------------------------------
def process(events, state, first_run):
    seen = set(state["seen"])
    # akış genelde yeniden eskiye gelir; eskiden yeniye işle
    for ev in reversed(events):
        if not isinstance(ev, dict):
            continue
        key = event_key(ev)
        if key in seen:
            continue
        seen.add(key)
        state["seen"].append(key)

        if APP_IDS and str(pick(ev, "app_id") or "") not in APP_IDS:
            continue
        t = str(pick(ev, "type"))
        if t not in TYPES_SEEN:
            TYPES_SEEN.add(t)
            print(f"[akış] yeni olay tipi: {t} -> {'satış, gönderilir' if is_sale(ev) else 'atlanır'}", flush=True)
        if not is_sale(ev):
            continue
        now = to_ton(pick(ev, "price"))
        if now is None:
            continue

        if now < MIN_PRICE_TON:
            continue
        if first_run and not POST_OLD:
            continue
        if post(ev, build_message(ev)):
            time.sleep(1.5)  # kanal başına Telegram limiti ~20 mesaj/dk


def main():
    if not DRY_RUN and (not BOT_TOKEN or not CHANNEL_ID):
        sys.exit("BOT_TOKEN ve CHANNEL_ID ortam değişkenlerini ayarla (ya da DRY_RUN=1 ile dene).")
    state = load_state()
    first_run = not state["seen"]
    print(f"Bot başladı. {POLL_SECONDS} sn'de bir {FEED_URL.format(limit=FEED_LIMIT)} okunuyor.", flush=True)
    debug_done = False
    while True:
        try:
            events = fetch_feed()
            if DEBUG and not debug_done and events:
                print("[debug] ilk kayıt:\n" + json.dumps(events[0], indent=2, ensure_ascii=False), flush=True)
                debug_done = True
            process(events, state, first_run)
            first_run = False
            save_state(state)
        except urllib.error.HTTPError as e:
            print(f"[px.market] HTTP {e.code}", flush=True)
        except Exception as e:  # ağ kopması vb. botu düşürmesin
            print(f"[hata] {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
