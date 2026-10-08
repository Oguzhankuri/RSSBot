# 📰 Günlük Bülten

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
