import json

import pytest

from bulten import ideas
from bulten.db import SqliteRepo
from bulten.pipeline import model, runner
from bulten.pipeline.__main__ import main as cli_main
from bulten.pipeline.tasks import Deps
from tests.fakes import FakeChat, FakeImageBackend

DATE = "2026-10-09"


def feed_reader(url):
    return [
        {"id": f"https://n/{i}", "title": f"Önemli gelişme numara {i} {w}", "link": f"https://n/{i}",
         "published": "", "published_ts": 100 - i, "summary": "özet " * 5}
        for i, w in enumerate(["liman", "seçim", "deprem", "uzay", "ekonomi", "spor"])
    ]


class FakeSynth:
    def __init__(self, cfg=None):
        self.calls = []

    def synthesize_to_file(self, text, lang, dst):
        self.calls.append((lang, dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"RIFF")


@pytest.fixture
def setup(tmp_path, base_cfg):
    cfg = {
        **base_cfg,
        "output": {"base_dir": str(tmp_path / "out")},
        "formats": {"enabled": ["yatay", "dikey"], "overrides": {"yatay": {"max_items": 2}, "dikey": {"max_items": 2}}},
        "brain": {"enabled": True, "candidate_pool": 30, "repeat_days": 30, "repeat_threshold": 0.8},
        "db": {"provider": "sqlite"},
        "translate": {"enabled": True, "languages": ["en"]},
        "voice": {**base_cfg["voice"], "languages": ["en"]},
    }
    repo = SqliteRepo()
    synth = FakeSynth()
    backend = FakeImageBackend()
    deps = Deps(
        chat_factory=lambda c: FakeChat(),
        image_backend_factory=lambda c: backend,
        synth_factory=lambda c: synth,
        feed_reader=feed_reader,
        text_fetcher=lambda url: "Tam haber metni. " * 30,
    )
    return cfg, repo, deps, synth, backend


def _steps(repo):
    return {s["key"]: s["status"] for s in runner.list_steps(repo, model.run_id_for(DATE))}


def test_full_day_flow(setup, tmp_path):
    cfg, repo, deps, synth, backend = setup
    idea = ideas.add_idea(repo, "Kuşlar neden V şeklinde uçar?", priority=5)

    turn = runner.advance(repo, cfg, DATE, deps=deps)
    assert _steps(repo)["plan"] == model.DONE and _steps(repo)["write"] == model.DONE
    assert turn.actor == model.COLAB and "Colab" in turn.title
    contents = repo.select("contents")
    assert {c["format"] for c in contents} == {"yatay", "dikey"} and len(contents) == 4
    assert all(c["folder"] for c in contents)
    assert len(repo.select("seen_items")) >= 2
    dikey_dir = tmp_path / "out" / DATE / "dikey"
    assert len([p for p in dikey_dir.iterdir() if p.is_dir()]) == 2
    assert repo.get("ideas", idea["id"])["status"] == "yeni"  # LLM fikri seçmedi (sahte yanıt)

    # Colab: önce görseller, sonra sesler
    turn = runner.advance(repo, cfg, DATE, actors=[model.COLAB], only=["images"], deps=deps)
    assert _steps(repo)["images"] == model.DONE and _steps(repo)["voices"] == model.QUEUED
    sizes = {c["format"]: len(json.loads((tmp_path / "out" / c["folder"] / "metadata.json").read_text(encoding="utf-8"))["gorseller"]) for c in contents}
    assert sizes == {"yatay": 3, "dikey": 5}
    turn = runner.advance(repo, cfg, DATE, actors=[model.COLAB], only=["voices"], deps=deps)
    assert len(synth.calls) == 4 and turn.actor == model.USER and "TR ses" in turn.title

    # Kullanıcı TR seslerini kaydeder → PC paketi hazırlar → yayın linkleri beklenir
    for c in contents:
        (tmp_path / "out" / c["folder"] / "ses" / "tr.wav").write_bytes(b"x")
    turn = runner.advance(repo, cfg, DATE, deps=deps)
    assert _steps(repo)["package"] == model.DONE and turn.step_key == "publish"
    assert (tmp_path / "out" / DATE / "TESLIM.md").exists()
    assert (tmp_path / "out" / contents[0]["folder"] / "MONTAJ_NOTU.md").exists()

    for c in contents:
        repo.update("contents", c["id"], {"yt_video_id": "abc"})
    turn = runner.advance(repo, cfg, DATE, deps=deps)
    assert turn.actor is None and repo.get("runs", model.run_id_for(DATE))["status"] == "bitti"


def test_planner_uses_idea_for_vertical(setup):
    cfg, repo, deps, *_ = setup
    idea = ideas.add_idea(repo, "Kuşlar neden V şeklinde uçar?", priority=5)
    decision = json.dumps({"yatay": [2, 0], "dikey": [{"fikir_id": idea["id"][:6], "aci": "bilim"},
                                                       {"haber_no": 3, "aci": "uzay"}], "gerekce": "test"})
    responses = [decision]
    deps.chat_factory = lambda c: FakeChat(responses)
    runner.advance(repo, cfg, DATE, deps=deps)
    plan = repo.get("runs", model.run_id_for(DATE))["plan"]
    assert [i["id"] for i in plan["yatay"]] == ["https://n/2", "https://n/0"]
    assert plan["dikey"][0]["idea_id"] == idea["id"] and plan["dikey"][1]["id"] == "https://n/3"
    assert repo.get("ideas", idea["id"])["status"] == "kullanildi"
    idea_content = [c for c in repo.select("contents") if c.get("idea_id") == idea["id"]][0]
    assert idea_content["source_url"] == ""
    assert "fikir:" + idea["id"] not in {s["id"] for s in repo.select("seen_items")}


def test_failure_retry_unlock_and_busy(setup):
    cfg, repo, deps, *_ = setup
    deps.feed_reader = lambda url: []
    turn = runner.advance(repo, cfg, DATE, deps=deps)
    assert turn.status == model.FAILED and "yeni haber" in turn.detail
    deps.feed_reader = feed_reader
    turn = runner.advance(repo, cfg, DATE, deps=deps)
    assert _steps(repo)["write"] == model.DONE

    repo.update("run_steps", model.step_id(model.run_id_for(DATE), "images"), {"status": model.RUNNING})
    with pytest.raises(runner.PipelineBusy):
        runner.advance(repo, cfg, DATE, deps=deps)
    assert runner.unlock(repo, DATE) == 1
    assert runner.turn_for_date(repo, DATE).status == model.FAILED

    runner.reset_step(repo, DATE, "images")
    assert _steps(repo)["images"] == model.WAITING and _steps(repo)["write"] == model.DONE
    runner.complete_user_step(repo, DATE, "tr_voice")
    assert _steps(repo)["tr_voice"] == model.SKIPPED
    with pytest.raises(ValueError):
        runner.complete_user_step(repo, DATE, "images")


def test_write_is_resumable(setup):
    cfg, repo, deps, *_ = setup
    runner.advance(repo, cfg, DATE, deps=deps)
    before = len(repo.select("contents"))
    runner.reset_step(repo, DATE, "write")
    runner.advance(repo, cfg, DATE, deps=deps)
    assert len(repo.select("contents")) == before


def test_fal_runs_images_on_pc_and_voice_disabled_skips(setup):
    cfg, repo, deps, *_ = setup
    cfg = {**cfg, "images": {**cfg["images"], "provider": "fal"}, "voice": {**cfg["voice"], "enabled": False}}
    turn = runner.advance(repo, cfg, DATE, deps=deps)
    steps = _steps(repo)
    assert steps["images"] == model.DONE and steps["voices"] == model.SKIPPED
    assert turn.step_key == "tr_voice"


def test_current_turn_texts():
    assert model.current_turn([]).actor is None
    row = {"key": "plan", "position": 1, "actor": "pc", "status": model.RUNNING, "message": None}
    assert "çalışıyor" in model.current_turn([row]).title
    row = {**row, "key": "images", "actor": "colab"}
    assert "Colab'da çalışıyor" in model.current_turn([row]).title


def test_cli_status_and_advance(setup, tmp_path, monkeypatch, write_cfg, capsys):
    cfg, *_ = setup
    db = tmp_path / "x.db"
    path = write_cfg({"db": {"provider": "sqlite", "sqlite_path": str(db)}, "output": {"base_dir": str(tmp_path / "o")}})
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert cli_main(["status", "--config", str(path), "--date", DATE]) == 0
    assert cli_main(["advance", "--config", str(path), "--date", DATE]) == 2  # anahtar yok
    assert cli_main(["unlock", "--config", str(path), "--date", DATE]) == 0
    assert "kilit" in capsys.readouterr().out


def test_cli_colab_turn_and_latest(setup, tmp_path, write_cfg, monkeypatch):
    from bulten.db import create_repo
    from bulten.config import load_config

    monkeypatch.delenv("BULTEN_OUTPUT_DIR", raising=False)
    _, _, deps, *_ = setup
    db = tmp_path / "y.db"
    path = write_cfg({"db": {"provider": "sqlite", "sqlite_path": str(db)}, "output": {"base_dir": str(tmp_path / "o")},
                      "formats": {"enabled": ["dikey"], "overrides": {"dikey": {"max_items": 1}}}})
    assert cli_main(["colab-turn", "--config", str(path), "--date", "latest"]) == 3
    cfg = load_config(path)
    repo = create_repo(cfg)
    runner.advance(repo, cfg, DATE, deps=deps)
    assert cli_main(["colab-turn", "--config", str(path), "--date", "latest"]) == 0
    # GPU kütüphaneleri yok → görsel adımı hata olarak işaretlenir
    assert cli_main(["gpu", "--config", str(path), "--date", "latest", "--only", "images"]) == 1
