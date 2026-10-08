from bulten import state


def test_mark_seen_dedupes_and_persists(tmp_path):
    p = tmp_path / "seen.json"
    state.mark_seen(["https://a"], p)
    state.mark_seen(["https://a", "https://b"], p)
    assert state.load_seen(p) == {"https://a", "https://b"}


def test_load_seen_missing_and_corrupt(tmp_path):
    assert state.load_seen(tmp_path / "yok.json") == set()
    bad = tmp_path / "bad.json"
    bad.write_text('{"x": 1}', encoding="utf-8")
    assert state.load_seen(bad) == set()


def test_item_id_fallbacks():
    assert state.item_id({"link": "L", "id": "I"}) == "L"
    assert state.item_id({"id": "I"}) == "I"
    assert state.item_id({"title": "Başlık"}).startswith("sha1:")
