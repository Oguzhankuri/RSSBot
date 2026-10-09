""".env dosyasını panelden güvenle güncellemek için yardımcılar.

- Yalnızca SETTINGS listesindeki anahtarlar düzenlenebilir (şifre özeti vb. hariç).
- Değerler doğrulanır; satır sonu içeren değer reddedilir (.env'e sahte satır eklenemez).
- Yazım atomiktir (geçici dosya + yer değiştirme) ve dosya izinleri korunur.
- Mevcut değerler arayüzde asla tam gösterilmez: mask() yalnızca son 4 karakteri verir.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
MAX_VALUE_LEN = 4096


class EnvError(ValueError):
    pass


def _not_empty(value: str) -> None:
    if not value:
        raise EnvError("Boş olamaz.")


def _id_list(value: str) -> None:
    parts = [p for p in re.split(r"[,\s;]+", value) if p]
    if not parts or not all(re.fullmatch(r"-?\d{3,20}", p) for p in parts):
        raise EnvError("Sadece rakamlar; ekip için virgülle ayır (ör. 111111111,222222222).")


def _telegram_token(value: str) -> None:
    if not re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{20,}", value):
        raise EnvError("Telegram bot token biçimi: 123456789:AA... (@BotFather'dan)")


def _url(value: str) -> None:
    if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?/?", value):
        raise EnvError("Adres biçimi: https://alan-adi (yol olmadan)")


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    help: str
    validate: Callable[[str], None] = _not_empty
    advanced: bool = False


SETTINGS: tuple[Setting, ...] = (
    Setting("DEEPSEEK_API_KEY", "DeepSeek API anahtarı", "Senaryo ve çeviri. platform.deepseek.com → API Keys"),
    Setting("TELEGRAM_BOT_TOKEN", "Telegram bot token", "@BotFather → /newbot", _telegram_token),
    Setting("TELEGRAM_ALLOWED_USER_ID", "Telegram kullanıcı kimlikleri (sen + ekip)",
            "Her kişi @userinfobot'a yazıp sayısını versin; virgülle ayır: 111111111,222222222. "
            "Bu listede olmayanların mesajları yok sayılır.", _id_list),
    Setting("HF_TOKEN", "Hugging Face token", "Görseller: FLUX lisansı onaylı hesabın 'Read' token'ı (images.provider=hf_api ya da yerel FLUX)"),
    Setting("SUPABASE_URL", "Veritabanı adresi", "Yanlış girilirse panel veritabanına bağlanamaz!", _url, advanced=True),
    Setting("SUPABASE_SERVICE_KEY", "Veritabanı anahtarı", "Yanlış girilirse panel veritabanına bağlanamaz!", advanced=True),
)
EDITABLE = {s.key: s for s in SETTINGS}


def read(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def mask(value: str | None) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"


def clean(key: str, value: str) -> str:
    """Değeri doğrular ve temizlenmiş halini döndürür; geçersizse EnvError."""
    if key not in EDITABLE:
        raise EnvError(f"{key} panelden düzenlenemez.")
    if "\n" in value or "\r" in value or "\x00" in value:
        raise EnvError("Değer satır sonu içeremez.")
    value = value.strip()
    if len(value) > MAX_VALUE_LEN:
        raise EnvError("Değer çok uzun.")
    EDITABLE[key].validate(value)
    return value


def write_atomic(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def update(path: Path, changes: dict[str, str | None], allow: set[str] | None = None) -> list[str]:
    """changes: anahtar → yeni değer (None = sil). Diğer satırlar/yorumlar korunur. Değişen anahtarları döndürür.

    allow: panel dışı kullanım (şifre özeti gibi) için ek izinli anahtarlar; değerleri ayrıca doğrulanmaz.
    """
    extra = allow or set()
    cleaned: dict[str, str | None] = {}
    for key, value in changes.items():
        if not KEY_RE.match(key):
            raise EnvError(f"Geçersiz anahtar adı: {key!r}")
        if key in extra:
            if value is not None and ("\n" in value or "\r" in value):
                raise EnvError("Değer satır sonu içeremez.")
            cleaned[key] = value
        else:
            cleaned[key] = None if value is None else clean(key, value)

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in cleaned and "=" in line and not line.lstrip().startswith("#"):
            done.add(key)
            if cleaned[key] is not None:
                out.append(f"{key}={cleaned[key]}")
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in cleaned.items() if k not in done and v is not None]
    write_atomic(path, "\n".join(out) + "\n")

    # Çalışan süreç (ve başlatacağı pipeline alt süreçleri) yeni değeri hemen görsün.
    for key, value in cleaned.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    logger.info(".env güncellendi: %s", ", ".join(sorted(cleaned)))  # yalnızca anahtar adları
    return sorted(cleaned)
