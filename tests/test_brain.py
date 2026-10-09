import json

import pytest

from bulten import youtube
from bulten.brain import memory, reflect
from bulten.db import SqliteRepo
from tests.fakes import FakeChat


@pytest.fixture
def repo():
    r = SqliteRepo()
    for i, (fmt, views, pct, score) in enumerate([
        ("dikey", 50000, 80, 5), ("dikey", 200, 20, 2), ("yatay", 5000, 45, 4), ("yatay", 10, 5, None),
    ]):
        r.insert("contents", {"id": f"c{i}", "date": "2026-10-05", "format": fmt, "title": f"Başlık {i} liman krizi",
                              "source_title": f"Kaynak {i}", "script": "Açılış cümlesi. Devamı.", "hook": "Şok!" if fmt == "dikey" else None,
                              "tags": [], "features": {"words": 100}, "yt_video_id": f"vid{i:08d}"})
        r.insert("metrics", {"content_id": f"c{i}", "yt_video_id": f"vid{i:08d}", "views": views, "avg_view_pct": pct})
        if score:
            r.insert("ratings", {"content_id": f"c{i}", "score": score})
    r.insert("contents", {"id": "c9", "date": "2026-01-01", "format": "dikey", "title": "Çok eski", "tags": []})
    return r


def test_similarity_and_filter_repeats(repo):
    assert memory.similarity("Liman krizi büyüyor", "büyüyor liman krizi") > 0.9
    assert memory.similarity("Liman krizi", "Uzay görevi başladı") < 0.6
    recent = memory.recent_titles(repo, 30, today="2026-10-09")
    assert "Kaynak 0" in recent and "Çok eski" not in recent
    cands = [{"title": "Başlık 0 liman krizi"}, {"title": "Mars'a yeni görev"}]
    assert memory.filter_repeats(cands, recent, 0.8) == [{"title": "Mars'a yeni görev"}]


def test_performance_and_guidance(repo):
    table = memory.performance_table(repo)
    assert table[0]["content"]["id"] == "c0" and table[-1]["content"]["id"] == "c3"
    assert memory.performance_table(repo, "yatay")[0]["content"]["id"] == "c2"
    assert memory.performance_score(None, None) is None
    reflect.add_manual_rule(repo, "Kancada rakam kullan", "dikey")
    repo.insert("insights", {"rule": "Yatayda genel kural", "format": None, "confidence": 0.4, "active": True})
    repo.insert("insights", {"rule": "pasif", "format": "dikey", "confidence": 0.9, "active": False})
    guidance = memory.format_guidance(repo, "dikey")
    assert "Kancada rakam" in guidance and "Yatayda genel" in guidance and "pasif" not in guidance
    assert "Başlık 0" in guidance and "kanca: Şok!" in guidance
    ctx = memory.planner_context(repo, [{"id": "abcdef123", "text": "fikir", "priority": 5}], ["eski konu"])
    assert "[abcdef] (öncelik 5) fikir" in ctx and "eski konu" in ctx and "EN İYİ" in ctx
    with pytest.raises(ValueError):
        reflect.add_manual_rule(repo, "  ")


def test_reflect_replaces_unapproved_rules(repo):
    keep = reflect.add_manual_rule(repo, "Onaylı kural")
    old = repo.insert("insights", {"rule": "Eski otomatik", "confidence": 0.5, "active": True, "approved": False})
    answer = json.dumps({"kurallar": [
        {"kural": "Dikeyde kanca soru olsun", "format": "dikey", "guven": 1.7, "kanit": 3},
        {"kural": "", "format": "x"},
        {"kural": "Genel kural", "format": "kare", "guven": "x"},
    ], "ozet": "Dikey iyi gidiyor."})
    chat = FakeChat([answer])
    result = reflect.reflect(repo, chat)
    assert result["summary"] == "Dikey iyi gidiyor." and len(result["rules"]) == 2
    assert result["rules"][0]["confidence"] == 1.0 and result["rules"][1]["format"] is None
    assert repo.get("insights", old["id"])["active"] is False and repo.get("insights", keep["id"])["active"] is True
    assert "Onaylı kural" in chat.calls[0]["user"]


def test_reflect_needs_data_and_handles_empty():
    empty = SqliteRepo()
    assert "en az" in reflect.reflect(empty, FakeChat())["summary"]


def test_reflect_no_rules(repo):
    out = reflect.reflect(repo, FakeChat([json.dumps({"kurallar": []})]))
    assert out["rules"] == [] and out["summary"]


@pytest.mark.parametrize("value,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/shorts/dQw4w9WgXcQ?feature=share", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://example.com", None),
    ("", None),
])
def test_parse_video_id(value, expected):
    assert youtube.parse_video_id(value) == expected


def test_link_and_sync_metrics(repo):
    with pytest.raises(youtube.YouTubeError):
        youtube.link_video(repo, "c9", "kötü link")
    assert youtube.link_video(repo, "c9", "https://youtu.be/dQw4w9WgXcQ")["yt_video_id"] == "dQw4w9WgXcQ"

    class FakeSource:
        def fetch(self, ids, end):
            assert end == "2026-10-09"
            return {"vid00000000": {"views": 99, "avg_view_pct": 50}, "dQw4w9WgXcQ": {"views": 1}}

    assert youtube.sync_metrics(repo, FakeSource(), "2026-10-09") == 2
    assert youtube.sync_metrics(SqliteRepo(), FakeSource(), "x") == 0


def test_analytics_query_batches():
    calls = []

    class Q:
        def __init__(self, kw):
            self.kw = kw

        def execute(self):
            ids = self.kw["filters"].split("==")[1].split(",")
            return {"rows": [[v, 10, 30.0, 55.0, 1, 0, 2] for v in ids]}

    class Service:
        def reports(self):
            return self

        def query(self, **kw):
            calls.append(kw)
            return Q(kw)

    ids = [f"v{i:010d}" for i in range(60)]
    out = youtube.YouTubeAnalytics(Service()).fetch(ids, "2026-10-09")
    assert len(calls) == 2 and len(out) == 60 and out["v0000000000"]["avg_view_pct"] == 55.0


def test_from_token_missing(tmp_path):
    with pytest.raises(youtube.YouTubeError):
        youtube.YouTubeAnalytics.from_token(tmp_path / "yok.json")
