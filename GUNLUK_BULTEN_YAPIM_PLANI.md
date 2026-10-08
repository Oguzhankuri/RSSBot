# Günlük Bülten — Haber → İçerik + Görsel + Çok Dilli Seslendirme Otomasyonu
## Claude Code İçin Eksiksiz Yapım Planı (Plan Mode)

> **Bu dosya ne?** Claude Code'a verilecek, projeyi **adım adım, hiçbir şeyi atlamadan** inşa ettirecek teknik spesifikasyondur. Claude Code bunu plan mode'da okuyup bir plan çıkarmalı, sonra **modül modül** uygulamalı ve her modülden sonra **test kontrol noktasını** geçmeli.
>
> **Kullanıcı yalnızca `config.yaml` içine RSS adresini ve 4 hedef dili yazacak.** Başka hiçbir manuel kod müdahalesi gerekmemeli.

---

## 0. Claude Code İçin Çalışma Kuralları (ÖNEMLİ — önce bunu oku)

1. **Plan mode ile başla.** Önce tüm bu dosyayı oku, sonra adım sırasına birebir uyan bir uygulama planı sun (`ExitPlanMode`), onay al, sonra kodla.
2. **Sırayı bozma.** Bölüm 7'deki adımlar bağımlıdır. Her adımı bitirince o adımın **"✅ Test Kontrol Noktası"**nı çalıştır; geçmeden bir sonraki adıma geçme.
3. **Hiçbir modülü atlama, placeholder bırakma.** Her fonksiyon tam çalışır olmalı. `TODO` / `pass` ile boş bırakma.
4. **Gizli anahtarları koda gömme.** Tüm anahtarlar `.env` üzerinden okunur.
5. **İki faz var:** `run_text.py` (metin+görsel, tam otomatik) ve `run_voice.py` (Chatterbox ile 4 dil ses). Arada kullanıcı Türkçe'yi kendi sesiyle kaydeder. Bu ayrımı koru.
6. **GPU adımları** (Flux görsel + Chatterbox ses) Colab/yerel GPU'da çalışır; **metin** (DeepSeek) saf API çağrısıdır, GPU istemez.
7. Kod ve değişken adları İngilizce; kullanıcıya dönük metinler (log, README, çıktı başlıkları) Türkçe.
8. Python 3.10+. Tip ipuçları (type hints) kullan. Her modülde `logging` ile ilerleme bas.

---

## 1. Proje Amacı

Bir haber sitesinin RSS'inden günde **8 haber** çekip:
- Her haberi akıcı bir **Türkçe YouTube bülten senaryosuna** çevirmek (DeepSeek),
- Senaryoyu **4 yabancı dile** çevirmek (kullanıcı bunları kendi klon sesiyle seslendirecek),
- Her habere **3 adet AI görsel** üretmek (Flux schnell, telifsiz),
- **4 dildeki seslendirmeyi** kullanıcının kendi sesinin klonundan üretmek (Chatterbox Multilingual),
- Hepsini **tarih/haber bazlı klasörlere** düzenlemek.

Nihai çıktı **video değil**; düzenli klasör + tüm materyaller. Kullanıcı videoyu sonra kendi montajlar.

---

## 2. Kesinleşen Teknoloji Stack (değiştirme)

| Katman | Araç / Model | Lisans | Nerede çalışır | Maliyet |
|---|---|---|---|---|
| Metin yazımı + çeviri | **DeepSeek API** (`deepseek-chat`, OpenAI uyumlu) | — | API (GPU yok) | ~$1–2/ay |
| Görsel (24/gün) | **FLUX.1-schnell** (`diffusers`) | Apache-2.0 (ticari serbest ✅) | Colab/yerel GPU | $0 |
| Görsel (yedek) | **fal.ai** Flux API | — | API | ~$2–11/ay |
| TR seslendirme | Kullanıcının kendi kaydı | — | Manuel | $0 |
| 4 dil seslendirme | **Chatterbox Multilingual V3** (`chatterbox-tts`) | **MIT (ticari serbest ✅)** | Colab/yerel GPU | $0 |

