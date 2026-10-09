"""Tüm panel sayfalarının paylaştığı yapılandırma ve veritabanı bağlantısı."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from bulten.config import ConfigError, load_config  # noqa: E402
from bulten.db import RepoError, create_repo  # noqa: E402

CONFIG_PATH = str(ROOT / "config.yaml")


@st.cache_resource(show_spinner=False)
def _load() -> tuple[dict, object]:
    cfg = load_config(CONFIG_PATH, require_db=True)
    return cfg, create_repo(cfg)


def boot(title: str, icon: str) -> tuple[dict, object]:
    """Sayfa başlığını kurar; yapılandırma hatasını kullanıcı dostu gösterip durur."""
    st.set_page_config(page_title=f"{title} · Bülten Stüdyosu", page_icon=icon, layout="wide")
    try:
        return _load()
    except (ConfigError, RepoError) as exc:
        st.error(f"Ayarlar yüklenemedi: {exc}")
        st.info("`.env` ve `config.yaml` dosyalarını kontrol edip sayfayı yenile. Kurulum adımları README'de.")
        st.stop()


def reload_config() -> None:
    _load.clear()


def chat_client(cfg: dict):
    """DeepSeek anahtarı yoksa None (AI özellikleri sessizce devre dışı)."""
    if not cfg["env"].get("DEEPSEEK_API_KEY"):
        return None
    from bulten.llm import DeepSeekClient

    return DeepSeekClient(cfg)
