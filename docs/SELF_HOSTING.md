# RSSBot — Sunucuya Kurulum Rehberi (Self-Hosted)

> **Kime:** Sistemi sunucuya kuracak kişi.
> **Süre:** ~45–60 dk.
> **Bu repo PUBLIC'tir.** Bu dosyada hiçbir şifre/anahtar yoktur ve olmamalıdır. Gizli değerler sunucuda üretilir;
> repoya, issue'lara, PR açıklamalarına ve commit'lere **asla** yazılmaz.

---

## 1. Ne kuruluyor? (mimari)

Tek bir ücretsiz alan adı (DuckDNS) altında her şey:

```
 https://rssbot-xxx.duckdns.org
 ┌──────────────────────────── SUNUCU ─────────────────────────────┐
 │ Caddy :443 (HTTPS, otomatik sertifika)                          │
 │   ├─ /            → panel  (Streamlit, şifreli giriş)           │
 │   └─ /rest/v1/*   → rest   (PostgREST, service key ister)       │
 │                       └─ db (Postgres, dışarı kapalı)           │
 │ worker: Telegram → Fikir Kutusu (2 dk'da bir, 7/24)             │
 │ /mnt/gdrive  ← rclone ile Google Drive (çıktı klasörü)          │
 └─────────────────────────────────────────────────────────────────┘
 Colab (GPU) ──── /rest/v1 + aynı Google Drive klasörü
 Telefon/PC  ──── tarayıcıdan panel (şifre)
```

