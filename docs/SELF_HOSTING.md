# RSSBot — Sunucuya Kurulum Rehberi (Self-Hosted)

> **Kime:** Veritabanını sunucuya taşıyacak kişi.
> **Süre:** ~30–45 dk (alan adı DNS'i yayılırken bekleme hariç).
> **Bu repo PUBLIC'tir.** Bu dosyada hiçbir şifre/anahtar yoktur ve olmamalıdır. Gizli değerler sunucuda üretilir,
> repoya, issue'lara, PR açıklamalarına ve commit'lere **asla** yazılmaz.

---

## 1. Ne taşınıyor? (mimari)

Sunucuya **sadece veritabanı katmanı** gider. Geri kalan her şey olduğu yerde kalır:

```
                       ┌──────────────── SUNUCU (bu rehber) ────────────────┐
 PC: Panel (Streamlit) ─┤  Caddy :443 (HTTPS, otomatik sertifika)            │
 Colab (GPU işçisi)  ───┤     └─ /rest/v1/* → PostgREST :3000 (iç ağ)        │
 GitHub Actions      ───┤                       └─ Postgres :5432 (iç ağ)    │
   (Telegram senkronu)  └────────────────────────────────────────────────────┘
 Dosyalar (görsel/ses/senaryo) → Google Drive (değişmiyor)
```

| Bileşen | İmaj (sürüm sabit) | Görev | Dışarı açık mı? |
|---|---|---|---|
| `db` | `postgres:16-alpine` | Veriler: fikirler, içerikler, adımlar, metrikler, öğrenilmiş kurallar | ❌ Hayır |
| `rest` | `postgrest/postgrest:v12.2.3` | Postgres'i REST API olarak sunar (Supabase ile aynı API) | ❌ Hayır |
| `gateway` | `caddy:2.8-alpine` | HTTPS + `/rest/v1` yönlendirme | ✅ 80, 443 |
| `tunnel` | `cloudflared` | **Sunucuda KULLANILMAZ** (sadece PC'de geçici erişim içindi) | — |

Uygulama Supabase istemcisi gibi davranır: `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` ile `https://<alan-adi>/rest/v1/<tablo>` adresine konuşur.
Kodda değişiklik gerekmez.

### Güvenlik modeli
- `anon` rolü hiçbir tabloya erişemez (RLS açık, yetki yok) → anahtarsız istek **401**.
- `service_role` rolü tam erişimli; bu rol için imzalanan JWT = `SUPABASE_SERVICE_KEY`. **Bu anahtar ele geçerse tüm veri okunur/silinir.**
- JWT'yi imzalayan sır (`JWT_SECRET`) yalnızca sunucudaki `docker/.env` dosyasındadır.

---

## 2. Gereksinimler

- **Sunucu:** Ubuntu 22.04/24.04 (ya da Debian 12), **1 vCPU / 1 GB RAM** yeterli (2 GB rahat), 10 GB disk.
- **Alan adı:** Bir alt alan adı, ör. `db.ornekkanal.com`. DNS'te **A kaydı** → sunucunun IP'si (IPv6 varsa AAAA).
- **Açık portlar:** 22 (SSH), 80 ve 443 (Caddy sertifika alımı ve HTTPS için 80 de **açık olmalı**).
- **Yazılım:** Docker Engine + Docker Compose plugin, git, python3 (sadece kurulum betiği için; ek paket gerekmez).

---

## 3. Kurulum adımları

### 3.1 Sunucuyu hazırla
```bash
# Docker (resmi betik)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

# Güvenlik duvarı
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
```
> ⚠️ Docker, yayınladığı portlar için ufw'yi atlayabilir. Bu kurulumda yalnızca 80/443 yayınlanır (Postgres ve PostgREST
> yayınlanmaz), yani sorun yok — ama compose dosyasına **asla** `5432` ya da `3000` portu ekleme.

### 3.2 Kodu çek
```bash
sudo mkdir -p /opt/rssbot && sudo chown $USER /opt/rssbot
git clone https://github.com/Oguzhankuri/RSSBot.git /opt/rssbot
cd /opt/rssbot
```

### 3.3 Şifreleri üret (sunucuda, sıfırdan)
```bash
python3 docker/setup_db.py --server db.ornekkanal.com
```
Bu komut:
- `docker/.env` oluşturur: `POSTGRES_PASSWORD`, `AUTHENTICATOR_PASSWORD`, `JWT_SECRET` (rastgele, güçlü) ve `SITE_ADDRESS`.
- Ekrana **bir kez** `SUPABASE_URL` ve `SUPABASE_SERVICE_KEY` basar → bunları **Bölüm 5**'teki güvenli yolla proje sahibine ilet, sonra `clear`.
- Tekrar çalıştırılırsa var olan şifreleri **korur** (yeni anahtar imzalar ama aynı sırla; eski anahtar da geçerli kalır).

`docker/.env` git'e girmez (`.gitignore`'da). İzinlerini daralt:
```bash
chmod 600 docker/.env
```

