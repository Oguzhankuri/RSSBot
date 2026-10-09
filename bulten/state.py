"""Daha önce işlenen haberleri takip ederek tekrarı engeller."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Mapping

from bulten.utils import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_SEEN_PATH = "state/seen.json"


def item_id(entry: Mapping[str, Any]) -> str:
    """RSS entry kimliği: link > id > başlık hash'i."""
    for key in ("link", "id"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    title = str(entry.get("title") or "").strip()
    return "sha1:" + hashlib.sha1(title.encode("utf-8")).hexdigest()


def load_seen(path: str | Path = DEFAULT_SEEN_PATH) -> set[str]:
    data = read_json(path, default=[])
    if not isinstance(data, list):
        logger.warning("%s beklenmeyen biçimde; boş kabul edildi.", path)
        return set()
    return {str(x) for x in data}


def mark_seen(urls: list[str], path: str | Path = DEFAULT_SEEN_PATH) -> set[str]:
    """Verilen kimlikleri kalıcı listeye ekler ve güncel kümeyi döndürür."""
    updated = load_seen(path) | {u for u in urls if u}
    write_json(path, sorted(updated))
    logger.info("%d haber kimliği kaydedildi (toplam %d).", len(urls), len(updated))
    return updated


# --- v2: veritabanı tabanlı tekrar engeli ---

LEGACY_IMPORT_FLAG = "legacy_seen_imported"


def import_legacy_seen(repo: Any, path: str | Path = DEFAULT_SEEN_PATH) -> int:
    """Eski state/seen.json kayıtlarını bir kez veritabanına taşır; aktarılan sayıyı döndürür."""
    from bulten.db import kv_get, kv_set

    if kv_get(repo, LEGACY_IMPORT_FLAG, False):
        return 0
    ids = sorted(load_seen(path))
    for seen_id in ids:
        repo.upsert("seen_items", {"id": seen_id})
    kv_set(repo, LEGACY_IMPORT_FLAG, True)
    if ids:
        logger.info("%d eski haber kimliği veritabanına taşındı.", len(ids))
    return len(ids)


def load_seen_db(repo: Any) -> set[str]:
    return {row["id"] for row in repo.select("seen_items")}


def mark_seen_db(repo: Any, ids: list[str]) -> None:
    for seen_id in ids:
        if seen_id:
            repo.upsert("seen_items", {"id": seen_id})
