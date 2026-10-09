"""🏠 Ana sayfa — tek tık akış: 'Bugünü Başlat', sıra kimde, sıradaki iş."""

from __future__ import annotations

from datetime import date

import streamlit as st
from common import CONFIG_PATH, boot, chat_client

from bulten import dbstack, telegram_sync
from bulten import panel_support as ps
from bulten.db import RepoError
from bulten.pipeline import model, runner
from bulten.utils import today_str

cfg, repo = boot("Bugün", "🎬")

st.title("🎬 Bülten Stüdyosu")
picked = st.date_input("Gün", value=date.fromisoformat(today_str()), format="YYYY-MM-DD")
DATE = picked.isoformat()


def start(force: bool = False) -> None:
    if not cfg["env"].get("DEEPSEEK_API_KEY"):
        st.toast(".env içinde DEEPSEEK_API_KEY yok; senaryolar yazılamaz.", icon="❌")
        return
    ps.start_background(ps.pipeline_command(DATE, CONFIG_PATH, force=force))
    st.toast("Başladı! Durum birkaç saniye içinde güncellenecek.", icon="🚀")


@st.fragment(run_every=5)
def live_status() -> None:
    steps = runner.list_steps(repo, model.run_id_for(DATE))
    turn = model.current_turn(steps) if steps else None

    if turn is None:
        st.info("Bu gün için henüz bir şey yok.")
        st.button("▶️ Bugünü Başlat", type="primary", use_container_width=True, on_click=start)
        return

    box = {model.COLAB: st.warning, model.USER: st.info, None: st.success}.get(turn.actor, st.info)
    if turn.status == model.FAILED:
        box = st.error
    box(f"### {turn.title}\n{turn.detail}")

    cols = st.columns(3)
    if turn.actor == model.COLAB and turn.status != model.RUNNING:
        if turn.status == model.FAILED:
            cols[2].caption("Colab hücresini tekrar çalıştır; sadece eksikler üretilir.")
        cols[0].link_button("🚀 Colab'ı aç", ps.colab_url(cfg), type="primary", use_container_width=True)
        cols[1].caption("Colab'da tek hücreyi ▶ çalıştır. Bitince bu ekran kendiliğinden güncellenir.")
        if ps.uses_local_db(cfg):
            url = dbstack.tunnel_url()
            if url:
                st.caption("Colab Secrets → SUPABASE_URL şu olmalı (tünel adresi her açılışta değişir):")
                st.code(url, language=None)
            else:
                st.warning("Veritabanı bu bilgisayarda: Colab'ın ulaşması için önce ⚙️ Ayarlar → 'Tüneli aç'.")
    elif turn.status == model.FAILED:
        cols[0].button("🔁 Tekrar dene", type="primary", use_container_width=True, on_click=start)
    elif turn.actor == model.PC and turn.status != model.RUNNING:
        cols[0].button("▶️ Devam et", type="primary", use_container_width=True, on_click=start)
    elif turn.actor == model.USER:
        cols[0].button("🔄 Kontrol et ve devam et", type="primary", use_container_width=True, on_click=start)
        if cols[1].button("⏭️ Bu adımı atla", use_container_width=True):
            runner.complete_user_step(repo, DATE, turn.step_key, "Kullanıcı atladı.")
            start()

    st.subheader("Adımlar")
    for row in steps:
        sdef = model.STEP_BY_KEY[row["key"]]
        icon = ps.STATUS_ICONS.get(row["status"], "•")
        who = ps.ACTOR_LABELS.get(row["actor"], row["actor"])
        st.markdown(f"{icon} **{sdef.label}** · _{who}_")
        if row.get("message"):
            st.caption(row["message"])

    if turn.step_key == "tr_voice":
        tr_voice_panel()

    log = ps.tail(ps.log_path(cfg, DATE))
    if log:
        with st.expander("İşlem günlüğü"):
            st.code(log, language=None)


def tr_voice_panel() -> None:
    st.subheader("🎙️ TR ses kayıtları")
    st.caption("Senaryoyu oku, kaydını WAV olarak buraya bırak (ya da Drive'daki ses/tr.wav yoluna kaydet).")
    for item in ps.tr_voice_todo(repo, cfg, DATE):
        content = item["content"]
        label = f"{'✅' if item['done'] else '⏳'} [{content['format']}] {content['title']}"
        with st.expander(label, expanded=not item["done"]):
            if item["script_path"].exists():
                st.markdown(item["script_path"].read_text(encoding="utf-8"))
            st.code(str(item["wav_path"]), language=None)
            upload = st.file_uploader("tr.wav yükle", type=["wav"], key=f"wav-{content['id']}")
            if upload is not None:
                try:
                    ps.save_upload(item["wav_path"], upload.getvalue())
                    st.success("Kaydedildi.")
                except ValueError as exc:
                    st.error(str(exc))


@st.fragment(run_every=120)
def telegram_background_sync() -> None:
    """Veritabanı bu bilgisayardaysa GitHub Actions ulaşamaz; panel açıkken fikirleri panel çeker."""
    if not (cfg["env"].get("TELEGRAM_BOT_TOKEN") and cfg["env"].get("TELEGRAM_ALLOWED_USER_ID")):
        return
    try:
        api, owner = telegram_sync.from_config(cfg)
        telegram_sync.sync(repo, api, owner, chat_client(cfg))
    except (telegram_sync.TelegramError, RepoError) as exc:
        st.caption(f"📨 Telegram senkronu bekliyor: {exc}")


live_status()
telegram_background_sync()

with st.sidebar:
    st.header("Bakım")
    if st.button("🔓 Kilidi aç", help="Bir işlem yarıda kaldıysa 'çalışıyor' durumunu temizler."):
        st.toast(f"{runner.unlock(repo, DATE)} kilit temizlendi.")
    step_keys = [s.key for s in model.STEPS]
    redo = st.selectbox("Adımı baştan çalıştır", step_keys, format_func=lambda k: model.STEP_BY_KEY[k].label)
    if st.button("↩️ Bu adımdan itibaren sıfırla"):
        runner.reset_step(repo, DATE, redo)
        st.toast("Sıfırlandı. 'Devam et' ile yeniden çalıştır.")
