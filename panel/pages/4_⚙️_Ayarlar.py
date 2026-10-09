"""⚙️ Ayarlar — formülleri (dikey/yatay prompt şablonları) düzenle, bağlantıları kontrol et."""

from __future__ import annotations

import streamlit as st
import yaml
from common import boot, reload_config

from bulten import formats
from bulten import panel_support as ps

cfg, repo = boot("Ayarlar", "⚙️")
st.title("⚙️ Ayarlar")

st.subheader("Bağlantılar")
env = cfg["env"]
checks = {
    "DeepSeek (senaryo)": bool(env.get("DEEPSEEK_API_KEY")),
    f"Veritabanı ({cfg['db']['provider']})": True,
    "Telegram botu": bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_ALLOWED_USER_ID")),
    "fal.ai (opsiyonel)": bool(env.get("FAL_KEY")),
}
for name, ok in checks.items():
    st.markdown(f"{'✅' if ok else '❌'} {name}")
st.markdown(f"🔗 Colab: {ps.colab_url(cfg)}")
st.markdown(f"📁 Çıktı klasörü: `{cfg['output']['base_dir']}`")
if cfg["db"]["provider"] == "sqlite":
    st.warning("Veritabanı yerel (SQLite). Telegram ve Colab'ın aynı veriyi görmesi için Supabase'e geç (README).")

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
