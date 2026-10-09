"""Panel: yardımcılar + Streamlit AppTest ile sayfaların hatasız açıldığına dair duman testleri."""

from pathlib import Path

import pytest

from bulten import ideas
from bulten import panel_support as ps
from bulten.db import SqliteRepo
from bulten.pipeline import model, runner
from tests.test_pipeline import DATE

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "panel"


def test_support_helpers(tmp_path, base_cfg):
    cfg = {**base_cfg, "output": {"base_dir": str(tmp_path)}, "colab": {}}
    assert ps.colab_url(cfg) == ps.DEFAULT_COLAB_URL
    assert ps.colab_url({"colab": {"notebook_url": "u"}}) == "u"
    cmd = ps.pipeline_command(DATE, "c.yaml", force=True)
    assert cmd[1:4] == ["-m", "bulten.pipeline", "advance"] and cmd[-1] == "--force"
    log = ps.log_path(cfg, DATE)
    assert ps.tail(log) == ""
    log.parent.mkdir(parents=True)
    log.write_text("".join(f"satır {i}\n" for i in range(100)), encoding="utf-8")
    assert ps.tail(log, 2) == "satır 98\nsatır 99\n"
    with pytest.raises(ValueError):
        ps.save_upload(tmp_path / "x.wav", b"MP3...")
    assert ps.save_upload(tmp_path / "a" / "tr.wav", b"RIFF0000WAVEfmt ").exists()


def test_tr_voice_todo(tmp_path, base_cfg):
    cfg = {**base_cfg, "output": {"base_dir": str(tmp_path)}}
    repo = SqliteRepo()
    repo.insert("contents", {"id": "c1", "run_id": model.run_id_for(DATE), "folder": f"{DATE}/dikey/01-a", "title": "A"})
    (tmp_path / DATE / "dikey" / "01-a" / "ses").mkdir(parents=True)
    assert ps.tr_voice_todo(repo, cfg, DATE)[0]["done"] is False
    (tmp_path / DATE / "dikey" / "01-a" / "ses" / "tr.wav").write_bytes(b"RIFF")
    assert ps.tr_voice_todo(repo, cfg, DATE)[0]["done"] is True


@pytest.fixture
def panel_env(monkeypatch, tmp_path, base_cfg):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.syspath_prepend(str(PANEL))
    import common

    cfg = {**base_cfg, "output": {"base_dir": str(tmp_path)}, "db": {"provider": "sqlite"},
           "colab": {"notebook_url": "https://colab.example"}, "youtube": {"token_path": str(tmp_path / "t.json")},
           "formats": {"enabled": ["yatay", "dikey"], "overrides": {}},
           "brain": {"enabled": True, "candidate_pool": 30, "repeat_days": 30, "repeat_threshold": 0.8},
           "env": {"DEEPSEEK_API_KEY": None, "TELEGRAM_BOT_TOKEN": None}}
    repo = SqliteRepo()
    def fake_load():
        return cfg, repo

    fake_load.clear = lambda: None  # st.cache_resource arayüzü
    monkeypatch.setattr(common, "_load", fake_load)
    started = []
    monkeypatch.setattr(ps, "start_background", lambda cmd, cwd=None: started.append(cmd))
    return AppTest, cfg, repo, started


def _run(AppTest, page):
    at = AppTest.from_file(str(page), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_home_shows_colab_turn(panel_env):
    AppTest, cfg, repo, _ = panel_env
    at = _run(AppTest, PANEL / "app.py")
    assert any("Bu gün için" in i.value for i in at.info)
    runner.ensure_run(repo, cfg, at.date_input[0].value.isoformat())
    for key in ("plan", "write"):
        repo.update("run_steps", model.step_id(model.run_id_for(at.date_input[0].value.isoformat()), key),
                    {"status": model.DONE})
    repo.update("run_steps", model.step_id(model.run_id_for(at.date_input[0].value.isoformat()), "images"),
                {"status": model.QUEUED})
    at = _run(AppTest, PANEL / "app.py")
    assert any("Colab" in w.value for w in at.warning)


def test_idea_page_add(panel_env):
    AppTest, cfg, repo, _ = panel_env
    ideas.add_idea(repo, "var olan fikir", priority=4)
    at = _run(AppTest, PANEL / "pages" / "1_💡_Fikir_Kutusu.py")
    at.text_area[0].input("Panelden yeni fikir")  # form: değer gönderimle birlikte işlenir
    at.button[0].click().run()
    assert not at.exception
    assert {i["text"] for i in repo.select("ideas")} == {"var olan fikir", "Panelden yeni fikir"}


@pytest.mark.parametrize("page", ["2_🎬_Icerikler.py", "3_🧠_Beyin.py", "4_⚙️_Ayarlar.py"])
def test_other_pages_render(panel_env, page):
    AppTest, cfg, repo, _ = panel_env
    repo.insert("contents", {"id": "c1", "date": DATE, "format": "dikey", "title": "T", "script": "S", "tags": [],
                             "hook": "K", "folder": f"{DATE}/dikey/01-t"})
    repo.insert("ratings", {"content_id": "c1", "score": 4})
    repo.insert("insights", {"rule": "Kural", "format": None, "confidence": 0.5, "active": True})
    _run(AppTest, PANEL / "pages" / page)


def test_absolute_folder_rejects_traversal(tmp_path, base_cfg):
    from bulten import organize

    cfg = {**base_cfg, "output": {"base_dir": str(tmp_path / "out")}}
    assert organize.absolute_folder("2026/dikey/01-a", cfg) == tmp_path / "out" / "2026/dikey/01-a"
    with pytest.raises(ValueError, match="output dışına"):
        organize.absolute_folder("../../evil", cfg)


def test_supabase_rejects_bad_column():
    from bulten.db import RepoError, SupabaseRepo

    repo = SupabaseRepo("https://x", "k", session=object())
    with pytest.raises(RepoError, match="sütun"):
        repo.select("ideas", {"status&or": "x"})
