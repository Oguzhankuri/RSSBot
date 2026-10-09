"""FAZ A — RSS → Türkçe senaryo → çeviriler → görseller → klasörleme (tam otomatik)."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

from bulten import images, ingest, organize, rewrite, state, translate
from bulten.config import ConfigError, load_config
from bulten.llm import DeepSeekClient
from bulten.utils import setup_logging, today_str

logger = logging.getLogger("run_text")


def process_item(
    item: dict[str, Any],
    item_dir: Path,
    cfg: dict[str, Any],
    client: DeepSeekClient,
    backend: images.ImageBackend,
) -> dict[str, Any]:
    """Tek haberi işler; hatalar 'hatalar' listesine yazılır, istisna yukarı taşınmaz."""
    errors: list[str] = []
    try:
        script = rewrite.rewrite_item(item, cfg, client)
    except Exception as exc:  # noqa: BLE001
        logger.error("Senaryo üretilemedi: %s", exc)
        script = rewrite.fallback_script(item)
        errors.append(f"senaryo: {exc}")
    if script.get("uyari"):
        errors.append(script["uyari"])

    translations, t_errors = translate.translate_all(script["senaryo"], cfg, client)
    errors += [f"ceviri/{lang}: {msg}" for lang, msg in t_errors.items()]

    saved_images, i_errors = images.generate_images(
        script["gorsel_promptleri"], item_dir / "gorseller", cfg, backend
    )
    errors += [f"gorsel/{msg}" for msg in i_errors]

    data = {**item, **script, "ceviriler": translations, "gorseller": saved_images, "hatalar": errors}
    organize.save_item(item_dir, data)
    return data


def is_complete(data: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Senaryo gerçekse, en az bir çeviri ve en az bir görsel varsa haber "görüldü" sayılır."""
    tcfg = cfg["translate"]
    needs_translation = tcfg.get("enabled", True) and bool(tcfg.get("languages"))
    return (
        not data.get("uyari")
        and bool(data["gorseller"])
        and (bool(data["ceviriler"]) or not needs_translation)
    )


def run(config_path: str, date_str: str | None = None) -> int:
    cfg = load_config(config_path, require_text=True)
    date_str = date_str or today_str()
    seen_path = Path(state.DEFAULT_SEEN_PATH)

    items = ingest.fetch_feed_items(cfg, seen=state.load_seen(seen_path))
    if not items:
        logger.warning("İşlenecek yeni haber yok. (Hepsi daha önce işlenmiş olabilir: %s)", seen_path)
        return 0

    # Görsel altyapısı yoksa DeepSeek kotası harcanmadan ve haberler "görüldü" sayılmadan dur.
    backend = images.create_backend(cfg)
    client = DeepSeekClient(cfg)

    # Klasör adları DeepSeek başlığından türediği için senaryo önce, klasör sonra.
    results: list[dict[str, Any]] = []
    root = organize.day_dir(date_str, cfg)
    start = organize.next_index(root)
    for offset, item in enumerate(items):
        idx = start + offset
        logger.info("[%d/%d] %s", offset + 1, len(items), item["title"])
        tmp_dir = root / f"_{idx:02d}-isleniyor"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        try:
            data = process_item(item, tmp_dir, cfg, client, backend)
            tmp_dir.rename(organize.unique_dir(root / organize.item_dir_name(idx, data["baslik"])))
            results.append(data)
            if is_complete(data, cfg):
                state.mark_seen([item["id"]], seen_path)
            else:
                logger.warning("Haber eksik üretildi; bir sonraki çalıştırmada tekrar denenecek.")
        except Exception as exc:  # noqa: BLE001 — bir haber çökerse diğerleri sürsün
            logger.exception("Haber işlenemedi, atlanıyor: %s — %s", item["title"], exc)
            shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info("%d/%d haber işlendi…", offset + 1, len(items))

    if not results:
        logger.error("Hiçbir haber başarıyla işlenemedi.")
        return 1

    index_path, _ = organize.write_day_index(date_str, cfg)
    image_count = sum(len(r["gorseller"]) for r in results)
    error_count = sum(1 for r in results if r["hatalar"])
    if image_count == 0:
        logger.error('HİÇ GÖRSEL ÜRETİLEMEDİ. GPU/VRAM yetersiz olabilir; images.provider: "hf_api" deneyin.')
    logger.info("=" * 60)
    logger.info("BİTTİ: %d haber, %d görsel. Uyarılı haber: %d", len(results), image_count, error_count)
    logger.info("Çıktı: %s", index_path.parent.resolve())
    logger.info("Sıradaki adım: senaryo_tr.md'leri kendi sesinle oku, ses/tr.wav olarak ekle; sonra run_voice.py")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="FAZ A: haber → senaryo + çeviri + görsel")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--date", help="Çıktı klasörü tarihi (YYYY-MM-DD), varsayılan bugün")
    setup_logging()
    args = parser.parse_args()
    try:
        sys.exit(run(args.config, args.date))
    except (ConfigError, ingest.IngestError, images.ImageGenerationError) as exc:
        logger.error("%s", exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
