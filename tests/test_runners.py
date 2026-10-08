import json
from pathlib import Path

import pytest

import run_text
import run_voice
from bulten.config import ConfigError
from bulten.voice import VoiceSynthesizer
from tests.fakes import FakeChat, FakeImageBackend, FakeTTSModel, make_item


@pytest.fixture
def project(tmp_path, monkeypatch, write_cfg):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs" / "ref_voice.wav").write_bytes(b"x")
    return str(write_cfg({"output": {"base_dir": "output"}}))


def patch_pipeline(monkeypatch, items, backend=None):
    monkeypatch.setattr(
        run_text.ingest, "fetch_feed_items", lambda cfg, seen=None: [i for i in items if i["id"] not in seen]
    )
    monkeypatch.setattr(run_text, "DeepSeekClient", lambda cfg: FakeChat())
    monkeypatch.setattr(run_text.images, "create_backend", lambda cfg: backend or FakeImageBackend())


def item_dirs(day: str) -> list[Path]:
    return sorted(d for d in Path("output", day).iterdir() if d.is_dir())


def test_run_text_end_to_end_and_dedupe(project, monkeypatch):
    patch_pipeline(monkeypatch, [make_item(1), make_item(2)])
    assert run_text.run(project, "2026-10-08") == 0
    dirs = item_dirs("2026-10-08")
    assert [d.name[:3] for d in dirs] == ["01-", "02-"]
    for d in dirs:
        assert (d / "senaryo_tr.md").exists()
        assert len(list((d / "ceviriler").glob("*.md"))) == 4
        assert len(list((d / "gorseller").glob("*.png"))) == 3
    manifest = json.loads(Path("output/2026-10-08/manifest.json").read_text(encoding="utf-8"))
    assert manifest["haber_sayisi"] == 2
    seen = set(json.loads(Path("state/seen.json").read_text(encoding="utf-8")))
    assert seen == {"https://example.com/1", "https://example.com/2"}

    assert run_text.run(project, "2026-10-09") == 0
    assert not Path("output/2026-10-09").exists()


def test_run_text_item_failure_isolated(project, monkeypatch):
    patch_pipeline(monkeypatch, [make_item(1), make_item(2)])
    real = run_text.organize.save_item

    def flaky(d, data):
        if data["id"].endswith("/1"):
            raise OSError("disk")
        real(d, data)

    monkeypatch.setattr(run_text.organize, "save_item", flaky)
    assert run_text.run(project, "2026-10-08") == 0
    dirs = item_dirs("2026-10-08")
    assert len(dirs) == 1 and dirs[0].name.startswith("02-")


def test_run_text_without_gpu_stops_before_spending(project, monkeypatch):
    patch_pipeline(monkeypatch, [make_item(1)])
    chat_created = []
    monkeypatch.setattr(run_text, "DeepSeekClient", lambda cfg: chat_created.append(1))

    def no_gpu(cfg):
        raise run_text.images.ImageGenerationError("GPU bulunamadı")

    monkeypatch.setattr(run_text.images, "create_backend", no_gpu)
    with pytest.raises(run_text.images.ImageGenerationError):
        run_text.run(project, "2026-10-08")
    assert chat_created == [] and not Path("state/seen.json").exists()


def test_incomplete_item_not_marked_seen(project, monkeypatch):
    patch_pipeline(monkeypatch, [make_item(1)], backend=FakeImageBackend(fail_on={1, 2, 3}))
    assert run_text.run(project, "2026-10-08") == 0
    assert not Path("state/seen.json").exists()


def test_same_day_rerun_continues_numbering(project, monkeypatch):
    items = [make_item(1)]
    patch_pipeline(monkeypatch, items)
    run_text.run(project, "2026-10-08")
    tr_wav = item_dirs("2026-10-08")[0] / "ses" / "tr.wav"
    tr_wav.write_bytes(b"benim sesim")
    items.append(make_item(2))
    run_text.run(project, "2026-10-08")
    assert [d.name[:3] for d in item_dirs("2026-10-08")] == ["01-", "02-"]
    assert tr_wav.read_bytes() == b"benim sesim"
    manifest = json.loads(Path("output/2026-10-08/manifest.json").read_text(encoding="utf-8"))
    assert manifest["haber_sayisi"] == 2


def test_run_text_no_new_items(project, monkeypatch):
    patch_pipeline(monkeypatch, [])
    assert run_text.run(project, "2026-10-08") == 0


def test_run_voice_generates_all_languages(project, monkeypatch):
    patch_pipeline(monkeypatch, [make_item(1)])
    run_text.run(project, "2026-10-08")
    cfg = run_voice.load_config(project, require_voice=True)
    synth = VoiceSynthesizer(cfg, model=FakeTTSModel())
    assert run_voice.run(project, "2026-10-08", synth=synth) == 0
    ses = item_dirs("2026-10-08")[0] / "ses"
    assert sorted(p.name for p in ses.glob("*.wav")) == ["ar.wav", "de.wav", "en.wav", "ru.wav"]
    assert run_voice.run(project, "2026-10-08", synth=synth) == 0  # var olanlar atlanır


def test_run_voice_missing_day(project):
    with pytest.raises(ConfigError, match="run_text"):
        run_voice.run(project, "2020-01-01", synth=object())


def test_run_voice_requires_ref(project):
    Path("refs/ref_voice.wav").unlink()
    with pytest.raises(ConfigError, match="referans"):
        run_voice.run(project, "2026-10-08")