> PC'deki yerel kurulumun şifrelerini sunucuya **kopyalama** — sunucu kendi şifrelerini üretmeli.

### 3.4 Başlat
```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml up -d
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml ps
```
İlk açılışta Postgres şemayı otomatik kurar (`docker/initdb/00_roles.sh` → `db/migrations/001_init.sql` → `docker/initdb/02_grants.sql`).
Caddy birkaç saniye içinde Let's Encrypt sertifikasını alır.

### 3.5 Doğrula
```bash
curl -s https://db.ornekkanal.com/                       # → RSSBot DB gateway
curl -s -o /dev/null -w "%{http_code}\n" https://db.ornekkanal.com/rest/v1/ideas   # → 401 (anahtarsız erişim kapalı ✅)
```
Anahtarlı test (anahtarı komut geçmişine yazmamak için önce değişkene oku):
```bash
read -s KEY   # SUPABASE_SERVICE_KEY'i yapıştır, Enter
curl -s -H "apikey: $KEY" -H "Authorization: Bearer $KEY" "https://db.ornekkanal.com/rest/v1/ideas?limit=1"   # → []
unset KEY
```

---

## 4. Mevcut veriyi PC'den taşıma (varsa)

PC'deki yerel Docker veritabanında veri birikmişse (fikirler, içerikler…):

**PC'de** (proje klasöründe):
```bash
docker compose -f docker/docker-compose.yml exec -T db pg_dump -U postgres --data-only --no-owner --no-privileges postgres > rssbot-veri.sql
```
Dosyayı sunucuya güvenli kopyala (içinde fikirler var — public bir yere koyma):
```bash
scp rssbot-veri.sql kullanici@sunucu:/opt/rssbot/
```
**Sunucuda** (şema zaten kurulu olduğu için sadece veri yüklenir):
```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1 < rssbot-veri.sql
shred -u rssbot-veri.sql   # işi bitince sil
```
PC'de de `rssbot-veri.sql` dosyasını sil.

---

## 5. Gizli değerlerin aktarımı ve nereye girileceği

| Değer | Nerede üretilir | Kim kullanır | Nereye girilir |
|---|---|---|---|
| `POSTGRES_PASSWORD`, `AUTHENTICATOR_PASSWORD`, `JWT_SECRET` | Sunucu (`setup_db.py`) | Sadece sunucu | `docker/.env` — **sunucudan hiç çıkmaz** |
| `SUPABASE_URL` (`https://db…`) | Sunucu | PC, Colab, GitHub Actions | aşağıdaki 3 yer |
| `SUPABASE_SERVICE_KEY` | Sunucu | PC, Colab, GitHub Actions | aşağıdaki 3 yer |

**Aktarım:** `SUPABASE_SERVICE_KEY` şifre gibidir. Tercih sırası:
1. Ortak şifre yöneticisi (Bitwarden/1Password paylaşımı) ✅
2. Tek seferlik/kendini silen not (ör. Bitwarden Send, onetimesecret) ✅
3. Uçtan uca şifreli mesajlaşma (WhatsApp/Signal) — kullanılacaksa **"kaybolan mesaj"** açık olsun, mesaj okunduktan sonra iki taraftan da silinsin ⚠️

**Asla:** repo, issue, PR, commit mesajı, e-posta, ekran görüntüsü.

**Proje sahibinin yapacakları (taşıma sonrası):**
1. **PC** → proje kökündeki `.env`:
   ```
   SUPABASE_URL=https://db.ornekkanal.com
   SUPABASE_SERVICE_KEY=<sunucudan gelen>
   ```
   `config.yaml` → `db.provider: "supabase"` (zaten öyle). Paneli kapatıp `BASLAT.bat` ile tekrar aç.
