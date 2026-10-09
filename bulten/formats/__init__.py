"""Video formatı profilleri (yatay 16:9 bülten, dikey 9:16 Shorts).

Her profil bir YAML dosyasıdır: prompt şablonları, görsel boyutları, haber sayısı.
config.yaml → formats.overrides.<ad> ile tek tek alanlar ezilebilir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from bulten.config import ConfigError

FORMATS_DIR = Path(__file__).resolve().parent
REQUIRED_KEYS = ("name", "label", "max_items", "images", "system_prompt", "user_template")

Profile = dict[str, Any]


def available_formats() -> list[str]:
    return sorted(p.stem for p in FORMATS_DIR.glob("*.yaml"))


def load_profile(name: str, cfg: dict[str, Any] | None = None) -> Profile:
    path = FORMATS_DIR / f"{name}.yaml"
    if not path.exists():
        raise ConfigError(f"Bilinmeyen format: {name!r}. Mevcut: {available_formats()}")
    with path.open(encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    missing = [k for k in REQUIRED_KEYS if k not in base]
    if missing:
        raise ConfigError(f"{path.name} eksik alanlar: {missing}")
    overrides = ((cfg or {}).get("formats") or {}).get("overrides", {}).get(name) or {}
    images = {**base["images"], **(overrides.get("images") or {})}
    return {**base, **overrides, "images": images}


def enabled_profiles(cfg: dict[str, Any]) -> list[Profile]:
    names = (cfg.get("formats") or {}).get("enabled") or ["yatay"]
    return [load_profile(n, cfg) for n in names]


def target_words(profile: Profile, cfg: dict[str, Any]) -> int:
    return int(profile.get("target_words") or cfg["rewrite"].get("target_words", 110))


def image_cfg(profile: Profile, cfg: dict[str, Any]) -> dict[str, Any]:
    """Genel images ayarları + formatın boyut/adet/kompozisyonu birleştirilmiş YENİ sözlük."""
    base = cfg["images"]
    pimg = profile["images"]
    style = ", ".join(s for s in (pimg.get("composition", ""), base.get("style", "")) if s)
    return {
        **base,
        "width": int(pimg.get("width") or base["width"]),
        "height": int(pimg.get("height") or base["height"]),
        "count_per_item": int(pimg.get("count") or base.get("count_per_item", 3)),
        "style": style,
    }


def with_format(cfg: dict[str, Any], profile: Profile) -> dict[str, Any]:
    """Görsel modüllerine verilecek, formata özel yapılandırma kopyası."""
    return {**cfg, "images": image_cfg(profile, cfg)}


def render(template: str, **values: Any) -> str:
    """{{anahtar}} alanlarını doldurur; JSON süslü parantezlerine dokunmaz."""
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out
