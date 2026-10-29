# px.market canlı satış botu · kurulum

Bot, px.market'teki yeni satışları her 20 saniyede bir kontrol eder ve Telegram kanalına
@PixelMarketLIVE tarzında "ITEM SOLD" mesajı olarak (resim, ad #numara, satış fiyatı) gönderir.

## 1. Telegram tarafı
1. Telegram'da **@BotFather** → `/newbot` → bir ad ver → sana bir **token** verir. Bu token'ı kimseyle paylaşma, sohbete de yapıştırma.
2. Kanalını aç (ya da var olanı kullan), botu kanala **yönetici** olarak ekle ("Mesaj gönder" izni yeterli).
3. Kanal herkese açıksa `CHANNEL_ID` = `@kanal_adin`. Gizliyse `-100...` ile başlayan sayısal id.

## 2. Önce bilgisayarında dene (isteğe bağlı)
Python 3.9+ yeterli, kurulacak paket yok.
```
DRY_RUN=1 DEBUG=1 POST_OLD=1 python bot.py
```
Telegram'a bir şey göndermez; akıştan gelen ilk kaydı ve oluşacak mesajları ekrana yazar.
Ekrandaki `[debug] ilk kayıt` kısmını bana gönderirsen alan adlarını birebir ayarlarım.

## 3. Sunucuda çalıştır
Bot sürekli açık kalmalı, bu yüzden bir sunucuya koy:

**Railway (en kolayı):** New Project → Deploy from GitHub (bu klasörü bir repoya koy) ya da "Empty project" + dosyaları yükle.
Variables kısmına ekle:
- `BOT_TOKEN` = BotFather'ın verdiği token
- `CHANNEL_ID` = `@kanal_adin`
- `APP_ID` (isteğe bağlı): varsayılan `16,2,7` = Pixel World + VOID + Glance. Boş bırakırsan (`APP_ID=`) tüm oyunlar

Start command: `python bot.py`

**Render:** "Background Worker" seç, aynı değişkenler, start command `python bot.py`.

**VPS:** `BOT_TOKEN=... CHANNEL_ID=@... APP_ID=16 nohup python3 bot.py &`

## Ayarlar
| Değişken | Ne işe yarar | Varsayılan |
|---|---|---|
| `POLL_SECONDS` | kaç saniyede bir kontrol | 20 |
| `MIN_PRICE_TON` | bu fiyatın altındaki satışları gösterme | 0 |
| `APP_ID` | sadece bu oyun (16 = Pixel World) | 16,2,7 |
| `POST_OLD` | 1 ise açılışta eski satışları da atar | kapalı |

## Not
px.market'in robots.txt dosyası botların `/api` yollarına girmesini istemiyor. Kontrol aralığını
çok kısaltma (20 sn iyi), kanal büyürse Not Games / px.market ekibinden izin ya da resmi API istemek en temizi.
