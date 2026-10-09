"""config.yaml + .env yükleme ve doğrulama."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from bulten.utils import LANGUAGE_NAMES


class ConfigError(Exception):
    """Yapılandırma eksik veya hatalı olduğunda fırlatılır."""


PLACEHOLDER_FEED_MARKER = "ORNEK-HABER-SITESI"
VALID_IMAGE_PROVIDERS = ("flux_local", "fal")


def get_env(key: str, required: bool = False) -> str | None:
    value = os.getenv(key, "").strip() or None
    if required and value is None:
        raise ConfigError(
            f"'{key}' ortam değişkeni bulunamadı. Proje kökündeki .env dosyasına "
            f"'{key}=...' satırını ekleyin (.env.example dosyasını örnek alın)."
        )
    return value


def load_config(
    path: str | Path = "config.yaml",
    env_path: str | Path | None = None,
    require_text: bool = False,
    require_voice: bool = False,
    require_db: bool = False,
) -> dict[str, Any]:
    """YAML'ı okur, .env'i yükler, doğrular ve birleşik sözlük döndürür."""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Yapılandırma dosyası bulunamadı: {config_path}")

    load_dotenv(env_path or config_path.parent / ".env", override=False)

    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml bir sözlük (anahtar: değer) yapısı olmalı.")

    _validate(raw, require_text=require_text, require_voice=require_voice)
    merged = _with_defaults(raw)
    db_override = get_env("BULTEN_DB_PROVIDER")  # GitHub Actions / Colab her zaman bulut DB kullanır
    if db_override:
        merged = {**merged, "db": {**merged["db"], "provider": db_override}}
    _validate_extras(merged)

    uses_supabase = merged["db"]["provider"] == "supabase"
    env = {
        "DEEPSEEK_API_KEY": get_env("DEEPSEEK_API_KEY", required=require_text),
        "FAL_KEY": get_env(
            "FAL_KEY",
            required=require_text and raw["images"]["provider"] == "fal",
        ),
        "SUPABASE_URL": get_env("SUPABASE_URL", required=require_db and uses_supabase),
        "SUPABASE_SERVICE_KEY": get_env("SUPABASE_SERVICE_KEY", required=require_db and uses_supabase),
        "TELEGRAM_BOT_TOKEN": get_env("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_ALLOWED_USER_ID": get_env("TELEGRAM_ALLOWED_USER_ID"),
    }
    # Colab ile PC'nin output klasörü farklı yolda (Drive) olabilir.
    output_override = get_env("BULTEN_OUTPUT_DIR")
    if output_override:
        merged = {**merged, "output": {**merged["output"], "base_dir": output_override}}
    return {**merged, "env": env}


OPTIONAL_DEFAULTS: dict[str, dict[str, Any]] = {
    "db": {"provider": "sqlite", "sqlite_path": "state/bulten.db"},
    "formats": {"enabled": ["yatay", "dikey"], "overrides": {}},
    "brain": {"enabled": True, "candidate_pool": 30, "repeat_days": 30, "repeat_threshold": 0.8},
    "colab": {"notebook_url": ""},
    "telegram": {"enabled": False},
    "youtube": {
        "client_secret": "secrets/client_secret.json",
        "token_path": "secrets/youtube_token.json",
    },
}
VALID_DB_PROVIDERS = ("sqlite", "supabase")


def _with_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    """Yeni (v2) bölümler config.yaml'da yoksa varsayılanlarla doldurulur; eski dosyalar bozulmaz."""
    extras = {key: {**defaults, **(raw.get(key) or {})} for key, defaults in OPTIONAL_DEFAULTS.items()}
    return {**raw, **extras}


def _validate_extras(cfg: dict[str, Any]) -> None:
    if cfg["db"]["provider"] not in VALID_DB_PROVIDERS:
        raise ConfigError(f"'db.provider' geçersiz: {cfg['db']['provider']!r}. Seçenekler: {VALID_DB_PROVIDERS}")
    enabled = cfg["formats"].get("enabled") or []
    if not isinstance(enabled, list) or not enabled:
        raise ConfigError("'formats.enabled' en az bir format içermeli (yatay, dikey).")


def _validate(cfg: dict[str, Any], require_text: bool, require_voice: bool) -> None:
    for section in ("feeds", "ingest", "rewrite", "translate", "images", "voice", "output"):
        if section not in cfg:
            raise ConfigError(f"config.yaml içinde '{section}' bölümü eksik.")

    feeds = cfg["feeds"]
    if not isinstance(feeds, list) or not [f for f in feeds if str(f or "").strip()]:
        raise ConfigError("config.yaml 'feeds' listesi boş. En az bir RSS adresi yazın.")
    if require_text and any(PLACEHOLDER_FEED_MARKER in str(f) for f in feeds):
        raise ConfigError(
            "config.yaml 'feeds' hâlâ örnek adresi içeriyor. Kendi RSS adresinizi yazın."
        )

    t_langs = [str(x).lower() for x in cfg["translate"].get("languages") or []]
    v_langs = [str(x).lower() for x in cfg["voice"].get("languages") or []]
    if cfg["translate"].get("enabled", True) and not t_langs:
        raise ConfigError("'translate.languages' boş. Hedef dilleri ISO kodu olarak yazın.")
    both_on = cfg["translate"].get("enabled", True) and cfg["voice"].get("enabled", True)
    if both_on and set(t_langs) != set(v_langs):
        raise ConfigError(
            "'translate.languages' ile 'voice.languages' aynı olmalı. "
            f"Şu an: translate={t_langs}, voice={v_langs}. İki listeyi de güncelleyin."
        )
    unknown = sorted(set(t_langs + v_langs) - set(LANGUAGE_NAMES))
    if unknown:
        raise ConfigError(
            f"Desteklenmeyen dil kodu: {unknown}. Geçerli kodlar: {sorted(LANGUAGE_NAMES)}"
        )
    if "tr" in v_langs:
        raise ConfigError("'voice.languages' içine 'tr' yazmayın; Türkçe sesi siz kaydediyorsunuz.")

    provider = cfg["images"].get("provider")
    if provider not in VALID_IMAGE_PROVIDERS:
        raise ConfigError(
            f"'images.provider' geçersiz: {provider!r}. Seçenekler: {VALID_IMAGE_PROVIDERS}"
        )

    if require_voice and not Path(cfg["voice"].get("ref_audio", "")).exists():
        raise ConfigError(
            "Önce kendi sesinizden bir referans kaydı "
            f"'{cfg['voice'].get('ref_audio')}' olarak ekleyin."
        )
