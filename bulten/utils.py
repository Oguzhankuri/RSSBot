"""Ortak yardımcılar: slug, tarih, dosya G/Ç, logging, dil adları."""

from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TR_CHAR_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c",
        "ğ": "g", "Ğ": "g",
        "ı": "i", "I": "i", "İ": "i",
        "ö": "o", "Ö": "o",
        "ş": "s", "Ş": "s",
        "ü": "u", "Ü": "u",
    }
)

# ISO kodu -> (İngilizce ad, Türkçe ad)
LANGUAGE_NAMES: dict[str, tuple[str, str]] = {
    "tr": ("Turkish", "Türkçe"),
    "en": ("English", "İngilizce"),
    "de": ("German", "Almanca"),
    "ar": ("Arabic", "Arapça"),
    "ru": ("Russian", "Rusça"),
    "fr": ("French", "Fransızca"),
    "es": ("Spanish", "İspanyolca"),
    "it": ("Italian", "İtalyanca"),
    "pt": ("Portuguese", "Portekizce"),
    "nl": ("Dutch", "Felemenkçe"),
    "pl": ("Polish", "Lehçe"),
    "sv": ("Swedish", "İsveççe"),
    "da": ("Danish", "Danca"),
    "fi": ("Finnish", "Fince"),
    "no": ("Norwegian", "Norveççe"),
    "el": ("Greek", "Yunanca"),
    "he": ("Hebrew", "İbranice"),
    "hi": ("Hindi", "Hintçe"),
    "ja": ("Japanese", "Japonca"),
    "ko": ("Korean", "Korece"),
    "zh": ("Chinese", "Çince"),
    "ms": ("Malay", "Malayca"),
    "sw": ("Swahili", "Svahili"),
}

LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"


def slugify_tr(text: str, max_len: int = 50) -> str:
    """Türkçe karakterleri sadeleştirip URL/klasör güvenli slug üretir."""
    simplified = text.translate(TR_CHAR_MAP)
    normalized = unicodedata.normalize("NFKD", simplified)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "haber"


def today_str(tz: str = "Europe/Istanbul") -> str:
    """Verilen saat diliminde bugünün tarihini YYYY-MM-DD döndürür."""
    return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")


def ensure_dir(path: str | Path) -> Path:
    """Klasörü (ebeveynleriyle) oluşturur; varsa dokunmaz."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def setup_logging(level: int = logging.INFO) -> None:
    """Uygulama genelinde zaman + modül + mesaj formatlı logging kurar."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows konsolunda Türkçe karakter
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt="%H:%M:%S", force=True)


def write_text(path: str | Path, content: str) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(content, encoding="utf-8")
    return p


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Any) -> Path:
    return write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def language_name(code: str, lang: str = "en") -> str:
    """ISO kodunu okunur dil adına çevirir (lang='en' İngilizce, 'tr' Türkçe ad)."""
    names = LANGUAGE_NAMES.get(code.lower())
    if names is None:
        return code
    return names[0] if lang == "en" else names[1]