**Neden bu modeller:** Kanal **monetize** edilecek. XTTS-v2 ve F5-TTS-Turkish gibi popüler açık modeller **CC-BY-NC (ticari yasak)** olduğu için elenmiştir. Chatterbox **MIT** olduğu ve Türkçe dahil 23 dili + referans sesten klonlamayı desteklediği için seçilmiştir. Flux schnell **Apache-2.0** olduğu için ticari görselde güvenlidir.

**Telif/YouTube notu:** AI ile üretilen *orijinal* görsel/ses Content ID'ye takılmaz. Prompt'larda **gerçek tanınabilir yüz, logo, marka, telifli karakter ve görsel içi okunaklı yazı** ÜRETİLMEMELİDİR (bu kural görsel prompt üretimine gömülecek — bkz. Bölüm 9).

---

## 3. Klasör Yapısı (repo)

```
gunluk-bulten/
├── README.md                     # kurulum + kullanım (Claude Code üretecek)
├── requirements.txt              # API/CPU bağımlılıkları
├── requirements-gpu.txt          # torch, diffusers, chatterbox-tts (Colab/GPU)
├── .env.example                  # DEEPSEEK_API_KEY=, FAL_KEY=
├── config.yaml                   # feeds, diller, sayılar, sağlayıcı seçimi
├── gunluk_bulten_colab.ipynb     # Colab başlangıç notebook'u (kur + çalıştır)
├── run_text.py                   # FAZ A: ingest→rewrite→translate→images→organize
├── run_voice.py                  # FAZ B: Chatterbox ile 4 dil ses
├── bulten/
│   ├── __init__.py
│   ├── config.py                 # config.yaml + .env yükle & doğrula
│   ├── utils.py                  # slugify_tr, logging, tarih, dosya yardımcıları
│   ├── state.py                  # görülen haberleri takip (tekrar engeli)
│   ├── ingest.py                 # RSS (feedparser) + tam metin (trafilatura)
│   ├── rewrite.py                # DeepSeek: haber → bülten senaryosu (JSON)
│   ├── translate.py              # DeepSeek: TR → 4 dil
│   ├── images.py                 # Flux schnell (GPU) | fal.ai (API) soyutlaması
│   ├── voice.py                  # Chatterbox Multilingual klonlama (GPU)
│   └── organize.py               # klasör oluşturma + kaydetme + manifest
├── refs/
│   └── ref_voice.wav             # kullanıcının referans sesi (klonlama için)
├── state/
│   └── seen.json                 # daha önce işlenen haber URL'leri
└── output/
    └── YYYY-MM-DD/ ...           # günlük çıktı (Bölüm 4)
```

---

## 4. Çıktı Klasör Şeması (kesin biçim)

```
output/2026-10-08/
├── bulten.md                     # günün index'i: 8 haberin başlık+özeti
├── manifest.json                 # tüm günün makine-okunur özeti
├── 01-<slug>/
│   ├── senaryo_tr.md             # Türkçe bülten senaryosu (kullanıcı bunu okuyacak)
│   ├── metadata.json             # kaynak url, tarih, başlık, etiketler, görsel promptları
│   ├── ceviriler/
│   │   ├── en.md
│   │   ├── de.md
│   │   ├── ar.md
│   │   └── ru.md
│   ├── gorseller/
│   │   ├── 01.png
│   │   ├── 02.png
│   │   ├── 03.png
│   │   └── prompts.txt           # kullanılan görsel promptları (izlenebilirlik)
│   └── ses/
│       ├── tr.wav                # BOŞ — kullanıcı manuel ekler (README not düşülür)
│       ├── en.wav                # Chatterbox (FAZ B)
│       ├── de.wav
│       ├── ar.wav
│       └── ru.wav
├── 02-<slug>/ ...
└── ... (08-<slug>/ 'e kadar)
```

- `<slug>`: Türkçe karakter-güvenli, kısaltılmış başlık (bkz. `utils.slugify_tr`).
- Sıra numarası `01..08` iki hane, sıfır dolgulu.

---

## 5. config.yaml (şema + varsayılanlar)

Claude Code bu dosyayı **birebir** bu alanlarla üretsin. Kullanıcı sadece `feeds` ve `languages`'ı dolduracak.

