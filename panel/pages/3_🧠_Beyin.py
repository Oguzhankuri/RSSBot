"""🧠 Beyin — öğrenilmiş kurallar, performans tablosu, öğrenme ve YouTube senkronu."""

from __future__ import annotations

import streamlit as st
from common import boot, chat_client

from bulten import youtube
from bulten.brain import memory, reflect
from bulten.utils import today_str

cfg, repo = boot("Beyin", "🧠")
st.title("🧠 Beyin")
st.caption(
    "Model fine-tune edilmez: performans verilerinden kurallar çıkarılır ve her yeni senaryo prompt'una eklenir. "
    "Onayladığın kurallar kalıcıdır."
)

a, b = st.columns(2)
if a.button("📊 YouTube metriklerini çek", use_container_width=True):
    try:
        source = youtube.YouTubeAnalytics.from_token(cfg["youtube"]["token_path"])
        st.success(f"{youtube.sync_metrics(repo, source, today_str())} içeriğin metrikleri güncellendi.")
    except youtube.YouTubeError as exc:
        st.error(str(exc))
if b.button("🧠 Öğren (kuralları güncelle)", type="primary", use_container_width=True):
    client = chat_client(cfg)
    if client is None:
        st.error(".env içinde DEEPSEEK_API_KEY yok.")
    else:
        with st.spinner("Beyin geçmişi inceliyor…"):
            result = reflect.reflect(repo, client)
        st.info(result["summary"])

st.subheader("Öğrenilmiş kurallar")
with st.form("manual_rule", clear_on_submit=True):
    c1, c2, c3 = st.columns([4, 1, 1])
    text = c1.text_input("Kendi kuralını ekle", placeholder="Örn: Dikey videolarda ilk cümlede rakam kullan.")
    fmt = c2.selectbox("Format", ["hepsi", "yatay", "dikey"])
    if c3.form_submit_button("Ekle", use_container_width=True) and text.strip():
        reflect.add_manual_rule(repo, text, None if fmt == "hepsi" else fmt)
        st.rerun()

rules = sorted(repo.select("insights"), key=lambda r: (not r.get("active"), not r.get("approved"), -float(r.get("confidence") or 0)))
for rule in rules:
    status = "✅ onaylı" if rule.get("approved") else ("🟢 aktif" if rule.get("active") else "⚪ pasif")
    cols = st.columns([6, 1, 1, 1])
    cols[0].markdown(f"**{rule['rule']}**  \n{status} · {rule.get('format') or 'tüm formatlar'} · "
                     f"güven %{float(rule.get('confidence') or 0) * 100:.0f} · kanıt {rule.get('evidence', 0)}")
    if not rule.get("approved") and cols[1].button("Onayla", key=f"a-{rule['id']}"):
        repo.update("insights", rule["id"], {"approved": True, "active": True})
        st.rerun()
    toggle = "Kapat" if rule.get("active") else "Aç"
    if cols[2].button(toggle, key=f"t-{rule['id']}"):
        repo.update("insights", rule["id"], {"active": not rule.get("active")})
        st.rerun()
    if cols[3].button("Sil", key=f"d-{rule['id']}"):
        repo.delete("insights", rule["id"])
        st.rerun()
if not rules:
    st.caption("Henüz kural yok. İçeriklere puan ver / YouTube linki ekle, sonra 'Öğren'e bas.")

st.subheader("Performans sıralaması")
table = memory.performance_table(repo)
if table:
    st.dataframe(
        [{"format": r["content"]["format"], "başlık": r["content"]["title"], "izlenme": r["views"],
          "izlenme %": r["avg_view_pct"], "puan": r["rating"], "skor": r["score"]} for r in table],
        use_container_width=True, hide_index=True,
    )
else:
    st.caption("Henüz ölçülmüş içerik yok.")
