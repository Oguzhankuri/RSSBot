# 📰 Günlük Bülten Stüdyosu (v2)

**Tek tıkla** günlük haber içeriği: RSS gündemi + senin fikirlerin + kanalın geçmiş performansı harmanlanır,
**yatay (16:9) bülten** ve **dikey (9:16) Shorts** için ayrı formüllerle senaryo, çeviri, görsel ve klon ses üretilir,
grafikçilerin montajlayacağı düzenli bir paket çıkar. Sistem yayınlanan videoların performansından **kendi kurallarını öğrenir**.

```
 Telefon ──Telegram──┐                 ┌── Colab (GPU): görseller + klon sesler
                     ▼                 │
             Veritabanı (Supabase) ◄───┤
                     ▲                 │
 PC: BASLAT.bat → Panel ┘              └── Google Drive: output/ (PC + Colab + grafikçiler)
```

## 🚀 Günlük kullanım

1. **`BASLAT.bat`**'a çift tıkla → tarayıcıda panel açılır → **▶️ Bugünü Başlat**.
2. Panel ne zaman ne yapacağını söyler:
   - **"🚀 Sıra Colab'da — git orayı hallet!"** → *Colab'ı aç* butonu → tek hücreyi ▶ çalıştır.
   - **"🎙️ Sıra sende: TR ses kaydı"** → panelde senaryoları oku, `tr.wav` kayıtlarını panele bırak.
   - **"Yayın + YouTube linkleri"** → videolar yayınlanınca linkleri *İçerikler* sayfasına yapıştır.
3. Grafikçiler `output/<tarih>/TESLIM.md` ve her klasördeki `MONTAJ_NOTU.md` ile çalışır.

| Adım | Nerede | Ne olur |
|---|---|---|
| 1. Planla (Beyin) | PC | Gündem + fikir kutusu + hafıza → yatay ve dikey için konu seçimi |
| 2. Senaryolar | PC | Formata özel senaryolar + 4 dile çeviri (DeepSeek) |
| 3. Görseller | Colab (ya da `fal` ile PC) | Yatay 1280×720 ×3, dikey 720×1280 ×5 |
| 4. Klon sesler | Colab | 4 dilde senin sesinle (Chatterbox) |
| 5. TR ses kaydı | Sen | Panelden yükle ya da `ses/tr.wav` olarak kaydet |
| 6. Grafikçi paketi | PC | `MONTAJ_NOTU.md` (sahne akışı, süreler, ekran yazıları) + `TESLIM.md` |
| 7. Yayın | Sen | YouTube linkleri → metrikler → beyin öğrenir |

### Çıktı yapısı

```
output/2026-10-09/
├── TESLIM.md                      # grafikçiler için günün özeti + eksik dosya uyarıları
├── yatay/01-<slug>/  senaryo_tr.md, MONTAJ_NOTU.md, metadata.json, ceviriler/, gorseller/, ses/
└── dikey/01-<slug>/  + ekran_yazilari.json (zamanlı ekran yazıları), kanca, CTA, müzik önerisi
```

## 💡 Fikir Kutusu

- **Panelden:** *Fikir Kutusu* sayfası.
- **Telefondan:** Telegram botuna ne yazarsan fikir olarak kaydedilir. Başına `!` koyarsan acil (öncelik 5).
  Komutlar: `/liste`, `/oncelik <kod> <1-5>`, `/sil <kod>` (arşivler, silmez).
- PC kapalıyken bile GitHub Actions 15 dakikada bir mesajları veritabanına aktarır. Fikir **önce kaydedilir**, AI etiketleme sonra gelir; hiçbir fikir kaybolmaz.
- Planlayıcı her gün açık fikirleri gündemle harmanlar (özellikle dikey Shorts için); kullanılan fikir "kullanıldı" olur.

## 🧠 Beyin (kendi kendine öğrenme)

