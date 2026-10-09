"""🎬 İçerikler — üretilen videolar, YouTube linkleri, puanlar ve performans."""

from __future__ import annotations

import streamlit as st
from common import boot

from bulten import organize, youtube
from bulten.brain import memory

cfg, repo = boot("İçerikler", "🎬")
st.title("🎬 İçerikler")

contents = repo.select("contents", order_by="created_at", desc=True, limit=300)
dates = sorted({c["date"] for c in contents}, reverse=True)
f1, f2 = st.columns(2)
day = f1.selectbox("Gün", ["Hepsi", *dates])
fmt = f2.radio("Format", ["Hepsi", "yatay", "dikey"], horizontal=True)
shown = [c for c in contents if (day == "Hepsi" or c["date"] == day) and (fmt == "Hepsi" or c["format"] == fmt)]

scores = {row["content"]["id"]: row for row in memory.performance_table(repo)}
st.caption(f"{len(shown)} içerik")

for c in shown:
    perf = scores.get(c["id"])
    badge = f" · 👁 {perf['views']}" if perf and perf.get("views") is not None else ""
    yt = " · ▶️" if c.get("yt_video_id") else ""
    with st.expander(f"[{c['format']}] {c['title']} — {c['date']}{badge}{yt}"):
        left, right = st.columns([3, 2])
        with left:
            if c.get("hook"):
                st.markdown(f"**Kanca:** {c['hook']}")
            st.write(c.get("script") or "")
            if c.get("source_url"):
                st.caption(f"Kaynak: {c['source_url']}")
            if c.get("folder"):
                st.code(str(organize.absolute_folder(c["folder"], cfg)), language=None)
        with right:
            link = st.text_input("YouTube linki", value=(f"https://youtu.be/{c['yt_video_id']}" if c.get("yt_video_id") else ""),
                                 key=f"yt-{c['id']}")
            if st.button("🔗 Kaydet", key=f"ytb-{c['id']}"):
                try:
                    youtube.link_video(repo, c["id"], link)
                    st.toast("Link kaydedildi.")
                except youtube.YouTubeError as exc:
                    st.error(str(exc))
            score = st.feedback("stars", key=f"r-{c['id']}")
            note = st.text_input("Not (neden beğendin/beğenmedin?)", key=f"n-{c['id']}")
            if st.button("⭐ Puanı kaydet", key=f"rb-{c['id']}", disabled=score is None):
                repo.insert("ratings", {"content_id": c["id"], "score": int(score) + 1, "note": note.strip() or None})
                st.toast("Puan kaydedildi; beyin bundan öğrenecek.")
            if perf:
                st.metric("Skor", perf["score"])
                if perf.get("avg_view_pct") is not None:
                    st.caption(f"İzlenme oranı: %{perf['avg_view_pct']:.0f}")
                if perf.get("rating") is not None:
                    st.caption(f"Ortalama puanın: {perf['rating']:.1f}/5")