```yaml
site:
  name: "Benim Haber Sitem"

feeds:
  # >>> KULLANICI BURAYA RSS ADRES(LER)İNİ YAZACAK <<<
  - "https://ORNEK-HABER-SITESI.com/rss"
  # birden fazla olabilir

ingest:
  max_items: 8             # günde kaç haber
  fetch_full_text: true    # makale sayfasından tam metni çek (trafilatura)
  dedupe: true             # state/seen.json ile tekrarı engelle
  min_chars: 200           # bundan kısa haberleri ele

rewrite:
  provider: "deepseek"
  model: "deepseek-chat"
  base_url: "https://api.deepseek.com"
  target_words: 110        # her haber senaryosu ~kaç kelime (8×110 ≈ 8 dk)
  tone: "net, tarafsız, akıcı, YouTube haber bülteni anlatımı"

translate:
  enabled: true
  # >>> KULLANICI 4 HEDEF DİLİ BURAYA YAZACAK (ISO kodu) <<<
  languages: ["en", "de", "ar", "ru"]

images:
  provider: "flux_local"   # flux_local (Colab GPU) | fal (API)
  model_id: "black-forest-labs/FLUX.1-schnell"
  count_per_item: 3
  width: 1280
  height: 720              # 16:9
  steps: 4                 # schnell için 4 adım yeterli
  style: "modern, temiz, gerçekçi haber illüstrasyonu, sinematik ışık"
  fal_model: "fal-ai/flux/schnell"   # provider=fal ise

voice:
  enabled: true
  engine: "chatterbox"
  device: "cuda"           # GPU; yoksa "cpu" (çok yavaş)
  ref_audio: "refs/ref_voice.wav"   # kullanıcının referans sesi
  languages: ["en", "de", "ar", "ru"]   # translate.languages ile aynı olmalı
  max_chars_per_chunk: 300            # uzun metni cümlelere böl
  exaggeration: 0.5
  cfg_weight: 0.5

output:
  base_dir: "output"
  # Colab'da Drive'a yazmak için: "/content/drive/MyDrive/gunluk-bulten/output"
```

---

## 6. .env.example

```
# DeepSeek (zorunlu — metin + çeviri için)
DEEPSEEK_API_KEY=

# Sadece images.provider=fal ise gerekli
FAL_KEY=
```

`bulten/config.py` bunları `python-dotenv` ile yükler. `DEEPSEEK_API_KEY` yoksa `run_text.py` anlamlı bir hatayla durur (sessizce geçme).

---

## 7. ADIM ADIM YAPIM PLANI (sıra bozulmaz)

### Adım 1 — İskelet + bağımlılıklar
- Bölüm 3'teki klasör/dosya iskeletini oluştur. Boş `__init__.py`, boş `state/`, `refs/`, `output/` klasörleri (`.gitkeep` ile).
- `requirements.txt`:
  ```
  feedparser
  trafilatura
  requests
  openai>=1.40
  pyyaml
  python-dotenv
  pillow
  soundfile
  ```
- `requirements-gpu.txt` (Colab/GPU):
  ```
  torch
  torchaudio
  diffusers>=0.30
  transformers
  accelerate
  sentencepiece
  chatterbox-tts
  ```
- `.env.example` ve örnek `config.yaml`'ı Bölüm 5–6'ya göre yaz.

**✅ Test:** `python -c "import feedparser, trafilatura, yaml, dotenv, openai"` hatasız dönmeli.

---

### Adım 2 — `bulten/utils.py`
Fonksiyonlar:
- `slugify_tr(text: str, max_len: int = 50) -> str` — Türkçe harfleri sadeleştir (ç→c, ğ→g, ı→i, ö→o, ş→s, ü→u, İ→i), küçült, alfanümerik dışını `-` yap, kırp.
- `today_str(tz="Europe/Istanbul") -> str` — `YYYY-MM-DD`.
- `ensure_dir(path)` — klasör oluştur (varsa geç).
- `setup_logging()` — `logging` INFO formatı (zaman + modül + mesaj).
- `write_text(path, content)`, `read_json/write_json`.

**✅ Test:** `slugify_tr("Çanakkale'de İşçi Grevi Büyüyor!")` → `canakkale-de-isci-grevi-buyuyor` benzeri; `today_str()` doğru tarihi dönmeli.

---

