"""Günlük çıktı klasör ağacını kurar, dosyaları ve index'i yazar."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from bulten.utils import ensure_dir, read_json, slugify_tr, write_json, write_text

logger = logging.getLogger(__name__)

ITEM_DIR_RE = re.compile(r"^\d{2}-")

TR_VOICE_NOTE = (
    "Türkçe sesinizi bu klasöre 'tr.wav' olarak ekleyin.\n"
    "Okuyacağınız metin: ../senaryo_tr.md\n"
    "Diğer diller (en/de/...) run_voice.py ile otomatik üretilir.\n"
)


def item_dir_name(index: int, title: str) -> str:
    return f"{index:02d}-{slugify_tr(title)}"


def day_dir(date_str: str, cfg: dict[str, Any]) -> Path:
    return Path(cfg["output"]["base_dir"]) / date_str


def format_dir(date_str: str, fmt: str, cfg: dict[str, Any]) -> Path:
    """v2 düzeni: output/<tarih>/<yatay|dikey>/NN-<slug>/"""
    return day_dir(date_str, cfg) / fmt


def relative_folder(path: Path, cfg: dict[str, Any]) -> str:
    """DB'de saklanan yol: PC ve Colab'da farklı olan output kökünden bağımsız."""
    return Path(path).resolve().relative_to(Path(cfg["output"]["base_dir"]).resolve()).as_posix()


def absolute_folder(rel: str, cfg: dict[str, Any]) -> Path:
    """DB'den gelen göreli yolu output kökü altına çözer; kök dışına çıkan yolu reddeder."""
    base = Path(cfg["output"]["base_dir"])
    target = base / rel
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"Geçersiz içerik klasörü (output dışına çıkıyor): {rel!r}")
    return target


def build_day_dirs(date_str: str, items: list[dict[str, Any]], cfg: dict[str, Any]) -> list[Path]:
    """output/<date>/NN-<slug>/{ceviriler,gorseller,ses} ağacını kurar."""
    root = ensure_dir(day_dir(date_str, cfg))
    dirs: list[Path] = []
    for idx, item in enumerate(items, start=1):
        d = root / item_dir_name(idx, item.get("baslik") or item["title"])
        for sub in ("ceviriler", "gorseller", "ses"):
            ensure_dir(d / sub)
        dirs.append(d)
    return dirs


EXTRA_META_KEYS = ("kanca", "ekran_yazilari", "altyazi_vurgulari", "kapanis_cta", "muzik_onerisi")


def render_script_md(data: dict[str, Any]) -> str:
    source = data.get("link") or "(kendi fikrin)"
    head = f"# {data['baslik']}\n\nKaynak: {source}\n\n"
    hook = f"**KANCA (ilk 2 sn):** {data['kanca']}\n\n" if data.get("kanca") else ""
    cta = f"\n**KAPANIŞ:** {data['kapanis_cta']}\n" if data.get("kapanis_cta") else ""
    return f"{head}{hook}{data['senaryo']}\n{cta}"


def save_item(item_dir: str | Path, data: dict[str, Any]) -> None:
    """Senaryo, metadata, çeviriler ve ses notunu yazar (görseller images.py'den gelir)."""
    d = Path(item_dir)
    write_text(d / "senaryo_tr.md", render_script_md(data))
    for lang, text in (data.get("ceviriler") or {}).items():
        write_text(d / "ceviriler" / f"{lang}.md", text.strip() + "\n")
    ensure_dir(d / "gorseller")
    write_text(d / "ses" / "OKU_BENI.txt", TR_VOICE_NOTE)
    if data.get("ekran_yazilari"):
        write_json(d / "ekran_yazilari.json", data["ekran_yazilari"])
    metadata = {
        "format": data.get("format", "yatay"),
        "baslik": data["baslik"],
        "kaynak_baslik": data.get("title"),
        "kaynak_url": data.get("link", ""),
        "yayin_tarihi": data.get("published"),
        "islenme_zamani": datetime.now().isoformat(timespec="seconds"),
        "ozet": data.get("ozet", ""),
        "senaryo": data.get("senaryo", ""),
        "etiketler": data.get("etiketler", []),
        "gorsel_promptleri": data.get("gorsel_promptleri", []),
        "gorseller": [Path(p).name for p in data.get("gorseller", [])],
        "ceviri_dilleri": sorted((data.get("ceviriler") or {}).keys()),
        "hatalar": data.get("hatalar", []),
        **{k: data[k] for k in EXTRA_META_KEYS if k in data},
        **({"content_id": data["content_id"]} if data.get("content_id") else {}),
        **({"idea_id": data["idea_id"]} if data.get("idea_id") else {}),
    }
    write_json(d / "metadata.json", metadata)


def existing_item_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir() and ITEM_DIR_RE.match(d.name))


def next_index(root: Path) -> int:
    """Aynı gün tekrar çalıştırılırsa numaralandırma kaldığı yerden sürer."""
    return max((int(d.name[:2]) for d in existing_item_dirs(root)), default=0) + 1


def unique_dir(path: Path) -> Path:
    """Var olan klasörü (ve içindeki ses kayıtlarını) asla ezmez."""
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}-{n}")
        n += 1
    return candidate


def write_day_index(date_str: str, cfg: dict[str, Any]) -> tuple[Path, Path]:
    """Gün klasöründeki TÜM haberlerin metadata'sından bulten.md ve manifest.json yazar."""
    return write_index(day_dir(date_str, cfg), date_str, cfg)


def write_index(root: Path, date_str: str, cfg: dict[str, Any], label: str = "Günlük Bülten") -> tuple[Path, Path]:
    """Verilen klasördeki (gün ya da gün/format) haberlerden bulten.md + manifest.json yazar."""
    site = (cfg.get("site") or {}).get("name", "Günlük Bülten")
    dirs = existing_item_dirs(root)
    lines = [f"# {site} — {label} {date_str}", "", f"Toplam haber: {len(dirs)}", ""]
    entries = []
    for idx, d in enumerate(dirs, start=1):
        meta = read_json(d / "metadata.json", default={}) or {}
        title = meta.get("baslik", d.name)
        lines += [
            f"## {d.name[:2]}. {title}",
            "",
            meta.get("ozet", ""),
            "",
            f"- Klasör: [{d.name}](./{d.name}/)",
            f"- Senaryo: [senaryo_tr.md](./{d.name}/senaryo_tr.md)",
            f"- Kaynak: {meta.get('kaynak_url', '')}",
            "",
        ]
        entries.append(
            {
                "sira": idx,
                "klasor": d.name,
                "baslik": title,
                "ozet": meta.get("ozet", ""),
                "kaynak_url": meta.get("kaynak_url", ""),
                "etiketler": meta.get("etiketler", []),
                "gorsel_sayisi": len(meta.get("gorseller", [])),
                "ceviri_dilleri": meta.get("ceviri_dilleri", []),
                "hatalar": meta.get("hatalar", []),
            }
        )
    index_path = write_text(root / "bulten.md", "\n".join(lines).rstrip() + "\n")
    manifest_path = write_json(
        root / "manifest.json",
        {
            "tarih": date_str,
            "site": site,
            "haber_sayisi": len(dirs),
            "diller": list(cfg["translate"].get("languages", [])),
            "haberler": entries,
        },
    )
    return index_path, manifest_path
