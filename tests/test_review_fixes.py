"""Kod incelemesinde bulunan hataların regresyon testleri."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from bulten import ideas, telegram_sync
from bulten.db import RepoError, SqliteRepo, SupabaseRepo
from bulten.pipeline import model, runner
from tests.test_db import FakeResp, FakeSession
from tests.test_ideas_telegram import OWNER, FakeHttp, msg
from tests.test_pipeline import DATE, setup  # noqa: F401 — fixture


def test_telegram_ideas_have_distinct_short_codes():
    repo = SqliteRepo()
    api = telegram_sync.TelegramApi("t", http=FakeHttp([msg(1, "bir"), msg(2, "iki")]))
    telegram_sync.sync(repo, api, OWNER)
    codes = {ideas.short_id(i) for i in repo.select("ideas")}
    assert len(codes) == 2
    for code in codes:
        assert ideas.find_by_prefix(repo, code) is not None


def test_telegram_network_error_keeps_offset():
    class FlakyRepo(SqliteRepo):
        def insert(self, table, row):
            if table == "ideas":
                raise RepoError("Supabase'e ulaşılamadı")
            return super().insert(table, row)

    repo = FlakyRepo()
    api = telegram_sync.TelegramApi("t", http=FakeHttp([msg(7, "kaybolmasın")]))
    with pytest.raises(RepoError):
        telegram_sync.sync(repo, api, OWNER)
    from bulten.db import kv_get
    assert kv_get(repo, telegram_sync.OFFSET_KEY, 0) == 0


def test_supabase_paginates_and_flags_conflict():
    page = [{"id": str(i)} for i in range(1000)]
    sess = FakeSession([FakeResp(data=page), FakeResp(data=[{"id": "x"}]), FakeResp(409, {"code": "23505"})])
    repo = SupabaseRepo("https://x", "k", session=sess)
    assert len(repo.select("seen_items")) == 1001
    assert sess.calls[1]["params"]["offset"] == 1000
    with pytest.raises(RepoError) as info:
        repo.insert("ideas", {"id": "a", "text": "t"})
    assert info.value.conflict is True


def test_stale_running_does_not_block(setup):  # noqa: F811
    cfg, repo, deps, *_ = setup
    runner.ensure_run(repo, cfg, DATE)
    sid = model.step_id(model.run_id_for(DATE), "plan")
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    repo.upsert("run_steps", {"id": sid, "status": model.RUNNING, "updated_at": old})
    # SqliteRepo.update updated_at'i yeniler; eski zamanı doğrudan yazdık
    assert not runner._is_live(repo.get("run_steps", sid))
    runner.advance(repo, cfg, DATE, deps=deps)
    assert repo.get("run_steps", sid)["status"] == model.DONE


def test_reset_reopens_finished_run(setup):  # noqa: F811
    cfg, repo, deps, *_ = setup
    runner.ensure_run(repo, cfg, DATE)
    repo.update("runs", model.run_id_for(DATE), {"status": "bitti"})
    runner.reset_step(repo, DATE, "package")
    assert repo.get("runs", model.run_id_for(DATE))["status"] == "aktif"


def test_partial_image_failure_and_missing_folder(setup, tmp_path):  # noqa: F811
    cfg, repo, deps, _, backend = setup
    runner.advance(repo, cfg, DATE, deps=deps)
    backend.fail_on = {2}
    turn = runner.advance(repo, cfg, DATE, actors=[model.COLAB], only=["images"], deps=deps)
    assert turn.status == model.FAILED and "görsel üretilemedi" in turn.detail
    backend.fail_on = set()
    turn = runner.advance(repo, cfg, DATE, actors=[model.COLAB], only=["images"], deps=deps)
    assert repo.get("run_steps", model.step_id(model.run_id_for(DATE), "images"))["status"] == model.DONE

    content = repo.select("contents")[0]
    (tmp_path / "out" / content["folder"] / "metadata.json").unlink()
    runner.reset_step(repo, DATE, "images")
    turn = runner.advance(repo, cfg, DATE, actors=[model.COLAB], only=["images"], deps=deps)
    assert turn.status == model.FAILED and "Drive" in turn.detail


def test_profile_snapshot_used_after_yaml_edit(setup):  # noqa: F811
    cfg, repo, deps, *_ = setup
    runner.advance(repo, cfg, DATE, deps=deps)
    plan = repo.get("runs", model.run_id_for(DATE))["plan"]
    assert plan["profiles"]["dikey"]["images"]["width"] == 720


def test_public_ci_logs_hide_response_body(monkeypatch):
    from bulten.db import supabase_repo

    monkeypatch.setattr(supabase_repo, "PUBLIC_LOGS", True)
    repo = SupabaseRepo("https://gizli.supabase.co", "k", session=FakeSession([FakeResp(400, {"text": "gizli fikir"})]))
    with pytest.raises(RepoError) as info:
        repo.select("ideas", limit=1)
    assert "gizli fikir" not in str(info.value) and "(400)" in str(info.value)


def test_gated_model_gives_turkish_help(monkeypatch, base_cfg):
    import sys
    import types

    from bulten import images

    class Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def is_bf16_supported():
            return True

    class GatedRepoError(Exception):
        pass

    class FluxPipeline:
        @staticmethod
        def from_pretrained(*a, **k):
            raise GatedRepoError("401 Client Error. Cannot access gated repo")

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=Cuda, bfloat16="bf16", float16="f16"))
    monkeypatch.setitem(sys.modules, "diffusers", types.SimpleNamespace(FluxPipeline=FluxPipeline))
    with pytest.raises(images.ImageGenerationError, match="HF_TOKEN"):
        images.FluxLocalBackend(base_cfg)


def test_dbstack_tunnel_url_and_errors(monkeypatch):
    import subprocess

    from bulten import dbstack

    class Done:
        def __init__(self, code, out):
            self.returncode, self.stdout, self.stderr = code, out, ""

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return Done(0, "INF https://a-b.trycloudflare.com\nINF https://c-d.trycloudflare.com\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dbstack.tunnel_url() == "https://c-d.trycloudflare.com"
    dbstack.start_tunnel()
    assert calls[-1][-3:] == ["up", "-d", "tunnel"]
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: Done(1, "no such service"))
    assert dbstack.tunnel_url() is None
    with pytest.raises(dbstack.StackError, match="no such"):
        dbstack.stop_tunnel()

    def boom(cmd, **kw):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(dbstack.StackError, match="Docker Desktop"):
        dbstack.start_tunnel()


def test_uses_local_db():
    from bulten import panel_support as ps

    assert ps.uses_local_db({"db": {"provider": "supabase"}, "env": {"SUPABASE_URL": "http://127.0.0.1:8000"}})
    assert not ps.uses_local_db({"db": {"provider": "supabase"}, "env": {"SUPABASE_URL": "https://x.supabase.co"}})
    assert not ps.uses_local_db({"db": {"provider": "sqlite"}, "env": {}})


def test_setup_db_jwt_and_env_merge(tmp_path):
    import base64
    import hashlib
    import hmac
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("setup_db", Path("docker/setup_db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    token = mod.sign_jwt({"role": "service_role"}, "sır")
    head, body, sig = token.split(".")
    expected = hmac.new(b"s\xc4\xb1r", f"{head}.{body}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(sig + "==") == expected
    assert json.loads(base64.urlsafe_b64decode(body + "==")) == {"role": "service_role"}
    env = tmp_path / ".env"
    env.write_text("# yorum\nDEEPSEEK_API_KEY=abc\nSUPABASE_URL=eski\n", encoding="utf-8")
    mod.set_env_values(env, {"SUPABASE_URL": "yeni", "SUPABASE_SERVICE_KEY": "k"})
    assert env.read_text(encoding="utf-8") == "# yorum\nDEEPSEEK_API_KEY=abc\nSUPABASE_URL=yeni\nSUPABASE_SERVICE_KEY=k\n"


def test_setup_db_server_mode(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("setup_db_srv", Path("docker/setup_db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DOCKER_ENV", tmp_path / "docker.env")
    mod.setup_server("db.ornek.com")
    env = mod.read_env(tmp_path / "docker.env")
    assert env["SITE_ADDRESS"] == "db.ornek.com" and len(env["JWT_SECRET"]) > 40
    out = capsys.readouterr().out
    assert "SUPABASE_URL=https://db.ornek.com" in out and "SUPABASE_SERVICE_KEY=ey" in out
    with pytest.raises(SystemExit):
        mod.setup_server("http://kotu adres")