### Adım 3 — `bulten/config.py`
- `load_config(path="config.yaml") -> dict` — YAML + `.env` yükle, birleştir.
- Doğrulama: `feeds` boş değil mi, `translate.languages` ile `voice.languages` tutarlı mı, `DEEPSEEK_API_KEY` var mı (metin fazı için). Eksikse açık Türkçe hata ver.
- `get_env(key, required=False)` yardımcı.

**✅ Test:** Örnek config + sahte `.env` ile `load_config()` sözlük dönmeli; `DEEPSEEK_API_KEY` boşken `require_text=True` çağrısı anlamlı hata fırlatmalı.

---

### Adım 4 — `bulten/state.py` (tekrar engeli)
- `load_seen(path="state/seen.json") -> set[str]`
- `mark_seen(urls: list[str])` — ekle ve kaydet.
- Haber kimliği: RSS entry'nin `link` veya `id`'si (yoksa başlık hash'i).

**✅ Test:** Aynı URL iki kez `mark_seen` edilince set tek kayıt tutmalı; dosya kalıcı olmalı.

---

### Adım 5 — `bulten/ingest.py`
- `fetch_feed_items(cfg) -> list[dict]`:
  1. `feedparser` ile tüm `feeds`'i oku.
  2. Her entry'den `{title, link, published, summary}` çıkar.
  3. `dedupe=true` ise `state.seen` içindekileri at.
  4. `fetch_full_text=true` ise `link`'i çek ve `trafilatura.extract` ile tam metni al; başarısızsa `summary`'ye düş.
  5. `min_chars` altındakileri ele.
  6. En yeni → `max_items` (8) taneye indir.
  7. Dönen her öğe: `{title, link, published, text}`.
- Ağ hatalarını yakala, o entry'i atla, logla (tüm akış çökmemeli).
- User-Agent header ver; istek zaman aşımı 15 sn.

**✅ Test:** Config'e gerçek/örnek bir RSS koyup çalıştır → en fazla 8 öğe, her birinde dolu `text` (≥ min_chars) olmalı. (Claude Code test için küçük bir genel RSS kullanabilir; kullanıcının RSS'i sonradan girilecek.)

---

### Adım 6 — `bulten/rewrite.py` (DeepSeek senaryo)
- `DeepSeekClient`: `openai.OpenAI(api_key=..., base_url=cfg.rewrite.base_url)`.
- `rewrite_item(item: dict, cfg) -> dict` — bir haberden JSON üretir.
- **Sistem promptu:**
  > Sen profesyonel bir Türkçe haber editörüsün. Verilen ham haberi, bir YouTube günlük haber bülteninde SESLENDİRİLECEK; akıcı, net, tarafsız, kısa cümleli bir anlatım senaryosuna dönüştürürsün. Abartı, yorum ve taraf tutma yok.
- **Kullanıcı promptu** (şablon): ham `title` + `text` ver, şu JSON'u iste (`response_format={"type":"json_object"}`):
  ```json
  {
    "baslik": "video içi kısa başlık (≤ 70 karakter)",
    "senaryo": "~{target_words} kelimelik Türkçe seslendirme metni",
    "ozet": "tek cümle özet",
    "gorsel_promptleri": ["İngilizce prompt 1", "prompt 2", "prompt 3"],
    "etiketler": ["3-5 etiket"]
  }
  ```
- **Görsel promptu kuralı (sisteme göm):** prompt'lar İngilizce, gerçekçi haber illüstrasyonu; **gerçek tanınabilir kişi yüzü, ünlü, logo, marka adı/ambalajı, telifli karakter ve görsel içinde okunaklı metin İÇERMEYECEK.** Jenerik, simgesel, haber-temalı sahneler.
- JSON parse güvenliği: kod bloğu işaretlerini temizle, `json.loads` başarısızsa bir kez daha dene (sıcaklık düşür), yine olmazsa `summary`'yi senaryo olarak kullanıp uyarı logla.
- `temperature` ~0.7.

**✅ Test:** Örnek bir haber metniyle çağır → geçerli JSON, `senaryo` Türkçe ve ~hedef uzunlukta, `gorsel_promptleri` tam 3 adet ve yasaklı öğe içermiyor.

---