| Servis | İmaj | Görev | Dışarı açık mı? |
|---|---|---|---|
| `gateway` | `caddy:2.8-alpine` | HTTPS, yönlendirme, güvenlik başlıkları | ✅ 80, 443 |
| `panel` | `rssbot-panel` (repo'dan derlenir) | Bülten Stüdyosu arayüzü | ❌ (Caddy arkasında) |
| `worker` | `rssbot-panel` | Telegram fikir senkronu | ❌ |
| `rest` | `postgrest/postgrest:v12.2.3` | Veritabanı REST API'si (Supabase uyumlu) | ❌ (Caddy arkasında) |
| `db` | `postgres:16-alpine` | Veriler | ❌ |

**Kod imaja gömülmez:** repo klasörü konteynerlere bağlanır. Güncelleme = `git pull` + yeniden başlatma.

### Güvenlik modeli
- **Panel:** yalnızca şifre (kullanıcı adı yok). Şifrenin kendisi saklanmaz, `.env`'de yalnızca **scrypt özeti** durur.
  Yanlış denemelerde bekleme süresi katlanarak artar (en çok 15 dk). Giriş 30 gün hatırlanır (imzalı çerez); şifre değişince tüm oturumlar düşer.
  Şifre tanımlanmadan panel **açılmaz** (`BULTEN_PUBLIC=1`).
- **API:** `anon` rolü hiçbir şeye erişemez → anahtarsız istek **401**. `SUPABASE_SERVICE_KEY` (service_role JWT) tam erişimlidir — şifre gibi sakla.
- Postgres ve PostgREST hiçbir porttan dışarı açılmaz.

---

## 2. Gereksinimler

- **Sunucu:** Ubuntu 22.04/24.04 ya da Debian 12, **2 GB RAM** önerilir (1 GB + 2 GB swap da olur), 20 GB disk.
- **Portlar:** 22 (SSH), 80, 443.
- **Ücretsiz alan adı:** [duckdns.org](https://www.duckdns.org) → Google/GitHub ile giriş → bir alt alan adı al (ör. `rssbot-xxx`)
  → **current ip** kutusuna sunucunun IP'sini yaz → *update ip*. Adres: `rssbot-xxx.duckdns.org`.
- **Google hesabı erişimi:** Drive bağlantısı için proje sahibinin bir kez onay vermesi gerekir (Bölüm 3.4).

---

## 3. Kurulum

### 3.1 Sunucuyu hazırla
```bash
# Ayrı, yetkisiz kullanıcı
sudo adduser --disabled-password --gecos "" rssbot

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker rssbot

# Güvenlik duvarı
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
sudo ufw enable

# Küçük sunucularda swap (2 GB)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```
> ⚠️ Compose dosyalarına **asla** `5432`, `3000` ya da `8501` portu ekleme.

### 3.2 Kodu çek
```bash
sudo mkdir -p /opt/rssbot && sudo chown rssbot:rssbot /opt/rssbot
sudo -iu rssbot
git clone https://github.com/Oguzhankuri/RSSBot.git /opt/rssbot
cd /opt/rssbot
```
(Bundan sonraki komutlar `rssbot` kullanıcısıyla, `/opt/rssbot` içinde.)

### 3.3 Veritabanı şifreleri ve alan adı
```bash
python3 docker/setup_db.py --server rssbot-xxx.duckdns.org
chmod 600 docker/.env .env
```
- `docker/.env`: Postgres/PostgREST şifreleri, `JWT_SECRET`, `SITE_ADDRESS` (rastgele ve güçlü; tekrar çalıştırılırsa korunur).
- `.env` (proje kökü): sunucudaki panelin kullanacağı `SUPABASE_SERVICE_KEY`.
- Ekrana **bir kez** `SUPABASE_URL` ve `SUPABASE_SERVICE_KEY` basar → Colab için gerekli, **Bölüm 5**'teki yolla proje sahibine ilet, sonra `clear`.

### 3.4 Google Drive bağlantısı (rclone)
Panelin ürettiği senaryolar ve Colab'ın ürettiği görsel/sesler aynı Drive klasöründe buluşur.

```bash
sudo apt-get install -y rclone fuse3
echo user_allow_other | sudo tee -a /etc/fuse.conf
sudo mkdir -p /mnt/gdrive && sudo chown rssbot:rssbot /mnt/gdrive
rclone config        # n → ad: gdrive → storage: drive → client_id/secret boş → scope: 1 (drive)
                     # → "Use web browser to automatically authenticate?" → n (sunucuda tarayıcı yok)
```
Son adımda rclone bir `rclone authorize "drive" "..."` komutu verir. Bu komut, **proje sahibinin** (Drive'ın sahibi) kendi
bilgisayarında çalıştırılır ([rclone.org/downloads](https://rclone.org/downloads/)); tarayıcıda Google onayı açılır,
çıkan token sunucudaki rclone'a yapıştırılır. *(Token Drive'a erişim verir: Bölüm 5'teki gibi güvenli ilet.)*

```bash
exit   # root/sudo kullanıcısına dön
sudo cp /opt/rssbot/docker/rclone-gdrive.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now rclone-gdrive
ls /mnt/gdrive/gunluk-bulten     # → output, refs … görünmeli
sudo -iu rssbot && cd /opt/rssbot
```
`docker/.env`'e çıktı klasörünü ve kullanıcı kimliğini ekle:
```bash
cat >> docker/.env <<EOF
OUTPUT_HOST_DIR=/mnt/gdrive/gunluk-bulten/output
APP_UID=$(id -u)
APP_GID=$(id -g)
EOF
```

### 3.5 Uygulama anahtarları ve panel şifresi
Proje kökündeki `.env`'e uygulama anahtarlarını **proje sahibi** girer (sunucuya SSH ile ya da kurulumu yapan kişi
güvenli yoldan alıp girer):
```bash
nano .env
```
```
DEEPSEEK_API_KEY=...            # zorunlu (senaryo)
FAL_KEY=...                     # images.provider=fal ise
TELEGRAM_BOT_TOKEN=...          # Telegram fikir kutusu
TELEGRAM_ALLOWED_USER_ID=...    # sadece bu kişinin mesajları kabul edilir
```
Panel şifresi (en az 12 karakter; proje sahibi kendisi yazsın — ekranda görünmez):
```bash
python3 -m bulten.auth set-password
```
`.env`'e `PANEL_PASSWORD_HASH` (özet) ve `PANEL_SESSION_SECRET` yazılır. Şifrenin kendisi hiçbir yere kaydedilmez.

### 3.6 Başlat
```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml up -d --build
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml ps
```
İlk açılışta Postgres şemayı kurar, Caddy Let's Encrypt sertifikasını alır (birkaç saniye–1 dk), panel imajı derlenir (~2–3 dk).

> Kısayol için: `echo "alias rss='docker compose -f /opt/rssbot/docker/docker-compose.yml -f /opt/rssbot/docker/docker-compose.server.yml'" >> ~/.bashrc && source ~/.bashrc`
> → sonra `rss ps`, `rss logs -f panel`, `rss up -d` …

### 3.7 Doğrula
```bash
D=rssbot-xxx.duckdns.org
curl -s -o /dev/null -w "%{http_code}\n" http://$D/                   # 308 (HTTPS'e yönlendirme)
curl -s https://$D/_stcore/health                                     # ok (panel)
curl -s -o /dev/null -w "%{http_code}\n" https://$D/rest/v1/ideas     # 401 (anahtarsız API kapalı ✅)
read -s KEY; curl -s -o /dev/null -w "%{http_code}\n" -H "apikey: $KEY" -H "Authorization: Bearer $KEY" "https://$D/rest/v1/ideas?limit=1"; unset KEY   # 200
rss logs --tail=5 worker                                              # Telegram senkronu hatasız mı
```
Tarayıcıdan `https://rssbot-xxx.duckdns.org` → şifre ekranı → giriş.

---

## 4. Mevcut veriyi PC'den taşıma (varsa)

**PC'de** (proje klasöründe):
```bash
docker compose -f docker/docker-compose.yml exec -T db pg_dump -U postgres --data-only --no-owner --no-privileges postgres > rssbot-veri.sql
scp rssbot-veri.sql rssbot@SUNUCU_IP:/opt/rssbot/
```
**Sunucuda:**
```bash
rss exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1 < rssbot-veri.sql
shred -u rssbot-veri.sql
```
PC'deki kopyayı da sil (içinde fikirler var).

---

## 5. Gizli değerler: kim, nerede, nasıl?

| Değer | Üretildiği yer | Durduğu yer | Kim bilmeli |
|---|---|---|---|
| `POSTGRES_PASSWORD`, `AUTHENTICATOR_PASSWORD`, `JWT_SECRET` | sunucu (`setup_db.py`) | sunucu `docker/.env` | kimse (sunucudan çıkmaz) |
| `SUPABASE_SERVICE_KEY` | sunucu | sunucu `.env` + **Colab Secrets** | proje sahibi |
| Panel şifresi | proje sahibi | hiçbir yerde (sadece özeti) | proje sahibi |
| `DEEPSEEK_API_KEY`, `FAL_KEY`, `TELEGRAM_*`, `HF_TOKEN` | proje sahibi | sunucu `.env` (HF_TOKEN yalnız Colab) | proje sahibi |
| rclone Drive token'ı | proje sahibinin onayı | sunucu `~/.config/rclone/rclone.conf` | kimse |

**Aktarım yöntemi** (tercih sırasıyla): ortak şifre yöneticisi (Bitwarden/1Password) → tek seferlik not (Bitwarden Send) →
uçtan uca şifreli mesaj (WhatsApp/Signal; **kaybolan mesajlar açık**, okununca iki taraftan silinsin).
**Asla:** repo, issue, PR, e-posta, ekran görüntüsü.

**Kurulumdan sonra proje sahibinin yapacakları:**
1. **Colab** → 🔑 Secrets: `SUPABASE_URL=https://rssbot-xxx.duckdns.org`, `SUPABASE_SERVICE_KEY`, `HF_TOKEN` (artık tünel gerekmez).
2. `config.yaml` → `colab.notebook_url` aynı kalır. Panel artık `https://rssbot-xxx.duckdns.org`.
3. GitHub Actions Telegram workflow'u gereksiz (sunucudaki `worker` yapıyor): *Actions → telegram-fikir-senkronu → Disable workflow*.
4. PC'deki yerel Docker yığını kapatılabilir: `docker compose -f docker/docker-compose.yml --profile tunnel down`.

---

## 6. İşletme

### Yedek (her gece, 14 gün sakla)
```bash
mkdir -p ~/yedek && crontab -e
30 3 * * * cd /opt/rssbot && docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml exec -T db pg_dump -U postgres postgres | gzip > ~/yedek/rssbot-$(date +\%F).sql.gz && find ~/yedek -name '*.sql.gz' -mtime +14 -delete
```
Geri yükleme (boş kuruluma): `gunzip -c ~/yedek/rssbot-TARIH.sql.gz | rss exec -T db psql -U postgres -d postgres`

### Güncelleme
```bash
cd /opt/rssbot && git pull
rss up -d --build          # requirements.txt değiştiyse imaj yeniden derlenir
rss restart panel worker   # yalnızca kod değiştiyse yeterli
```
> Yeni şema dosyası (`db/migrations/002_*.sql`) gelirse elle uygula, ardından yetkileri tazele:
> `rss exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1 < db/migrations/002_xxx.sql`
> `rss exec -T db psql -U postgres -d postgres < docker/initdb/02_grants.sql`

### Loglar
`rss logs -f --tail=100 panel worker gateway rest`

### Şifre / anahtar yenileme
- **Panel şifresi:** `python3 -m bulten.auth set-password` → `rss restart panel` (tüm açık oturumlar düşer).
- **Service key sızdıysa:** `docker/.env`'den `JWT_SECRET` satırını sil → `python3 docker/setup_db.py --server <alan-adi>`
  → `rss up -d --force-recreate rest panel worker` → yeni anahtarı Colab Secrets'a gir.
- **DuckDNS IP değişirse:** duckdns.org'da *update ip* (sunucu IP'si sabitse gerekmez).

---

## 7. Sorun giderme

| Belirti | Çözüm |
|---|---|
| Panelde "şifre tanımlı değil" | `python3 -m bulten.auth set-password` → `rss restart panel` |
| "Çok fazla hatalı deneme" | Bekle (en çok 15 dk) ya da `rss restart panel` |
| Caddy sertifika alamıyor | `dig +short rssbot-xxx.duckdns.org` sunucu IP'sini mi gösteriyor? 80/443 açık mı (`sudo ufw status`)? |
| `required variable SITE_ADDRESS / OUTPUT_HOST_DIR` | `docker/.env` eksik → Bölüm 3.3 / 3.4 |
| Panelde "…bulunamadı ya da eksik. Drive senkronu…" | `systemctl status rclone-gdrive`, `ls /mnt/gdrive/gunluk-bulten/output` |
| Panel dosya yazamıyor (`Permission denied`) | `docker/.env` → `APP_UID`/`APP_GID` = `id -u`/`id -g` (rssbot); `rss up -d` |
| API anahtarla da 401 `JWSInvalidSignature` | Anahtar başka sırla imzalanmış (PC'ninki?) → sunucuda üretileni kullan |
| `permission denied for table` | `02_grants.sql`'i tekrar çalıştır (Bölüm 6) |
| `rest` sürekli yeniden başlıyor | `rss logs rest` — çoğunlukla `AUTHENTICATOR_PASSWORD` volume'daki şifreyle uyuşmuyor |
| worker: `TELEGRAM_ALLOWED_USER_ID sayısal…` | `.env`'e Telegram bilgilerini gir → `rss restart worker` |
| Bellek yetmiyor (OOM) | Swap ekle (3.1); `docker stats` |

---

## 8. Kontrol listesi

- [ ] `http://<alan-adi>/` → HTTPS'e yönlendiriyor (308)
- [ ] `https://<alan-adi>/` → şifre ekranı; yanlış şifre reddediliyor, doğru şifreyle giriliyor
- [ ] `…/rest/v1/ideas` anahtarsız **401**, anahtarlı **200**
- [ ] `ss -tlnp` → yalnızca 22, 80, 443 dışarı açık (5432/3000/8501 YOK)
- [ ] `docker/.env` ve `.env` izinleri `600`, `git status` temiz (gizli dosya izlenmiyor)
- [ ] `/mnt/gdrive/gunluk-bulten/output` görünüyor, panelden yüklenen dosya Drive'da çıkıyor
- [ ] `rss logs worker` → Telegram'dan atılan test mesajı Fikir Kutusu'nda
- [ ] Günlük yedek cron'u kurulu, bir yedek oluştu
- [ ] `SUPABASE_SERVICE_KEY` güvenli yolla iletildi; ekran ve geçmiş temizlendi (`history -c`)

---

## 9. Repo erişimi (proje sahibi için)

- Kurulum için yazma yetkisi **gerekmez** (repo public). Kod değiştirecekse *Settings → Collaborators* → **Write** (Admin **verme**).
- `main` dalını koru: *Settings → Branches → Add rule → main* → "Require a pull request before merging".
  Sunucu ve Colab kodu `main`'den çeker: `main`'e giren kod, sunucudaki tüm anahtarlarla çalışır.
