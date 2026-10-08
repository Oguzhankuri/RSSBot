import re

from bulten import utils


def test_slugify_tr_turkish_chars():
    assert utils.slugify_tr("Çanakkale'de İşçi Grevi Büyüyor!") == "canakkale-de-isci-grevi-buyuyor"


def test_slugify_tr_dotless_and_max_len():
    assert utils.slugify_tr("IŞIK ÖĞÜ", max_len=50) == "isik-ogu"
    slug = utils.slugify_tr("a" * 30 + " " + "b" * 30, max_len=35)
    assert len(slug) <= 35 and not slug.endswith("-")


def test_slugify_tr_empty_fallback():
    assert utils.slugify_tr("!!!") == "haber"


def test_today_str_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", utils.today_str())


def test_json_and_text_roundtrip(tmp_path):
    p = utils.write_json(tmp_path / "a" / "b.json", {"ş": 1})
    assert utils.read_json(p) == {"ş": 1}
    assert utils.read_json(tmp_path / "yok.json", default=[]) == []
    t = utils.write_text(tmp_path / "x.md", "merhaba")
    assert utils.read_text(t) == "merhaba"


def test_language_name():
    assert utils.language_name("de") == "German"
    assert utils.language_name("de", "tr") == "Almanca"
    assert utils.language_name("xx") == "xx"
