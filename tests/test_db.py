import json

import pytest

from bulten import state
from bulten.config import ConfigError, load_config
from bulten.db import RepoError, SqliteRepo, SupabaseRepo, create_repo, kv_get, kv_set


@pytest.fixture
def repo():
    return SqliteRepo()


def test_insert_get_update_delete(repo):
    row = repo.insert("ideas", {"text": "fikir", "priority": 3})
    assert row["id"] and row["created_at"]
    assert repo.get("ideas", row["id"])["text"] == "fikir"
    updated = repo.update("ideas", row["id"], {"priority": 5})
    assert updated["priority"] == 5 and updated["text"] == "fikir" and updated["updated_at"]
    repo.delete("ideas", row["id"])
    assert repo.get("ideas", row["id"]) is None


def test_insert_duplicate_and_unknown(repo):
    repo.insert("kv", {"id": "a", "value": 1})
    with pytest.raises(RepoError):
        repo.insert("kv", {"id": "a", "value": 2})
    with pytest.raises(RepoError):
        repo.insert("yok", {})
    with pytest.raises(RepoError):
        repo.update("kv", "olmayan", {"value": 1})


def test_select_filters_order_limit_since(repo):
    for i, status in enumerate(["yeni", "arsiv", "yeni"]):
        repo.insert("ideas", {"id": f"i{i}", "text": str(i), "status": status, "priority": i,
                              "created_at": f"2026-10-0{i + 1}T00:00:00+00:00"})
    assert [r["id"] for r in repo.select("ideas", {"status": "yeni"})] == ["i0", "i2"]
    assert [r["id"] for r in repo.select("ideas", order_by="priority", desc=True, limit=2)] == ["i2", "i1"]
    assert [r["id"] for r in repo.select("ideas", since=("created_at", "2026-10-02"))] == ["i1", "i2"]


def test_upsert_merges(repo):
    repo.upsert("kv", {"id": "k", "value": 1, "x": "keep"})
    repo.upsert("kv", {"id": "k", "value": 2})
    assert repo.get("kv", "k")["value"] == 2 and repo.get("kv", "k")["x"] == "keep"


def test_kv_helpers(repo):
    assert kv_get(repo, "offset", 0) == 0
    kv_set(repo, "offset", 42)
    assert kv_get(repo, "offset") == 42


def test_sqlite_file_persists(tmp_path):
    path = tmp_path / "sub" / "b.db"
    SqliteRepo(path).insert("ideas", {"id": "x", "text": "kalıcı"})
    assert SqliteRepo(path).get("ideas", "x")["text"] == "kalıcı"


def test_legacy_seen_import_once(repo, tmp_path):
    seen = tmp_path / "seen.json"
    seen.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert state.import_legacy_seen(repo, seen) == 2
    assert state.import_legacy_seen(repo, seen) == 0
    state.mark_seen_db(repo, ["c", ""])
    assert state.load_seen_db(repo) == {"a", "b", "c"}


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data
        self.content = b"x" if data is not None else b""
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json, "headers": headers})
        return self.responses.pop(0)


def test_supabase_requests_shape():
    sess = FakeSession([
        FakeResp(data=[{"id": "1", "text": "a"}]),
        FakeResp(data=[{"id": "1"}]),
        FakeResp(data=[]),
        FakeResp(data=[{"id": "1", "priority": 4}]),
        FakeResp(data=None),
        FakeResp(data=[{"id": "1"}]),
    ])
    repo = SupabaseRepo("https://p.supabase.co/", "srv", session=sess)
    assert repo.insert("ideas", {"text": "a"})["text"] == "a"
    assert sess.calls[0]["headers"]["Authorization"] == "Bearer srv"
    assert sess.calls[0]["url"] == "https://p.supabase.co/rest/v1/ideas"
    repo.select("ideas", {"status": "yeni", "active": True}, order_by="created_at", desc=True, limit=5,
                since=("created_at", "2026"))
    params = sess.calls[1]["params"]
    assert params["status"] == "eq.yeni" and params["active"] == "is.true"
    assert params["order"] == "created_at.desc.nullslast" and params["limit"] == 5
    assert params["created_at"] == "gte.2026"
    assert repo.get("ideas", "nope") is None
    assert repo.update("ideas", "1", {"priority": 4})["priority"] == 4
    repo.delete("ideas", "1")
    assert sess.calls[4]["method"] == "DELETE"
    assert "merge-duplicates" in (repo.upsert("kv", {"id": "1"}) and sess.calls[5]["headers"]["Prefer"])


def test_supabase_errors():
    with pytest.raises(RepoError):
        SupabaseRepo("", "")
    repo = SupabaseRepo("https://x", "k", session=FakeSession([FakeResp(400, {"msg": "bad"}), FakeResp(data=[])]))
    with pytest.raises(RepoError, match="400"):
        repo.select("ideas")
    with pytest.raises(RepoError, match="bulunamadı"):
        repo.update("ideas", "x", {"a": 1})


def test_create_repo_and_config(write_cfg, monkeypatch, tmp_path):
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "BULTEN_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(write_cfg({"db": {"provider": "sqlite", "sqlite_path": str(tmp_path / "x.db")}}))
    assert cfg["formats"]["enabled"] == ["yatay", "dikey"] and cfg["brain"]["candidate_pool"] == 30
    assert isinstance(create_repo(cfg), SqliteRepo)

    with pytest.raises(ConfigError, match="SUPABASE_URL"):
        load_config(write_cfg({"db": {"provider": "supabase"}}), require_db=True)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setenv("BULTEN_OUTPUT_DIR", "/drive/out")
    cfg = load_config(write_cfg({"db": {"provider": "supabase"}}), require_db=True)
    assert isinstance(create_repo(cfg), SupabaseRepo)
    assert cfg["output"]["base_dir"] == "/drive/out"

    with pytest.raises(ConfigError, match="db.provider"):
        load_config(write_cfg({"db": {"provider": "mongo"}}))
    with pytest.raises(ConfigError, match="formats.enabled"):
        load_config(write_cfg({"formats": {"enabled": []}}))
    with pytest.raises(RepoError):
        create_repo({"db": {"provider": "x"}})
