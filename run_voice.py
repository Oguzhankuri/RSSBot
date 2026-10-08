"""FAZ B — Çevirileri kullanıcının klon sesiyle seslendirir (Chatterbox, GPU)."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from bulten import organize
from bulten.config import ConfigError, load_config
from bulten.utils import read_text, setup_logging, today_str
from bulten.voice import VoiceError, VoiceSynthesizer

logger = logging.getLogger("run_voice")

ITEM_DIR_PATTERN = re.compile(r"^\d{2}-")


def find_jobs(day_root: Path, languages: list[str], overwrite: bool) -> list[tuple[Path, str, Path]]:
    """(çeviri dosyası, dil, hedef wav) listesi döndürür."""
    jobs = []
    for item_dir in sorted(p for p in day_root.iterdir() if p.is_dir() and ITEM_DIR_PATTERN.match(p.name)):
        for lang in languages:
            src = item_dir / "ceviriler" / f"{lang}.md"
            dst = item_dir / "ses" / f"{lang}.wav"
            if not src.exists():
                logger.warning("Çeviri yok, atlanıyor: %s", src)
                continue
            if dst.exists() and not overwrite:
                logger.info("Zaten var, atlanıyor: %s", dst)
                continue
            jobs.append((src, lang, dst))
    return jobs


def run(config_path: str, date_str: str, overwrite: bool = False, synth: Any | None = None) -> int:
    cfg = load_config(config_path, require_voice=True)
    day_root = organize.day_dir(date_str, cfg)
    if not day_root.exists():
        raise ConfigError(f"{day_root} bulunamadı. Önce bu tarih için run_text.py çalıştırın.")

    jobs = find_jobs(day_root, list(cfg["voice"]["languages"]), overwrite)
    if not jobs:
        logger.info("Üretilecek yeni ses yok.")
        return 0

    synth = synth or VoiceSynthesizer(cfg)
    failures = 0
    for i, (src, lang, dst) in enumerate(jobs, start=1):
        logger.info("[%d/%d] %s → %s", i, len(jobs), src.parent.parent.name, dst.name)
        try:
            synth.synthesize_to_file(read_text(src), lang, dst)
        except Exception as exc:  # noqa: BLE001 — bir dosya hatası diğerlerini durdurmamalı
            failures += 1
            logger.error("Ses üretilemedi (%s): %s", dst, exc)
    logger.info("BİTTİ: %d/%d ses dosyası üretildi.", len(jobs) - failures, len(jobs))
    return 1 if failures == len(jobs) else 0


def _valid_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Tarih biçimi YYYY-MM-DD olmalı") from exc
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="FAZ B: çevirileri klon sesle seslendir")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--date", type=_valid_date, default=None, help="YYYY-MM-DD (varsayılan bugün)")
    parser.add_argument("--overwrite", action="store_true", help="Var olan wav dosyalarını yeniden üret")
    setup_logging()
    args = parser.parse_args()
    try:
        sys.exit(run(args.config, args.date or today_str(), args.overwrite))
    except (ConfigError, VoiceError) as exc:
        logger.error("%s", exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
