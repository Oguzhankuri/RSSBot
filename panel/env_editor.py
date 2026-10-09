"""Ayarlar sayfası: .env anahtarlarını ve panel şifresini arayüzden güncelleme."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from bulten import auth, envfile


def render_keys(env_path: Path, on_saved) -> None:
    st.subheader("🔑 Anahtarlar")
    st.caption(
        "Kayıtlı değerler asla tam gösterilmez. Değiştirmek istediğin alana yeni değeri yaz; "
        "boş bıraktığın alanlar olduğu gibi kalır. Kaydedince hemen geçerli olur."
    )
    current = envfile.read(env_path)
    with st.form("env_keys", clear_on_submit=True):
        changes: dict[str, str | None] = {}
        basic = [s for s in envfile.SETTINGS if not s.advanced]
        advanced = [s for s in envfile.SETTINGS if s.advanced]
        for setting in basic:
            changes.update(_field(setting, current))
        with st.expander("Gelişmiş: veritabanı bağlantısı"):
            st.warning("Bunları yanlış girersen panel veritabanına bağlanamaz; o zaman .env'i elle düzeltmen gerekir.")
            for setting in advanced:
                changes.update(_field(setting, current))
        submitted = st.form_submit_button("💾 Kaydet", type="primary")
    if not submitted:
        return
    if not changes:
        st.info("Değişiklik yok.")
        return
    try:
        saved = envfile.update(env_path, changes)
    except envfile.EnvError as exc:
        st.error(f"Kaydedilmedi: {exc}")
        return
    on_saved()
    st.success("Güncellendi: " + ", ".join(saved))


def _field(setting: envfile.Setting, current: dict[str, str]) -> dict[str, str | None]:
    value = current.get(setting.key, "")
    status = f"✅ ayarlı ({envfile.mask(value)})" if value else "❌ boş"
    col_input, col_clear = st.columns([4, 1])
    new = col_input.text_input(
        f"{setting.label} — {status}", type="password", key=f"env-{setting.key}", help=setting.help,
        placeholder="değiştirmek için yeni değeri yaz",
    )
    clear = col_clear.checkbox("Sil", key=f"envdel-{setting.key}", disabled=not value)
    if clear:
        return {setting.key: None}
    return {setting.key: new} if new.strip() else {}


def render_password(env_path: Path) -> None:
    st.subheader("🔒 Panel şifresi")
    has_password = bool(os.getenv("PANEL_PASSWORD_HASH"))
    if not has_password:
        st.caption("Şu an şifre yok (panel yalnızca bu bilgisayardan açılabiliyor). İstersen burada tanımlayabilirsin.")
    with st.form("change_password", clear_on_submit=True):
        current = st.text_input("Mevcut şifre", type="password", disabled=not has_password)
        new = st.text_input(f"Yeni şifre (en az {auth.MIN_PASSWORD_LEN} karakter)", type="password")
        repeat = st.text_input("Yeni şifre (tekrar)", type="password")
        submitted = st.form_submit_button("Şifreyi değiştir")
    if not submitted:
        return
    wait = auth.THROTTLE.wait_seconds()
    if wait > 0:
        st.warning(f"Çok fazla hatalı deneme. {wait} sn sonra tekrar dene.")
        return
    try:
        auth.change_password(env_path, current, new, repeat)
    except auth.PasswordError as exc:
        st.error(str(exc))
        return
    st.session_state["authed"] = True  # bu oturum açık kalsın
    st.success("Şifre değişti. Diğer cihazlardaki oturumlar kapandı.")
