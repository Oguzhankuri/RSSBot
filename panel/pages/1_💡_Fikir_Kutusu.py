"""💡 Fikir Kutusu — aklına geleni yaz, kaybolmasın. Telegram'dan yazdıkların da burada."""

from __future__ import annotations

import streamlit as st
from common import boot, chat_client

from bulten import ideas, telegram_sync
from bulten.db import RepoError

cfg, repo = boot("Fikir Kutusu", "💡")
st.title("💡 Fikir Kutusu")


def pull_telegram(show: bool) -> None:
    try:
        api, owner = telegram_sync.from_config(cfg)
        count = telegram_sync.sync(repo, api, owner, chat_client(cfg))
        if show:
            st.toast(f"Telegram: {count} yeni mesaj işlendi.", icon="📨")
    except (telegram_sync.TelegramError, RepoError) as exc:
        if show:
            st.warning(f"Telegram senkronu yapılamadı: {exc}")


if cfg["env"].get("TELEGRAM_BOT_TOKEN") and "tg_synced" not in st.session_state:
    pull_telegram(show=False)
    st.session_state["tg_synced"] = True

with st.form("new_idea", clear_on_submit=True):
    text = st.text_area("Yeni fikir", placeholder="Örn: Kuşların V şeklinde uçmasının nedeni → dikey Short olur", height=90)
    c1, c2 = st.columns([1, 3])
    priority = c1.select_slider("Öncelik", options=[1, 2, 3, 4, 5], value=3)
    if c2.form_submit_button("💾 Kaydet", type="primary", use_container_width=True):
        try:
            idea = ideas.add_idea(repo, text, "panel", priority, chat_client(cfg))
            st.success(f"Kaydedildi [{ideas.short_id(idea)}] {idea.get('category') or ''}")
        except ideas.IdeaError as exc:
            st.error(str(exc))

top = st.columns([3, 1])
status = top[0].radio("Göster", ideas.STATUSES, horizontal=True,
                      format_func={"yeni": "🆕 Açık", "kullanildi": "✅ Kullanıldı", "arsiv": "🗄️ Arşiv"}.get)
if top[1].button("📨 Telegram'ı çek", use_container_width=True):
    pull_telegram(show=True)

rows = ideas.list_ideas(repo, status)
st.caption(f"{len(rows)} fikir")
for idea in rows:
    meta = " · ".join(x for x in [
        f"⭐{idea.get('priority', 3)}",
        "📱" if idea.get("source") == "telegram" else "💻",
        idea.get("category") or "",
        f"→ {idea['suggested_format']}" if idea.get("suggested_format") else "",
        (idea.get("created_at") or "")[:10],
    ] if x)
    with st.expander(f"{idea['text'][:90]}  —  {meta}"):
        new_text = st.text_area("Metin", idea["text"], key=f"t-{idea['id']}")
        cols = st.columns(4)
        new_priority = cols[0].number_input("Öncelik", 1, 5, int(idea.get("priority", 3)), key=f"p-{idea['id']}")
        new_status = cols[1].selectbox("Durum", ideas.STATUSES, ideas.STATUSES.index(idea.get("status", "yeni")),
                                       key=f"s-{idea['id']}")
        if cols[2].button("Güncelle", key=f"u-{idea['id']}", use_container_width=True):
            try:
                ideas.edit_text(repo, idea["id"], new_text)
                ideas.set_priority(repo, idea["id"], int(new_priority))
                ideas.set_status(repo, idea["id"], new_status)
                st.rerun()
            except ideas.IdeaError as exc:
                st.error(str(exc))
        if idea.get("tags"):
            st.caption("Etiketler: " + ", ".join(idea["tags"]))
        if idea.get("used_in"):
            st.caption(f"{len(idea['used_in'])} içerikte kullanıldı.")
