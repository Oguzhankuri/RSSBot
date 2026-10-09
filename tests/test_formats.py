import json

import pytest

from bulten import formats, montage, organize, rewrite
from bulten.config import ConfigError
from tests.fakes import FakeChat, make_item

DIKEY_JSON = json.dumps(
    {
        "baslik": "Bunu kimse beklemiyordu",
        "kanca": "Dünyanın en büyük limanı bir gecede kapandı!",
        "senaryo": "Dünyanın en büyük limanı bir gecede kapandı! Peki neden? Yetkililer açıklama yaptı. Sen ne düşünüyorsun?",
        "ozet": "Liman kapandı.",
        "ekran_yazilari": [{"saniye": "5", "metin": "NEDEN?"}, {"saniye": 0, "metin": "LİMAN KAPANDI"}, {"metin": ""}, "bozuk"],
        "altyazi_vurgulari": ["liman", " "],
        "kapanis_cta": "Sen ne düşünüyorsun?",
        "muzik_onerisi": "gergin elektronik",
        "gorsel_promptleri": ["vertical port at night"],
        "etiketler": ["#shorts", "liman"],
    }
)


def test_profiles_load_and_override(base_cfg):
    assert {"yatay", "dikey"} <= set(formats.available_formats())
    cfg = {**base_cfg, "formats": {"enabled": ["dikey"], "overrides": {"dikey": {"max_items": 5, "images": {"count": 2}}}}}
    (dikey,) = formats.enabled_profiles(cfg)
    assert dikey["max_items"] == 5 and dikey["images"]["count"] == 2 and dikey["images"]["width"] == 720
    with pytest.raises(ConfigError, match="Bilinmeyen format"):
        formats.load_profile("kare")


def test_image_cfg_and_target_words(base_cfg):
    yatay, dikey = formats.load_profile("yatay"), formats.load_profile("dikey")
    assert formats.image_cfg(yatay, base_cfg)["width"] == base_cfg["images"]["width"]
    icfg = formats.with_format(base_cfg, dikey)["images"]
    assert (icfg["width"], icfg["height"], icfg["count_per_item"]) == (720, 1280, 5)
    assert icfg["style"].startswith("vertical 9:16")
    assert base_cfg["images"]["width"] == 1280  # orijinal yapılandırma değişmedi
    assert formats.target_words(yatay, base_cfg) == base_cfg["rewrite"]["target_words"]
    assert formats.target_words(dikey, base_cfg) == 120
    assert formats.render("{ {{a}} }", a=1) == "{ 1 }"


def test_rewrite_dikey_normalizes_extras(base_cfg):
    chat = FakeChat([DIKEY_JSON])
    out = rewrite.rewrite_item(make_item(), base_cfg, chat, formats.load_profile("dikey"), guidance="- KURAL X")
    assert out["kanca"].startswith("Dünyanın") and out["kapanis_cta"]
    assert out["ekran_yazilari"] == [{"saniye": 0, "metin": "LİMAN KAPANDI"}, {"saniye": 5, "metin": "NEDEN?"}]
    assert out["altyazi_vurgulari"] == ["liman"]
    assert len(out["gorsel_promptleri"]) == 5
    assert "KURAL X" in chat.calls[0]["system"] and "KANCA" in chat.calls[0]["system"]
    assert "{{" not in chat.calls[0]["system"] + chat.calls[0]["user"]


def test_rewrite_dikey_fallback_has_extras(base_cfg):
    out = rewrite.rewrite_item(make_item(), base_cfg, FakeChat(["x", "y"]), formats.load_profile("dikey"))
    assert out["uyari"] and out["ekran_yazilari"] == [] and out["kanca"] == ""
    assert len(out["gorsel_promptleri"]) == 5


def _dikey_data():
    data = json.loads(DIKEY_JSON)
    return {
        **make_item(),
        **rewrite._normalize(data, make_item(), formats.load_profile("dikey")),
        "format": "dikey",
        "ceviriler": {"en": "hi"},
        "gorseller": ["/x/01.png", "/x/02.png"],
        "hatalar": [],
        "content_id": "c1",
        "link": "",
    }


def test_organize_dikey_and_montage(tmp_path, base_cfg):
    cfg = {**base_cfg, "output": {"base_dir": str(tmp_path)}, "formats": {"enabled": ["yatay", "dikey"]}}
    folder = organize.format_dir("2026-10-09", "dikey", cfg) / "01-liman"
    organize.save_item(folder, _dikey_data())
    md = (folder / "senaryo_tr.md").read_text(encoding="utf-8")
    assert "KANCA" in md and "KAPANIŞ" in md and "kendi fikrin" in md
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    assert meta["format"] == "dikey" and meta["content_id"] == "c1" and meta["kaynak_url"] == ""
    assert json.loads((folder / "ekran_yazilari.json").read_text(encoding="utf-8"))[0]["metin"] == "LİMAN KAPANDI"
    assert organize.relative_folder(folder, cfg) == "2026-10-09/dikey/01-liman"
    assert organize.absolute_folder("2026-10-09/dikey/01-liman", cfg) == tmp_path / "2026-10-09/dikey/01-liman"

    (folder / "gorseller" / "01.png").write_bytes(b"x")
    notes = montage.write_montage_notes("2026-10-09", cfg)
    note = notes[0].read_text(encoding="utf-8")
    assert "KANCA" in note and "Ekran yazıları" in note and "gergin elektronik" in note
    assert "| 1 | 00:00 |" in note and "❌ ses/tr.wav" in note and "✅ gorseller/ (1 adet)" in note

    teslim = montage.write_delivery("2026-10-09", cfg).read_text(encoding="utf-8")
    assert "Dikey Shorts" in teslim and "eksik" in teslim and "Yatay bülten (16:9) — 0 içerik" in teslim


def test_yatay_montage_and_scenes(tmp_path, base_cfg):
    profile = formats.load_profile("yatay")
    meta = {"baslik": "B", "senaryo": "Bir iki üç. Dört beş altı. Yedi sekiz.", "gorseller": ["01.png", "02.png"]}
    note = montage.build_montage_note(tmp_path, meta, profile, ["en"])
    assert "Alt bant" in note and "❌ ses/en.wav" in note
    scenes = montage.build_scenes("A b. C d. E f.", ["g1"], 2.0)
    assert len(scenes) == 1 and scenes[0]["sure"] == 3
    assert montage.build_scenes("Tek cümle", [], 2.0)[0]["gorsel"].startswith("(görsel yok")


def test_write_index_per_format(tmp_path, base_cfg):
    cfg = {**base_cfg, "output": {"base_dir": str(tmp_path)}}
    root = organize.format_dir("2026-10-09", "dikey", cfg)
    organize.save_item(root / "01-a", _dikey_data())
    index, manifest = organize.write_index(root, "2026-10-09", cfg, label="Shorts")
    assert "Shorts 2026-10-09" in index.read_text(encoding="utf-8")
    assert json.loads(manifest.read_text(encoding="utf-8"))["haber_sayisi"] == 1
