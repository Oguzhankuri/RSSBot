"""DeepSeek ile ham haber → formata özel Türkçe senaryo (JSON).

Prompt şablonları bulten/formats/<format>.yaml içindedir (yatay, dikey…).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bulten import formats
from bulten.llm import DeepSeekClient

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 8000
RETRY_TEMPERATURE = 0.3
MAX_TITLE_CHARS = 70
MAX_TAGS = 6

FALLBACK_IMAGE_PROMPTS = [
    "a modern newsroom with glowing screens, no people, cinematic light",
    "an abstract world map with soft light connections, news theme",
    "a city skyline at dusk seen from above, documentary style",
    "a quiet street at night with soft reflections, documentary style",
    "an abstract data visualization glowing in the dark, news theme",
]


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def _clean_list(values: Any) -> list[str]:
    return [str(v).strip() for v in values or [] if str(v).strip()]


def _screen_texts(values: Any) -> list[dict[str, Any]]:
    """[{"saniye": 0, "metin": "..."}] biçimini garanti eder; bozuk öğeleri atar."""
    cleaned = []
    for entry in values or []:
        if not isinstance(entry, dict) or not str(entry.get("metin") or "").strip():
            continue
        try:
            second = max(0, int(float(entry.get("saniye", 0))))
        except (TypeError, ValueError):
            second = 0
        cleaned.append({"saniye": second, "metin": str(entry["metin"]).strip()})
    return sorted(cleaned, key=lambda e: e["saniye"])


def _extras(data: dict[str, Any], profile: formats.Profile) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for field in profile.get("extra_fields") or []:
        value = data.get(field)
        if field == "ekran_yazilari":
            extras[field] = _screen_texts(value)
        elif isinstance(value, list):
            extras[field] = _clean_list(value)
        else:
            extras[field] = str(value or "").strip()
    return extras


def _image_count(profile: formats.Profile) -> int:
    return int(profile["images"].get("count") or 3)


def _normalize(data: dict[str, Any], item: dict[str, Any], profile: formats.Profile) -> dict[str, Any]:
    count = _image_count(profile)
    prompts = (_clean_list(data.get("gorsel_promptleri")) + FALLBACK_IMAGE_PROMPTS)[:count]
    script = str(data.get("senaryo") or "").strip()
    if not script:
        raise ValueError("senaryo alanı boş")
    return {
        "baslik": str(data.get("baslik") or item["title"]).strip()[:MAX_TITLE_CHARS],
        "senaryo": script,
        "ozet": str(data.get("ozet") or "").strip(),
        "gorsel_promptleri": prompts,
        "etiketler": _clean_list(data.get("etiketler"))[:MAX_TAGS],
        **_extras(data, profile),
    }


def fallback_script(item: dict[str, Any], profile: formats.Profile | None = None) -> dict[str, Any]:
    profile = profile or formats.load_profile("yatay")
    base = {
        "baslik": item["title"][:MAX_TITLE_CHARS],
        "senaryo": item.get("summary") or item["text"][:800],
        "ozet": item["title"],
        "gorsel_promptleri": FALLBACK_IMAGE_PROMPTS[: _image_count(profile)],
        "etiketler": [],
        "uyari": "DeepSeek geçerli JSON üretemedi; özet senaryo olarak kullanıldı.",
    }
    return {**base, **_extras({}, profile)}


def build_prompts(
    item: dict[str, Any], cfg: dict[str, Any], profile: formats.Profile, guidance: str = ""
) -> tuple[str, str]:
    system = formats.render(
        profile["system_prompt"],
        tone=cfg["rewrite"].get("tone", "net, tarafsız"),
        image_count=_image_count(profile),
        guidance=guidance.strip(),
    )
    user = formats.render(
        profile["user_template"],
        title=item["title"],
        text=item["text"][:MAX_SOURCE_CHARS],
        target_words=formats.target_words(profile, cfg),
    )
    return system, user


def rewrite_item(
    item: dict[str, Any],
    cfg: dict[str, Any],
    client: DeepSeekClient,
    profile: formats.Profile | None = None,
    guidance: str = "",
) -> dict[str, Any]:
    profile = profile or formats.load_profile("yatay", cfg)
    system, user = build_prompts(item, cfg, profile, guidance)
    for temperature in (0.7, RETRY_TEMPERATURE):
        raw = client.chat(system, user, temperature=temperature, json_mode=True)
        try:
            return _normalize(json.loads(_clean_json_text(raw)), item, profile)
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("JSON çözümlenemedi (sıcaklık %.1f): %s", temperature, exc)
    logger.warning("Yedek senaryo kullanılıyor: %s", item["title"])
    return fallback_script(item, profile)
