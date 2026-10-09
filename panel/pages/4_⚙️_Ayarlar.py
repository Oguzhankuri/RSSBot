"""⚙️ Ayarlar — formülleri (dikey/yatay prompt şablonları) düzenle, bağlantıları kontrol et."""

from __future__ import annotations

import time

import common
import env_editor
import streamlit as st
import yaml
from common import boot, reload_config

from bulten import dbstack, formats
from bulten import panel_support as ps

cfg, repo = boot("Ayarlar", "⚙️")
st.title("⚙️ Ayarlar")

st.subheader("Bağlantılar")
env = cfg["env"]
checks = {
    "DeepSeek (senaryo)": bool(env.get("DEEPSEEK_API_KEY")),
    f"Veritabanı ({cfg['db']['provider']})": True,
    "Telegram botu": bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_ALLOWED_USER_ID")),
    f"Hugging Face (görseller: {cfg['images']['provider']})": bool(env.get("HF_TOKEN")) or cfg["images"]["provider"] == "flux_local",
}
for name, ok in checks.items():
    st.markdown(f"{'✅' if ok else '❌'} {name}")
st.markdown(f"🔗 Colab: {ps.colab_url(cfg)}")
st.markdown(f"📁 Çıktı klasörü: `{cfg['output']['base_dir']}`")
if cfg["db"]["provider"] == "sqlite":
    st.warning("Veritabanı yerel (SQLite). Telegram ve Colab'ın aynı veriyi görmesi için Supabase'e geç (README).")

env_editor.render_keys(common.ENV_PATH, on_saved=reload_config)
env_editor.render_password(common.ENV_PATH)

if ps.uses_local_db(cfg):
    st.subheader("🌐 Colab tüneli")
    st.caption(
        "Veritabanı bu bilgisayarda (Docker). Colab'ın ulaşması için tünel açılır; adres her açılışta değişir. "
        "Aşağıdaki adresi Colab → 🔑 Secrets → SUPABASE_URL olarak yapıştır."
    )
    if st.toggle("SUPABASE_SERVICE_KEY'i göster (Colab Secrets'a yapıştırmak için)"):
        st.caption("Bu anahtar şifre gibidir: yalnızca Colab Secrets'a yapıştır, kimseyle paylaşma.")
        st.code(env.get("SUPABASE_SERVICE_KEY") or "", language=None)
    url = dbstack.tunnel_url()
    if url:
        st.code(url, language=None)
        if st.button("⏹️ Tüneli kapat"):
            try:
                dbstack.stop_tunnel()
                st.rerun()
            except dbstack.StackError as exc:
                st.error(str(exc))
    elif st.button("▶️ Tüneli aç", type="primary"):
        try:
            with st.spinner("Tünel açılıyor…"):
                dbstack.start_tunnel()
                for _ in range(15):
                    time.sleep(2)
                    if dbstack.tunnel_url():
                        break
            st.rerun()
        except dbstack.StackError as exc:
            st.error(str(exc))

st.subheader("Formüller")
st.caption("Her format bir YAML dosyası. {{title}}, {{text}}, {{target_words}}, {{tone}}, {{image_count}}, {{guidance}} alanları otomatik doldurulur.")
name = st.radio("Format", formats.available_formats(), horizontal=True)
path = formats.FORMATS_DIR / f"{name}.yaml"
content = st.text_area("YAML", path.read_text(encoding="utf-8"), height=500, key=f"yaml-{name}")
if st.button("💾 Formülü kaydet", type="primary"):
    try:
        data = yaml.safe_load(content)
        missing = [k for k in formats.REQUIRED_KEYS if k not in (data or {})]
        if missing:
            raise ValueError(f"Eksik alanlar: {missing}")
        path.write_text(content, encoding="utf-8")
        reload_config()
        st.success("Kaydedildi. Bir sonraki üretimde kullanılacak.")
    except (yaml.YAMLError, ValueError) as exc:
        st.error(f"Kaydedilmedi: {exc}")
