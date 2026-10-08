"""DeepSeek ile Türkçe senaryo → hedef diller."""

from __future__ import annotations

import logging
from typing import Any

from bulten.llm import DeepSeekClient
from bulten.utils import language_name

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sen uzman bir çevirmensin. Verilen Türkçe bülten senaryosunu, SESLENDİRMEYE uygun, "
    "doğal ve akıcı {lang_tr} ({lang_en}) diline çevir. Anlamı ve haber tonunu koru. "
    "Sadece çeviriyi döndür, açıklama yapma."
)
TRANSLATE_TEMPERATURE = 0.3


def translate_text(text: str, lang: str, cfg: dict[str, Any], client: DeepSeekClient) -> str:
    system = SYSTEM_PROMPT.format(lang_tr=language_name(lang, "tr"), lang_en=language_name(lang, "en"))
    result = client.chat(system, text, temperature=TRANSLATE_TEMPERATURE)
    if not result:
        raise ValueError(f"{lang} çevirisi boş döndü")
    return result


def translate_all(text: str, cfg: dict[str, Any], client: DeepSeekClient) -> tuple[dict[str, str], dict[str, str]]:
    """Tüm hedef dillere çevirir. (başarılı çeviriler, dil→hata mesajı) döndürür."""
    tcfg = cfg["translate"]
    if not tcfg.get("enabled", True):
        return {}, {}
    translations: dict[str, str] = {}
    errors: dict[str, str] = {}
    for lang in tcfg.get("languages", []):
        try:
            translations[lang] = translate_text(text, lang, cfg, client)
            logger.info("  çeviri hazır: %s", lang)
        except Exception as exc:  # noqa: BLE001 — tek dil hatası diğerlerini durdurmamalı
            logger.error("  çeviri başarısız (%s): %s", lang, exc)
            errors[lang] = str(exc)
    return translations, errors
