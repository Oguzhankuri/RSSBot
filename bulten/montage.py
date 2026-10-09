"""Grafikçiler için montaj notları (MONTAJ_NOTU.md) ve günlük teslim özeti (TESLIM.md)."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from bulten import formats, organize
from bulten.utils import read_json, write_text

SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
DIKEY_SAFE_ZONE = "Yazıları üst %15 ve alt %20 bandının dışında tut (platform arayüzü orayı kapatır)."


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.split(text.strip()) if s.strip()]


def word_count(text: str) -> int:
    return len(text.split())


def estimate_seconds(text: str, wps: float) -> int:
    return max(1, math.ceil(word_count(text) / wps))


def build_scenes(script: str, images: list[str], wps: float) -> list[dict[str, Any]]:
    """Cümleleri görsel sayısı kadar sahneye eşit böler; her sahneye süre ve görsel atar."""
    sentences = split_sentences(script) or [script]
    count = max(1, min(len(images) or 1, len(sentences)))
    size = math.ceil(len(sentences) / count)
    scenes, start = [], 0
    for idx in range(count):
        chunk = " ".join(sentences[idx * size : (idx + 1) * size])
        if not chunk:
            continue
        seconds = estimate_seconds(chunk, wps)
        scenes.append(
            {
                "no": idx + 1,
                "baslangic": start,
                "sure": seconds,
                "gorsel": images[idx] if idx < len(images) else "(görsel yok — stok/arka plan kullan)",
                "metin": chunk,
            }
        )
        start += seconds
    return scenes


def _fmt_time(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _file_checklist(folder: Path, languages: list[str]) -> list[str]:
    def mark(path: Path) -> str:
        return "✅" if path.exists() else "❌"

    images = sorted((folder / "gorseller").glob("*.png"))
    lines = [
        f"- {mark(folder / 'senaryo_tr.md')} senaryo_tr.md",
        f"- {'✅' if images else '❌'} gorseller/ ({len(images)} adet)",
        f"- {mark(folder / 'ses' / 'tr.wav')} ses/tr.wav (senin sesin)",
    ]
    lines += [f"- {mark(folder / 'ses' / f'{lang}.wav')} ses/{lang}.wav" for lang in languages]
    return lines


def build_montage_note(folder: Path, meta: dict[str, Any], profile: formats.Profile, languages: list[str]) -> str:
    body = meta.get("senaryo") or ""
    images = [f"gorseller/{name}" for name in meta.get("gorseller", [])]
    wps = float(profile.get("speech_wps", 2.3))
    scenes = build_scenes(body, images, wps)
    total = sum(s["sure"] for s in scenes)

    lines = [
        f"# MONTAJ NOTU — {meta.get('baslik', folder.name)}",
        "",
        f"- **Format:** {profile['label']} — {profile.get('aspect', '')}",
        f"- **Tahmini süre (TR):** ~{_fmt_time(total)}",
        f"- **Kaynak:** {meta.get('kaynak_url') or 'kendi fikrimiz'}",
        "",
        "## Dosyalar",
        *_file_checklist(folder, languages),
        "",
    ]
    if profile["name"] == "dikey":
        lines += _vertical_section(meta)
    else:
        lines += [
            "## Görsel dil",
            "- Alt bant (lower third): video içi başlık → " + f"\"{meta.get('baslik', '')}\"",
            "- Geçişler: yumuşak çapraz geçiş (0.3–0.5 sn), görsellerde hafif Ken Burns zoom.",
            "",
        ]
    lines += ["## Sahne akışı", "", "| # | Zaman | Süre | Görsel | Metin |", "|---|---|---|---|---|"]
    lines += [
        f"| {s['no']} | {_fmt_time(s['baslangic'])} | {s['sure']} sn | {s['gorsel']} | {s['metin']} |" for s in scenes
    ]
    return "\n".join(lines).rstrip() + "\n"


def _vertical_section(meta: dict[str, Any]) -> list[str]:
    lines = ["## Shorts formülü", ""]
    if meta.get("kanca"):
        lines += [f"- **00:00–00:02 KANCA:** {meta['kanca']} — büyük punto, ilk karede ekranda olsun."]
    if meta.get("kapanis_cta"):
        lines += [f"- **Kapanış:** {meta['kapanis_cta']}"]
    if meta.get("muzik_onerisi"):
        lines += [f"- **Müzik:** {meta['muzik_onerisi']}"]
    if meta.get("altyazi_vurgulari"):
        lines += [f"- **Altyazıda renkli vurgula:** {', '.join(meta['altyazi_vurgulari'])}"]
    lines += [f"- {DIKEY_SAFE_ZONE}", ""]
    if meta.get("ekran_yazilari"):
        lines += ["### Ekran yazıları", "", "| Saniye | Yazı |", "|---|---|"]
        lines += [f"| {e['saniye']} | {e['metin']} |" for e in meta["ekran_yazilari"]]
        lines += [""]
    return lines


def write_montage_notes(date_str: str, cfg: dict[str, Any]) -> list[Path]:
    languages = list(cfg["voice"].get("languages", [])) if cfg["voice"].get("enabled", True) else []
    written = []
    for profile in formats.enabled_profiles(cfg):
        root = organize.format_dir(date_str, profile["name"], cfg)
        for folder in organize.existing_item_dirs(root):
            meta = read_json(folder / "metadata.json", default={}) or {}
            written.append(write_text(folder / "MONTAJ_NOTU.md", build_montage_note(folder, meta, profile, languages)))
    return written


def write_delivery(date_str: str, cfg: dict[str, Any]) -> Path:
    """Günün grafikçi teslim özeti: format format içerik listesi ve eksik dosya uyarıları."""
    languages = list(cfg["voice"].get("languages", [])) if cfg["voice"].get("enabled", True) else []
    site = (cfg.get("site") or {}).get("name", "Günlük Bülten")
    lines = [f"# {site} — TESLİM {date_str}", "", "Her klasörde MONTAJ_NOTU.md var; önce onu oku.", ""]
    for profile in formats.enabled_profiles(cfg):
        root = organize.format_dir(date_str, profile["name"], cfg)
        folders = organize.existing_item_dirs(root)
        lines += [f"## {profile['label']} — {len(folders)} içerik", ""]
        for folder in folders:
            meta = read_json(folder / "metadata.json", default={}) or {}
            missing = [ln[4:] for ln in _file_checklist(folder, languages) if ln.startswith("- ❌")]
            status = "✅ hazır" if not missing else "⚠️ eksik: " + "; ".join(missing)
            lines.append(f"- [{folder.name}](./{profile['name']}/{folder.name}/) — {meta.get('baslik', '')} — {status}")
        lines.append("")
    return write_text(organize.day_dir(date_str, cfg) / "TESLIM.md", "\n".join(lines).rstrip() + "\n")
