import pytest
import requests

from bulten import ingest

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Eski &amp; Haber</title><link>https://x/1</link><pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;ozet bir&lt;/p&gt;</description></item>
<item><title>Yeni Haber</title><link>https://x/2</link><pubDate>Wed, 07 Oct 2026 10:00:00 GMT</pubDate><description>ozet iki</description></item>
</channel></rss>"""


class Resp:
    def __init__(self, content=b"", text="", status=200):
        self.content, self.text, self.status = content, text, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))


def entry(i, ts, summary="s" * 300):
    return {"id": f"u{i}", "title": f"t{i}", "link": f"u{i}", "published": "", "published_ts": ts, "summary": summary}


def test_read_feed_parses_and_strips_html(monkeypatch):
    monkeypatch.setattr(ingest.requests, "get", lambda *a, **k: Resp(content=RSS))
    items = ingest._read_feed("https://feed")
    assert [i["title"] for i in items] == ["Eski & Haber", "Yeni Haber"]
    assert items[0]["summary"] == "ozet bir"
    assert items[1]["published_ts"] > items[0]["published_ts"]


def test_read_feed_http_error(monkeypatch):
    monkeypatch.setattr(ingest.requests, "get", lambda *a, **k: Resp(status=404))
    with pytest.raises(requests.HTTPError):
        ingest._read_feed("https://feed")


def test_fetch_full_text_success_and_failure(monkeypatch):
    monkeypatch.setattr(ingest.requests, "get", lambda *a, **k: Resp(text="<html>x</html>"))
    monkeypatch.setattr(ingest.trafilatura, "extract", lambda *a, **k: "  tam metin  ")
    assert ingest.fetch_full_text("https://a") == "tam metin"

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(ingest.requests, "get", boom)
    assert ingest.fetch_full_text("https://a") is None
    assert ingest.fetch_full_text("") is None


def test_fetch_items_sorts_dedupes_limits(base_cfg):
    cfg = {**base_cfg, "ingest": {**base_cfg["ingest"], "max_items": 2}}
    entries = [entry(1, 1), entry(2, 3), entry(3, 2), entry(4, 4, summary="kısa")]
    items = ingest.fetch_feed_items(cfg, seen={"u2"}, reader=lambda u: entries, text_fetcher=lambda link: None)
    # u4 kısa → elenir, u2 görülmüş → atlanır, kalanlar yeniden eskiye
    assert [i["id"] for i in items] == ["u3", "u1"]
    assert all(len(i["text"]) >= cfg["ingest"]["min_chars"] for i in items)


def test_full_text_preferred(base_cfg):
    items = ingest.fetch_feed_items(
        base_cfg, seen=set(), reader=lambda u: [entry(1, 1, "kısa")], text_fetcher=lambda link: "T" * 500
    )
    assert items[0]["text"] == "T" * 500


def test_one_feed_fails_others_continue(base_cfg):
    cfg = {**base_cfg, "feeds": ["bad", "good"]}

    def reader(url):
        if url == "bad":
            raise ConnectionError("x")
        return [entry(1, 1)]

    assert len(ingest.fetch_feed_items(cfg, seen=set(), reader=reader, text_fetcher=lambda link: None)) == 1


def test_all_feeds_fail(base_cfg):
    def reader(url):
        raise ConnectionError("x")

    with pytest.raises(ingest.IngestError):
        ingest.fetch_feed_items(base_cfg, seen=set(), reader=reader)