### Adım 7 — `bulten/translate.py` (DeepSeek çeviri)
- `translate_text(text: str, lang: str, cfg) -> str`.
- Sistem promptu: "Sen uzman bir çevirmensin. Verilen Türkçe bülten senaryosunu, SESLENDİRMEYE uygun, doğal ve akıcı {dil adı} diline çevir. Anlamı ve haber tonunu koru. Sadece çeviriyi döndür, açıklama yapma."
- `lang` ISO kodunu insan-okunur dile çevir (`en→İngilizce` vb.) bir sözlükle.
- Her haber için `translate.languages`'teki tüm dilleri üret → `{lang: text}`.

**✅ Test:** Bir Türkçe paragrafı `en` ve `de`'ye çevir → mantıklı, açıklama/ön-ek içermeyen düz çeviri dönmeli.

---

### Adım 8 — `bulten/images.py` (Flux schnell / fal)
Soyutlama: `generate_images(prompts: list[str], out_dir: str, cfg) -> list[str]`.

**provider = `flux_local` (varsayılan, Colab GPU):**
- `diffusers.FluxPipeline.from_pretrained(cfg.images.model_id, torch_dtype=torch.bfloat16)`.
- VRAM yönetimi: `pipe.enable_model_cpu_offload()` (T4/L4 için şart; A100'de gerekmeyebilir). Bir kez yükle, tüm görsellerde yeniden kullan (modeli her çağrıda yükleme).
- `pipe(prompt, num_inference_steps=cfg.images.steps, width=.., height=.., guidance_scale=0.0)` → PNG kaydet.
- Stil son-eki: her prompt'a `cfg.images.style` eklenir.
- Negatif/yasak: prompt üretimi Adım 6'da güvenli; yine de "no text, no watermark, no logos, no real faces" son-eki eklenebilir.

**provider = `fal` (yedek, API):**
- `fal_client` ile `cfg.images.fal_model` çağır, dönen URL'yi indir, kaydet.

- Çıktı: `gorseller/01.png..03.png` + `gorseller/prompts.txt`.
- GPU yoksa ve provider `flux_local` ise anlamlı hata: "GPU bulunamadı; images.provider=fal'a geç ya da GPU'lu ortamda çalıştır."

**✅ Test:** 1 prompt ile `flux_local` → 1 PNG (1280×720) üretmeli. GPU yoksa test `fal` ile veya atlanıp FAZ B'de yapılır; durumu logla.

---

### Adım 9 — `bulten/voice.py` (Chatterbox Multilingual)
- Model: `from chatterbox.mtl_tts import ChatterboxMultilingualTTS`; `model = ChatterboxMultilingualTTS.from_pretrained(device=cfg.voice.device)`. (Sınıf/import adını kütüphane sürümüne göre doğrula; gerekiyorsa `chatterbox` paketinin güncel API'sini kontrol et.)
- `synthesize(text, lang, ref_audio, cfg) -> np.ndarray/sr`:
  1. Uzun metni cümlelere böl (`max_chars_per_chunk`), parça parça üret.
  2. Her parça: `model.generate(chunk, language_id=lang, audio_prompt_path=ref_audio, exaggeration=.., cfg_weight=..)`.
  3. Parçaları birleştir (aralarına kısa sessizlik), tek dalga.
  4. `soundfile.write(out_path, wav, model.sr)` ile `ses/{lang}.wav` kaydet.
- Referans ses yoksa (`refs/ref_voice.wav`) anlamlı hata: "Önce kendi sesinizden bir referans kaydı `refs/ref_voice.wav` olarak ekleyin."
- Model bir kez yüklenir, tüm haber/dillerde yeniden kullanılır.
- `tr.wav` ÜRETİLMEZ (kullanıcı manuel ekler).

**✅ Test:** Kısa bir İngilizce cümleyi `ref_voice.wav` ile üret → geçerli, dinlenebilir `en.wav` (referans tınısına yakın). Türkçe referansla İngilizce üretimi doğrula (çapraz-dil klonlama).

---

### Adım 10 — `bulten/organize.py`
- `build_day_dirs(date_str, items, cfg)` — `output/<date>/NN-<slug>/` ağacını kurar (Bölüm 4).
- `save_item(dir, data)` — `senaryo_tr.md`, `metadata.json`, `ceviriler/*.md`, `gorseller/*` yazar; `ses/tr.wav` yerine `ses/OKU_BENI.txt` ("Türkçe sesinizi buraya `tr.wav` olarak ekleyin").
- `write_day_index(date_str, items)` — `bulten.md` (8 haberin başlık + tek cümle özeti + klasör linkleri) ve `manifest.json`.
- `senaryo_tr.md` biçimi: `# {baslik}` + kaynak linki + senaryo metni.

**✅ Test:** 2 sahte haberle tüm ağaç eksiksiz oluşmalı; `bulten.md` ve `manifest.json` tutarlı.

---

### Adım 11 — `run_text.py` (FAZ A — tam otomatik)
Akış:
```
config yükle → ingest → (her haber) rewrite → translate → images → organize
→ state.mark_seen → bulten.md + manifest.json
```
- İlerleme logla: "3/8 haber işlendi…".
- Bir haber çökerse diğerlerini sürdür (hatayı o haberin metadata'sına yaz).
- `images.provider=fal` ise GPU gerekmez; `flux_local` ise GPU'lu ortam (Colab) gerekir.
- Sonunda özet bas: kaç haber, kaç görsel, çıktı yolu.

**✅ Test:** Örnek RSS ile uçtan uca → `output/<bugün>/` altında 8 (veya feed'de kaç varsa) tam klasör, her birinde senaryo + 4 çeviri + 3 görsel.

---

### Adım 12 — `run_voice.py` (FAZ B — Chatterbox, GPU)
- Girdi: bir tarih (vars. bugün). O günün `output/<date>/NN-*/ceviriler/*.md` dosyalarını okur.
- Her haber, her dil için `voice.synthesize` → `ses/{lang}.wav`.
- Model bir kez yüklenir. İlerleme loglanır.
- `--date YYYY-MM-DD` argümanı (varsayılan bugün).
- `refs/ref_voice.wav` zorunlu; yoksa dur ve açıkla.

**Kullanım sırası (kullanıcıya):**
1. `run_text.py` → metin + görsel + çeviriler.
2. Kullanıcı `senaryo_tr.md`'leri **kendi sesiyle** okuyup her haberin `ses/tr.wav`'ını ekler; bir de temiz bir `refs/ref_voice.wav` referansı koyar.
3. `run_voice.py` → 4 dilin sesi klon sesle üretilir.

**✅ Test:** FAZ A çıktısı üzerinde `--date` ile çalıştır → her haber klasöründe 4 dil `.wav` oluşmalı.

---

### Adım 13 — `gunluk_bulten_colab.ipynb` (Colab notebook)
Hücreler (sırayla):
1. **(Markdown)** Başlık + kullanım açıklaması.
2. GPU kontrolü: `!nvidia-smi` — **Runtime türü GPU olmalı (TPU DEĞİL).** Bunu açıkça yaz.
3. Repo'yu getir (`git clone` veya dosya yükleme) + `pip install -r requirements.txt -r requirements-gpu.txt`.
4. (Opsiyonel) Google Drive mount; `output.base_dir`'i Drive'a ayarla.
5. `.env` oluşturma hücresi: `DEEPSEEK_API_KEY` gir.
6. `config.yaml` düzenleme hatırlatması: **RSS ve 4 dil**.
7. `!python run_text.py` çalıştır.
8. **(Markdown)** "Şimdi `senaryo_tr.md`'leri kendi sesinle oku, `tr.wav` ve `refs/ref_voice.wav` ekle."
9. `!python run_voice.py` çalıştır.
10. Çıktıyı zip'le / Drive'da göster.

**✅ Test:** Notebook hücreleri hatasız sıralı çalışmalı (Claude Code mantıksal doğruluğu ve komut sırasını kontrol etsin).

---

### Adım 14 — `README.md`
Şunları içersin: proje özeti, stack + lisanslar, kurulum (yerel ve Colab), `config.yaml`/`.env` doldurma, 3 adımlık kullanım akışı (FAZ A → manuel TR kayıt → FAZ B), çıktı klasör şeması, telif/YouTube notu, sık sorunlar (GPU yok, VRAM yetmiyor → `enable_model_cpu_offload` veya `provider=fal`, Chatterbox import adı).

---

## 8. DeepSeek Çağrı Detayları
- Endpoint OpenAI uyumlu: `OpenAI(api_key, base_url="https://api.deepseek.com")`, `model="deepseek-chat"`.
- `chat.completions.create(..., response_format={"type":"json_object"})` (rewrite için).
- Hız limiti/ağ hatasında üstel geri çekilme (exponential backoff), 3 deneme.

## 9. Görsel Güvenlik Kuralı (tek yerde)
Görsel prompt üretimi (Adım 6) ve `images.py` son-eki şunu garanti eder: **no real/identifiable people, no celebrities, no brand logos or packaging, no copyrighted characters, no readable text/watermark.** Haber illüstrasyonu simgesel ve jeneriktir. (Monetize güvenliği için zorunlu.)

## 10. Dil Kodları
`translate.languages` = `voice.languages` (aynı ISO kodları). İnsan-okunur eşleme sözlüğü `utils`'te: `en→English/İngilizce`, `de→German/Almanca`, `ar→Arabic/Arapça`, `ru→Russian/Rusça`, `tr→Turkish/Türkçe`… Kullanıcı 4 dili değiştirirse her iki listeyi de güncellemesi README'de belirtilir.

---

## 11. Kabul Kriterleri (hepsi ✅ olmadan proje "bitti" sayılmaz)

- [ ] `config.yaml`'a sadece RSS + 4 dil yazıp `run_text.py` çalıştırınca, **kod değişmeden** 8 haberlik tam çıktı üretiliyor.
- [ ] Her haber klasöründe: `senaryo_tr.md` (Türkçe, ~hedef uzunluk) + `ceviriler/` içinde 4 dil + `gorseller/` içinde 3 PNG (16:9).
- [ ] Görseller hiçbir gerçek yüz/logo/marka/okunaklı metin içermiyor.
- [ ] `run_voice.py`, `refs/ref_voice.wav` ile her haberin 4 dilde `.wav`'ını üretiyor; `tr.wav` üretmiyor.
- [ ] `dedupe` açıkken aynı haber ertesi gün tekrar işlenmiyor (`state/seen.json`).
- [ ] Tek bir haber/görsel/çeviri hatası tüm akışı çökertmiyor; hata loglanıp diğerleri sürüyor.
- [ ] GPU yokken anlamlı hata/yönlendirme veriyor (Flux/Chatterbox).
- [ ] `bulten.md` + `manifest.json` günün tamamını doğru özetliyor.
- [ ] Colab notebook'u baştan sona sıralı çalışıyor; GPU (TPU değil) uyarısı mevcut.
- [ ] README eksiksiz; kurulum sıfırdan takip edilebiliyor.

---

## 12. Hata Senaryoları & Fallback
| Durum | Davranış |
|---|---|
| RSS erişilemiyor | O feed'i atla, logla; hepsi erişilemezse anlamlı dur. |
| Tam metin çekilemedi | `summary`'ye düş. |
| DeepSeek JSON bozuk | 1 kez düşük sıcaklıkla yeniden dene; olmazsa `summary`'yi senaryo yap + uyar. |
| VRAM yetmiyor (Flux) | `enable_model_cpu_offload`; yine olmazsa `provider=fal` öner. |
| Chatterbox import adı farklı | Kütüphanenin güncel API'sini doğrula (`mtl_tts`/`tts` modül adı), uygun sınıfı kullan. |
| `ref_voice.wav` yok | FAZ B'yi durdur, kullanıcıya referans ekleme talimatı ver. |

---

## 13. Gelecek Geliştirmeler (opsiyonel, şimdi değil)
- Zamanlanmış çalıştırma (yerel cron / GitHub Actions — Colab 7/24 değil).
- Görsel üstüne Türkçe başlık kartı (Ideogram veya Pillow).
- Otomatik video montajı (ffmpeg) — kullanıcı isterse.
- Web paneli ile günün çıktısını önizleme.

---

**Özet:** Bu plan; ingest → DeepSeek senaryo → DeepSeek çeviri → Flux görsel → Chatterbox ses → klasörleme zincirini, iki faz ve net test kontrol noktalarıyla eksiksiz tanımlar. Claude Code plan mode'da bu sırayı izleyip her adımın testini geçerek projeyi uçtan uca kurabilir.