2. **Colab** → 🔑 Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` güncelle. (Artık tünel gerekmez; adres sabit.)
3. **GitHub** → *Settings → Secrets and variables → Actions*: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (+ `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_ALLOWED_USER_ID`, opsiyonel `DEEPSEEK_API_KEY`). Telegram senkronu 15 dk'da bir PC kapalıyken de çalışır.
4. PC'deki yerel Docker veritabanını ve tüneli kapat:
   `docker compose -f docker/docker-compose.yml --profile tunnel down` (veri volume'da kalır; tamamen silmek için `down -v`).

> Sunucuyu kuran kişinin DeepSeek / Telegram / Hugging Face / fal anahtarlarına **ihtiyacı yoktur**. Bunlar sunucuya gitmez.

---

## 6. İşletme

### Yedekleme (önerilen: günlük cron)
```bash
mkdir -p /opt/rssbot-yedek
crontab -e
# her gece 03:30'da sıkıştırılmış yedek, 14 günden eskileri sil:
30 3 * * * cd /opt/rssbot && docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml exec -T db pg_dump -U postgres postgres | gzip > /opt/rssbot-yedek/rssbot-$(date +\%F).sql.gz && find /opt/rssbot-yedek -name '*.sql.gz' -mtime +14 -delete
```
Yedekler hassas veridir; sunucu dışına alınacaksa şifreli depolamaya (ör. restic/borg) gönder.

**Geri yükleme (boş kuruluma):**
```bash
gunzip -c /opt/rssbot-yedek/rssbot-2026-10-09.sql.gz | docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml exec -T db psql -U postgres -d postgres
```

### Güncelleme
```bash
cd /opt/rssbot && git pull
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml pull
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml up -d
```
> **Yeni şema dosyası** (`db/migrations/002_*.sql` …) gelirse init betikleri var olan veritabanında tekrar ÇALIŞMAZ; elle uygula:
> `docker compose … exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1 < db/migrations/002_xxx.sql`
> ardından `docker/initdb/02_grants.sql`'i de tekrar çalıştır (yeni tablolara yetki için).

### Loglar ve durum
```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.server.yml logs -f --tail=100 gateway rest db
```

### Anahtar yenileme (anahtar sızdıysa HEMEN)
1. Sunucuda `docker/.env` içindeki `JWT_SECRET` satırını sil → `python3 docker/setup_db.py --server db.ornekkanal.com` (yeni sır + yeni anahtar üretir).
2. `docker compose … up -d --force-recreate rest`
3. Eski anahtar artık geçersiz. Yeni `SUPABASE_SERVICE_KEY`'i Bölüm 5'teki 3 yere gir.

Postgres şifrelerini değiştirmek gerekirse:
```bash
docker compose … exec db psql -U postgres -c "alter role authenticator password 'YENI_SIFRE';"
# docker/.env → AUTHENTICATOR_PASSWORD=YENI_SIFRE, sonra:
docker compose … up -d --force-recreate rest
```

---

## 7. Sorun giderme

| Belirti | Sebep / Çözüm |
|---|---|
| Caddy sertifika alamıyor (`acme` hataları) | DNS A kaydı bu sunucuyu göstermiyor ya da 80/443 kapalı. `dig +short db.ornekkanal.com` ve `ufw status` kontrol et. Cloudflare proxy (turuncu bulut) açıksa kapat ya da SSL modunu *Full* yap. |
| `required variable SITE_ADDRESS is missing` | `docker/.env` içinde `SITE_ADDRESS=` yok → `setup_db.py --server <alan-adi>` çalıştır. |
| Anahtarla da **401** `JWSInvalidSignature` | Anahtar başka bir `JWT_SECRET` ile imzalanmış (PC'nin anahtarı kullanılıyor olabilir). Sunucuda üretileni kullan. |
| **401** `JWT expired` | 10 yıllık anahtar dolmuş 🙂 → Bölüm 6 "Anahtar yenileme". |
| `permission denied for table …` (anahtarla) | Yeni tabloya yetki verilmemiş → `02_grants.sql`'i elle çalıştır. |
| `rest` sürekli yeniden başlıyor | `docker compose … logs rest` — genelde `AUTHENTICATOR_PASSWORD` uyuşmazlığı (volume eski şifreyle kurulmuş). Şifreyi Bölüm 6'daki gibi eşitle. |
| Uygulama "1000 satır" sınırına takılıyor gibi | Normal: istemci sayfalama yapıyor (`PGRST_DB_MAX_ROWS=1000`). |
| Disk doluyor | `docker system df`; eski yedekleri temizle; `docker image prune`. |

---

## 8. Kontrol listesi (kurulumu bitirmeden önce)

- [ ] `https://db.<alan-adi>/` → `RSSBot DB gateway`
- [ ] Anahtarsız `…/rest/v1/ideas` → **401**
- [ ] Anahtarlı `…/rest/v1/ideas?limit=1` → `[]` ya da veri
- [ ] `docker/.env` izinleri `600`, git'te **izlenmiyor** (`git status` temiz)
- [ ] `ss -tlnp` çıktısında 5432 ve 3000 **dışarı açık değil**
- [ ] Günlük yedek cron'u kurulu, bir yedek dosyası oluştu
- [ ] `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` proje sahibine güvenli yolla iletildi, ekran/geçmiş temizlendi
- [ ] (Varsa) PC verisi taşındı, `rssbot-veri.sql` her iki tarafta silindi

---

## 9. Repo erişimi hakkında (proje sahibi için)

- Sunucuya kurulum için arkadaşına **yazma yetkisi gerekmez**: repo public, `git clone` yeterli. Kod değişikliği yapacaksa
  *Settings → Collaborators* ile **Write** ver; **Admin verme** (Secrets'ı yönetebilir, repoyu silebilir).
- `main` dalını koru: *Settings → Branches → Add rule → main* → "Require a pull request before merging".
  Colab kodu `main`'den çektiği için `main`'e giren her kod, Colab'daki `SUPABASE_SERVICE_KEY` ile çalışır.
- GitHub Secrets'ı collaborator **göremez** ama Actions workflow'unu değiştirebilen biri teorik olarak okuyabilir —
  yalnızca güvendiğin kişilere Write ver.
