import json

from bulten import organize


def sample(i):
    return {
        "title": f"Kaynak {i}",
        "baslik": f"Başlık {i} Şöyle",
        "link": f"https://x/{i}",
        "published": "",
        "senaryo": "senaryo metni",
        "ozet": f"özet {i}",
        "etiketler": ["a"],
        "gorsel_promptleri": ["p"],
        "ceviriler": {"en": "hello", "de": "hallo"},
        "gorseller": ["/x/01.png"],
        "hatalar": [],
    }


def test_full_tree_and_index(tmp_path, base_cfg):
    cfg = {**base_cfg, "output": {"base_dir": str(tmp_path)}}
    items = [sample(1), sample(2)]
    dirs = organize.build_day_dirs("2026-10-08", items, cfg)
    assert [d.name for d in dirs] == ["01-baslik-1-soyle", "02-baslik-2-soyle"]
    for d, item in zip(dirs, items):
        organize.save_item(d, item)
        assert (d / "senaryo_tr.md").read_text(encoding="utf-8").startswith("# Başlık")
        assert (d / "ceviriler" / "en.md").exists() and (d / "ceviriler" / "de.md").exists()
        assert (d / "ses" / "OKU_BENI.txt").exists() and not (d / "ses" / "tr.wav").exists()
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
        assert meta["kaynak_url"] == item["link"] and meta["gorseller"] == ["01.png"]
    index, manifest = organize.write_day_index("2026-10-08", cfg)
    md = index.read_text(encoding="utf-8")
    assert "01. Başlık 1" in md and "./02-baslik-2-soyle/" in md
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["haber_sayisi"] == 2 and data["haberler"][1]["klasor"] == "02-baslik-2-soyle"
    assert data["haberler"][0]["ceviri_dilleri"] == ["de", "en"]
    assert organize.next_index(tmp_path / "2026-10-08") == 3


def test_unique_dir_never_overwrites(tmp_path):
    (tmp_path / "01-a").mkdir()
    (tmp_path / "01-a-2").mkdir()
    assert organize.unique_dir(tmp_path / "01-a").name == "01-a-3"
    assert organize.unique_dir(tmp_path / "02-b").name == "02-b"
    assert organize.next_index(tmp_path / "yok") == 1
