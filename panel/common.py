"""Tüm panel sayfalarının paylaştığı yapılandırma ve veritabanı bağlantısı."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os  # noqa: E402

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from bulten import auth  # noqa: E402

from bulten.config import ConfigError, load_config  # noqa: E402
from bulten.db import RepoError, create_repo  # noqa: E402

CONFIG_PATH = str(ROOT / "config.yaml")
ENV_PATH = ROOT / ".env"


@st.cache_resource(show_spinner=False)
def _load() -> tuple[dict, object]:
    cfg = load_config(CONFIG_PATH, require_db=True)
    return cfg, create_repo(cfg)


def _set_cookie(value: str, max_age: int) -> None:
    # Bileşen iframe'i aynı kökende çalışır; çerez panelin alan adına yazılır.
    components.html(
        f"<script>document.cookie='{auth.COOKIE_NAME}={value}; Max-Age={max_age}; Path=/; SameSite=Strict"
        + ("; Secure" if os.getenv("BULTEN_PUBLIC") == "1" else "")
        + "';</script>",
        height=0,
    )


def require_login() -> None:
    """PANEL_PASSWORD_HASH tanımlıysa şifre sorar. İnternete açık kurulumda (BULTEN_PUBLIC=1) şifre zorunlu."""
    # Çerez işlemi st.rerun()'dan SONRAKİ çizimde yapılır; aynı çizimde yapılırsa iframe hiç yüklenmez.
    pending = st.session_state.pop("cookie_op", None)
    if pending is not None:
        _set_cookie(*pending)
    stored = os.getenv("PANEL_PASSWORD_HASH", "").strip()
    session_secret = os.getenv("PANEL_SESSION_SECRET", "").strip()
    if not stored:
        if os.getenv("BULTEN_PUBLIC") == "1":
            st.error("Panel internete açık ama şifre tanımlı değil. Sunucuda: python3 -m bulten.auth set-password")
            st.stop()
        return  # yalnızca bu bilgisayardan erişilen yerel panel
    if st.session_state.get("authed"):
        return
    # st.context.cookies sayfa açılışındaki çerezlerdir; çıkış yapılan oturumda bunlara güvenilmez.
    if not st.session_state.get("logged_out") and auth.verify_token(
        st.context.cookies.get(auth.COOKIE_NAME), session_secret, stored
    ):
        st.session_state["authed"] = True
        return

    st.title("🔒 Bülten Stüdyosu")
    wait = auth.THROTTLE.wait_seconds()
    with st.form("login"):
        password = st.text_input("Şifre", type="password")
        submitted = st.form_submit_button("Giriş", type="primary", disabled=wait > 0)
    if wait > 0:
        st.warning(f"Çok fazla hatalı deneme. {wait} sn sonra tekrar dene.")
    elif submitted:
        if auth.verify_password(password, stored):
            auth.THROTTLE.record_success()
            st.session_state["authed"] = True
            st.session_state["logged_out"] = False
            st.session_state["cookie_op"] = (auth.issue_token(session_secret, stored), auth.SESSION_DAYS * 86400)
            st.rerun()
        auth.THROTTLE.record_failure()
        st.error("Şifre yanlış.")
    st.stop()


def logout_button() -> None:
    if os.getenv("PANEL_PASSWORD_HASH") and st.sidebar.button("🚪 Çıkış yap"):
        st.session_state["authed"] = False
        st.session_state["logged_out"] = True
        st.session_state["cookie_op"] = ("", 0)
        st.rerun()


def boot(title: str, icon: str) -> tuple[dict, object]:
    """Sayfa başlığını kurar, girişi denetler; yapılandırma hatasını kullanıcı dostu gösterip durur."""
    st.set_page_config(page_title=f"{title} · Bülten Stüdyosu", page_icon=icon, layout="wide")
    try:
        loaded = _load()  # .env'i de yükler (şifre özeti dahil)
    except (ConfigError, RepoError) as exc:
        require_login()
        st.error(f"Ayarlar yüklenemedi: {exc}")
        st.info("`.env` ve `config.yaml` dosyalarını kontrol edip sayfayı yenile. Kurulum adımları README'de.")
        st.stop()
    require_login()
    logout_button()
    return loaded


def reload_config() -> None:
    _load.clear()


def chat_client(cfg: dict):
    """DeepSeek anahtarı yoksa None (AI özellikleri sessizce devre dışı)."""
    if not cfg["env"].get("DEEPSEEK_API_KEY"):
        return None
    from bulten.llm import DeepSeekClient

    return DeepSeekClient(cfg)