Model fine-tune **edilmez**; şeffaf bir hafıza + geri bildirim döngüsü vardır:

1. **Hafıza:** son 30 günde işlenen konular tekrar seçilmez; en iyi giden içerikler örnek olarak prompt'a eklenir.
2. **Ölçüm:** YouTube Analytics'ten izlenme, izlenme yüzdesi, beğeni… + senin 1–5 yıldız puanların.
3. **Öğren:** *Beyin* sayfasında **🧠 Öğren** → DeepSeek performans verisinden kurallar çıkarır
   (ör. "Dikeyde kancayı soru cümlesiyle kur"). Kurallar her yeni senaryo prompt'una eklenir.
4. Kuralları onaylayabilir, kapatabilir ya da kendin yazabilirsin. Onaylı kurallar asla otomatik silinmez.

## ✍️ Formüller

`bulten/formats/yatay.yaml` ve `dikey.yaml` (panel → *Ayarlar*'dan da düzenlenir): prompt şablonları, haber sayısı,
görsel boyutu/adedi, kelime hedefi. `config.yaml → formats.overrides` ile tek tek alan ezilebilir.

---

## 🔧 Bir kerelik kurulum

### 1) `.env` (proje kökünde, git'e girmez)

```
DEEPSEEK_API_KEY=sk-...            # zorunlu
FAL_KEY=...                        # sadece images.provider=fal ise
HF_TOKEN=hf_...                    # yerel FLUX için: model sayfasında lisansı onayla + Read token
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=...           # Supabase → Project Settings → API → service_role (GİZLİ tut!)
TELEGRAM_BOT_TOKEN=...             # @BotFather → /newbot
TELEGRAM_ALLOWED_USER_ID=...       # @userinfobot'a yaz, verdiği sayı. Bot sadece sana cevap verir.
```

### 2) Supabase (ücretsiz) — PC, Colab ve Telegram aynı veriyi görsün
1. [supabase.com](https://supabase.com) → yeni proje.
2. **SQL Editor** → `db/migrations/001_init.sql` içeriğini yapıştır → **Run**.
3. `config.yaml → db.provider: "supabase"` yap.

> Supabase kurmadan da çalışır (`provider: "sqlite"`), ama o zaman Telegram ve Colab veritabanını göremez.

### 2b) …ya da kendi veritabanın (Docker, self-hosted) 🐳
Supabase hesabı gerekmez; aynı API (Postgres + PostgREST + Caddy) bilgisayarında ya da sunucunda çalışır:

```bash
python docker/setup_db.py                              # şifreleri üretir, .env + config.yaml'ı ayarlar (ekrana sır yazmaz)
docker compose -f docker/docker-compose.yml up -d      # veritabanını başlatır (yalnızca 127.0.0.1:8000)
```

- **Colab için:** panel → ⚙️ Ayarlar → **▶️ Tüneli aç**. Çıkan `https://…trycloudflare.com` adresini Colab Secrets'a
  `SUPABASE_URL` olarak, aynı sayfadaki anahtarı `SUPABASE_SERVICE_KEY` olarak yapıştır. Tünel adresi her açılışta değişir.
- **Telegram:** veritabanı bilgisayardayken GitHub Actions ulaşamaz; panel açıkken fikirler 2 dakikada bir çekilir.
  Telegram okunmamış mesajları 24 saat saklar.
- **Sunucuya taşıma:** `docker/` klasörünü + `docker/.env`'i kopyala, `Caddyfile`'da `:80` yerine alan adını yaz
  (Caddy HTTPS'i kendisi alır), `.env`'de `SUPABASE_URL=https://alan-adin` yap. Tünele ve PC'nin açık kalmasına gerek kalmaz;
  GitHub Actions Telegram senkronu da tekrar çalışır.
- Yedek: `docker compose -f docker/docker-compose.yml exec db pg_dump -U postgres postgres > yedek.sql`

### 3) Google Drive
PC'ye **Google Drive for Desktop** kur ve `config.yaml → output.base_dir` değerini Drive'daki
`gunluk-bulten/output` klasörüne yönlendir (ör. `"G:/My Drive/gunluk-bulten/output"`).
Colab aynı klasöre yazar; grafikçilerle bu klasörü paylaş.
Referans sesini `MyDrive/gunluk-bulten/refs/ref_voice.wav` olarak koy (10–20 sn temiz konuşma).

### 4) Colab
Notebook'u aç (panelde *Colab'ı aç*), **Runtime → T4 GPU**, soldaki 🔑 **Secrets**'a
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `HF_TOKEN` (+ gerekiyorsa `FAL_KEY`) ekle ve *Notebook access*'i aç.

### 5) Telegram 7/24 senkronu (GitHub Actions)
GitHub repo → *Settings → Secrets and variables → Actions*: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` (+ opsiyonel `DEEPSEEK_API_KEY`).
`.github/workflows/telegram_sync.yml` 15 dakikada bir çalışır.

### 6) YouTube ölçümü (opsiyonel, öğrenme için)
1. Google Cloud Console → yeni proje → **YouTube Data API v3** ve **YouTube Analytics API**'yi etkinleştir.
2. *OAuth consent screen* (External, kendini test kullanıcısı ekle) → *Credentials → OAuth client ID → Desktop app* → JSON'u indir.
3. Dosyayı `secrets/client_secret.json` olarak kaydet → `python -m bulten.youtube auth` (bir kez, tarayıcıda onay).
4. Panel → *Beyin* → **📊 YouTube metriklerini çek**.

### 🔒 Bu repo public — dikkat
- Anahtarlar **yalnızca** `.env` (gitignore'da), Colab Secrets ve GitHub Secrets'ta durur. Asla `config.yaml`'a ya da koda yazma.
- GitHub Actions logları herkese açıktır; kod CI'da hata ayrıntısı (URL, satır verisi) ve yabancı kullanıcı kimliği yazmaz.
- Fikirlerin, içeriklerin, öğrenilmiş kurallar ve metrikler repoda değil, **Supabase'te** (RLS açık) durur. Formül YAML'ları ise repoda, yani herkes görebilir.
- Colab kodu `main`'den çeker: GitHub hesabında **2FA** açık olsun, `main`'e sadece sen push et.
- GitHub, 60 gün commit olmayan public repolarda zamanlanmış workflow'ları durdurur; durursa *Actions* sekmesinden tekrar etkinleştir.
- Bir anahtar yanlışlıkla commit'lenirse silmek yetmez (geçmişte kalır): anahtarı hemen **iptal edip yenile**.

### Komut satırı (panel olmadan)

```bash
python -m bulten.pipeline advance        # PC adımlarını çalıştır
python -m bulten.pipeline status         # sıra kimde?
python -m bulten.pipeline gpu --only images --date latest   # Colab'da
python -m bulten.telegram_sync           # Telegram'ı elle çek
python -m bulten.youtube sync            # metrikleri çek
```

Eski iki fazlı akış (`run_text.py`, `run_voice.py`) hâlâ çalışır.

---

# v1 dokümantasyonu (referans)


Bir haber sitesinin RSS'inden günde **8 haber** çekip her biri için:

- akıcı bir **Türkçe YouTube bülten senaryosu** (DeepSeek),
- senaryonun **4 yabancı dile** çevirisi (DeepSeek),
- **3 adet telifsiz AI görsel** (FLUX.1-schnell),
- 4 dilde **senin klon sesinle seslendirme** (Chatterbox Multilingual)

üretir ve hepsini tarih/haber bazlı klasörlere düzenler. Çıktı video değildir; montajı sen yaparsın.

---

## Teknoloji ve lisanslar

| Katman | Araç | Lisans | Nerede |
|---|---|---|---|
| Senaryo + çeviri | DeepSeek API (`deepseek-chat`) | — | API (GPU yok), ~$1–2/ay |
| Görsel | FLUX.1-schnell (`diffusers`) | Apache-2.0 ✅ ticari | Colab/GPU |
| Görsel (yedek) | fal.ai `fal-ai/flux/schnell` | — | API, ~$2–11/ay |
| TR ses | Senin kaydın | — | Manuel |
| 4 dil ses | Chatterbox Multilingual (`chatterbox-tts`) | MIT ✅ ticari | Colab/GPU |

XTTS-v2 ve F5-TTS-Turkish **CC-BY-NC (ticari yasak)** olduğu için kullanılmadı.

---

## Kurulum

### A) Google Colab (önerilen)

1. `gunluk_bulten_colab.ipynb` dosyasını Colab'da aç (GitHub'dan: *File → Open notebook → GitHub*).
2. **Runtime → Change runtime type → T4 GPU** seç. (**TPU değil!**)
3. Hücreleri sırayla çalıştır. Notebook repo'yu klonlar, bağımlılıkları kurar, `.env`'i oluşturur.

### B) Yerel bilgisayar

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # sonra DEEPSEEK_API_KEY değerini yaz
```

GPU adımları için (en az ~16 GB VRAM'li NVIDIA kart önerilir):

```bash
pip install -r requirements-gpu.txt     # FAZ A — Flux
python run_text.py
pip install -r requirements-voice.txt   # FAZ B — Chatterbox (FAZ A'dan SONRA)
python run_voice.py
```

> ⚠️ **Kurulum sırası önemli:** `chatterbox-tts` kendi `diffusers==0.29.0` ve `torch==2.6.0` sürümlerini sabitler; FLUX ise `diffusers>=0.30` ister. Bu yüzden ikisi ayrı dosyada ve sırayla kurulur. İkisini sürekli aynı makinede kullanacaksan iki ayrı sanal ortam (`.venv-flux`, `.venv-voice`) aç.

GPU'n yoksa `config.yaml` içinde `images.provider: "fal"` yap ve `.env`'e `FAL_KEY` ekle — FAZ A tamamen GPU'suz çalışır.

---

## Ayarlar

### `.env`

```
DEEPSEEK_API_KEY=sk-...     # zorunlu
FAL_KEY=...                 # sadece images.provider=fal ise
```

### `config.yaml` — sadece şunları doldur

```yaml
feeds:
  - "https://senin-siten.com/rss"

translate:
  languages: ["en", "de", "ar", "ru"]

voice:
  languages: ["en", "de", "ar", "ru"]   # translate.languages ile AYNI olmalı
```

Dilleri değiştirirsen **iki listeyi de** güncelle; farklıysa program açık bir hatayla durur. Desteklenen kodlar: `ar da de el en es fi fr he hi it ja ko ms nl no pl pt ru sv sw zh`.

Diğer ayarlar (haber sayısı, senaryo uzunluğu, görsel boyutu, ses parametreleri) `config.yaml` içinde açıklamalı olarak durur.

---

## Kullanım (3 adım)

1. **FAZ A — tam otomatik**
   ```bash
   python run_text.py            # isteğe bağlı: --date 2026-10-08
   ```
2. **Manuel — Türkçe ses**
   - Her haberin `senaryo_tr.md` dosyasını kendi sesinle oku, `ses/tr.wav` olarak kaydet.
   - Bir kez: 10–20 sn'lik, gürültüsüz, tek kişilik konuşmanı `refs/ref_voice.wav` olarak koy.
3. **FAZ B — 4 dil klon ses**
   ```bash
   python run_voice.py           # --date 2026-10-08   --overwrite (yeniden üret)
   ```

Daha önce işlenen haberler `state/seen.json` içinde tutulur; ertesi gün tekrar işlenmez. Sıfırdan başlamak için bu dosyayı sil. Senaryosu, çevirisi ya da görseli hiç üretilemeyen haberler "görüldü" sayılmaz, bir sonraki çalıştırmada tekrar denenir. Aynı gün ikinci kez çalıştırırsan numaralandırma kaldığı yerden sürer (`09-…`); mevcut klasörler ve içindeki ses kayıtların silinmez.

---

## Çıktı yapısı

```
output/2026-10-08/
├── bulten.md                 # günün index'i (başlık + özet + linkler)
├── manifest.json             # makine-okunur özet
├── 01-<slug>/
│   ├── senaryo_tr.md         # okuyacağın Türkçe metin
│   ├── metadata.json         # kaynak, etiketler, görsel promptları, hatalar
│   ├── ceviriler/{en,de,ar,ru}.md
│   ├── gorseller/01.png 02.png 03.png prompts.txt
│   └── ses/OKU_BENI.txt  (+ senin tr.wav'ın, + FAZ B'nin en/de/ar/ru.wav'ları)
└── ... 08-<slug>/
```

Bir haberde çeviri/görsel hatası olursa diğerleri devam eder; hata o haberin `metadata.json → hatalar` alanına ve `manifest.json`'a yazılır.

---

## Telif / YouTube notu

AI ile üretilen **orijinal** görsel ve ses Content ID'ye takılmaz. Görsel promptlarına şu kural gömülüdür: **gerçek/tanınabilir kişi yüzü, ünlü, logo, marka, telifli karakter ve görsel içinde okunaklı yazı yok.** Yine de yayından önce görselleri gözle kontrol et. Haber metinleri kaynak siteden yeniden yazılır; kaynak linki her `senaryo_tr.md`'de durur.

---

## Sık sorunlar

| Sorun | Çözüm |
|---|---|
| `GPU bulunamadı` | Colab'da runtime'ı **T4 GPU** yap, ya da `images.provider: "fal"`. |
| Colab FLUX yüklerken çöküyor / "session crashed" | Ücretsiz Colab'ın ~12 GB RAM'i FLUX için yetmeyebilir. `images.provider: "fal"` kullan veya Colab Pro'da L4/A100 + High-RAM seç. |
| `CUDA out of memory` (Flux) | Kod 30 GB altı kartlarda (T4/L4) `enable_sequential_cpu_offload()` (yavaş ama düşük VRAM), 30–40 GB'ta `enable_model_cpu_offload()` kullanır. Yine olmuyorsa `provider: "fal"`. |
| `HİÇ GÖRSEL ÜRETİLEMEDİ` | Görseller başarısız oldu; o haberler "görüldü" sayılmaz, bir sonraki çalıştırmada tekrar denenir. `provider: "fal"`'a geç. |
| `Chatterbox Multilingual bulunamadı` | `pip install -r requirements-voice.txt`. Paket API'si değiştiyse sınıf `chatterbox.mtl_tts.ChatterboxMultilingualTTS` altında olmalı. |
| `ImportError: FluxPipeline` | Chatterbox, diffusers'ı 0.29'a düşürmüş. `pip install -U "diffusers>=0.30"` ya da ayrı ortam kullan. |
| `DEEPSEEK_API_KEY bulunamadı` | Proje kökünde `.env` var mı ve anahtar dolu mu kontrol et. |
| `feeds hâlâ örnek adresi içeriyor` | `config.yaml → feeds` altına kendi RSS adresini yaz. |
| `İşlenecek yeni haber yok` | Tüm haberler daha önce işlenmiş. Yeni haber bekle veya `state/seen.json`'u sil. |
| Klon ses kötü | Referans kaydını daha temiz/uzun yap; `voice.exaggeration` ve `cfg_weight` ile oyna. |

---

## Geliştirme

```bash
pip install -r requirements-dev.txt
pytest --cov=bulten --cov=run_text --cov=run_voice
```

Testler ağ, DeepSeek, GPU veya model indirmeden sahte nesnelerle çalışır.
