"""DeepSeek ile ham haber → Türkçe YouTube bülten senaryosu (JSON)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bulten.llm import DeepSeekClient

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 8000
RETRY_TEMPERATURE = 0.3
IMAGE_PROMPT_COUNT = 3

SYSTEM_PROMPT = """Sen profesyonel bir Türkçe haber editörüsün. Verilen ham haberi, bir YouTube günlük haber bülteninde SESLENDİRİLECEK; akıcı, net, tarafsız, kısa cümleli bir anlatım senaryosuna dönüştürürsün. Abartı, yorum ve taraf tutma yok.

Anlatım tonu: {tone}.

Görsel promptu kuralları (ZORUNLU):
- "gorsel_promptleri" tam 3 adet ve İNGİLİZCE olmalı.
- Gerçekçi, jenerik, simgesel haber illüstrasyonu sahneleri tarif et.
- Gerçek veya tanınabilir kişi yüzü, ünlü, siyasetçi, logo, marka adı/ambalajı, telifli karakter ve görsel içinde okunaklı metin/yazı/tabela İÇERMEYECEK.
- Kişi gerekiyorsa yüzü görünmeyen, anonim siluetler kullan.

Yanıtı YALNIZCA geçerli JSON nesnesi olarak ver."""

USER_TEMPLATE = """Ham haber:
BAŞLIK: {title}
METİN: {text}

Şu JSON'u üret:
{{
  "baslik": "video içi kısa başlık (en fazla 70 karakter)",
  "senaryo": "yaklaşık {target_words} kelimelik Türkçe seslendirme metni",
  "ozet": "tek cümle özet",
  "gorsel_promptleri": ["English prompt 1", "English prompt 2", "English prompt 3"],
  "etiketler": ["3-5 Türkçe etiket"]
}}"""

FALLBACK_IMAGE_PROMPTS = [
    "a modern newsroom with glowing screens, no people, cinematic light",
    "an abstract world map with soft light connections, news theme",
    "a city skyline at dusk seen from above, documentary style",
]


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def _normalize(data: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    prompts = [str(p).strip() for p in data.get("gorsel_promptleri") or [] if str(p).strip()]
    prompts = (prompts + FALLBACK_IMAGE_PROMPTS)[:IMAGE_PROMPT_COUNT]
    tags = [str(t).strip() for t in data.get("etiketler") or [] if str(t).strip()][:5]
    title = str(data.get("baslik") or item["title"]).strip()[:70]
    script = str(data.get("senaryo") or "").strip()
    if not script:
        raise ValueError("senaryo alanı boş")
    return {
        "baslik": title,
        "senaryo": script,
        "ozet": str(data.get("ozet") or "").strip(),
        "gorsel_promptleri": prompts,
        "etiketler": tags,
    }


def fallback_script(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "baslik": item["title"][:70],
        "senaryo": item.get("summary") or item["text"][:800],
        "ozet": item["title"],
        "gorsel_promptleri": list(FALLBACK_IMAGE_PROMPTS),
        "etiketler": [],
        "uyari": "DeepSeek geçerli JSON üretemedi; özet senaryo olarak kullanıldı.",
    }


def rewrite_item(item: dict[str, Any], cfg: dict[str, Any], client: DeepSeekClient) -> dict[str, Any]:
    rcfg = cfg["rewrite"]
    system = SYSTEM_PROMPT.format(tone=rcfg.get("tone", "net, tarafsız"))
    user = USER_TEMPLATE.format(
        title=item["title"],
        text=item["text"][:MAX_SOURCE_CHARS],
        target_words=rcfg.get("target_words", 110),
    )
    for temperature in (0.7, RETRY_TEMPERATURE):
        raw = client.chat(system, user, temperature=temperature, json_mode=True)
        try:
            return _normalize(json.loads(_clean_json_text(raw)), item)
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("JSON çözümlenemedi (sıcaklık %.1f): %s", temperature, exc)
    logger.warning("Yedek senaryo kullanılıyor: %s", item["title"])
    return fallback_script(item)
