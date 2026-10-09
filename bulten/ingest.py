"""RSS okuma (feedparser) + makale tam metni (trafilatura)."""

from __future__ import annotations

import calendar
import logging
import re
from html import unescape
from typing import Any, Callable

import feedparser
import requests
import trafilatura

from bulten import state

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 GunlukBulten/1.0"
)
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": USER_AGENT}


class IngestError(Exception):
    """Hiçbir RSS kaynağına erişilemediğinde fırlatılır."""


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _published_ts(entry: Any) -> float:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return float(calendar.timegm(parsed)) if parsed else 0.0


def _read_feed(url: str) -> list[dict[str, Any]]:
    """Tek bir feed'i okur; ağ hatasında boş liste değil, istisna fırlatır."""
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"RSS ayrıştırılamadı: {parsed.get('bozo_exception')}")
    return [
        {
            "id": state.item_id(e),
            "title": _strip_html(e.get("title", "")),
            "link": e.get("link", ""),
            "published": e.get("published") or e.get("updated") or "",
            "published_ts": _published_ts(e),
            "summary": _strip_html(e.get("summary") or e.get("description") or ""),
        }
        for e in parsed.entries
    ]


def fetch_full_text(url: str) -> str | None:
    """Makale sayfasını indirip ana metni çıkarır; başarısızsa None."""
    if not url:
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        text = trafilatura.extract(resp.content, include_comments=False, include_tables=False)
        return text.strip() if text else None
    except requests.RequestException as exc:
        logger.warning("Tam metin çekilemedi (%s): %s", url, exc)
        return None


def collect_entries(feeds: list[str], reader: Callable[[str], list[dict]] = _read_feed) -> list[dict]:
    entries: list[dict] = []
    failures = 0
    for url in feeds:
        try:
            got = reader(url)
            logger.info("RSS okundu: %s (%d kayıt)", url, len(got))
            entries.extend(got)
        except Exception as exc:  # noqa: BLE001 — tek feed hatası akışı durdurmamalı
            failures += 1
            logger.error("RSS okunamadı, atlanıyor: %s — %s", url, exc)
    if feeds and failures == len(feeds):
        raise IngestError("Hiçbir RSS kaynağına erişilemedi. config.yaml 'feeds' adreslerini kontrol edin.")
    return entries


def fetch_candidates(
    cfg: dict[str, Any],
    seen: set[str] | None = None,
    reader: Callable[[str], list[dict]] = _read_feed,
) -> list[dict[str, Any]]:
    """Tüm feed'lerden tekil, daha önce işlenmemiş, en yeniden eskiye aday listesi (tam metin YOK)."""
    icfg = cfg["ingest"]
    entries = collect_entries([str(f) for f in cfg["feeds"] if f], reader)

    unique: dict[str, dict] = {}
    for e in entries:
        unique.setdefault(e["id"], e)
    candidates = sorted(unique.values(), key=lambda e: e["published_ts"], reverse=True)

    if icfg.get("dedupe", True):
        seen_ids = seen if seen is not None else state.load_seen()
        before = len(candidates)
        candidates = [e for e in candidates if e["id"] not in seen_ids]
        logger.info("Tekrar engeli: %d haber daha önce işlenmiş, atlandı.", before - len(candidates))
    return candidates


def hydrate(
    candidates: list[dict[str, Any]],
    cfg: dict[str, Any],
    limit: int,
    text_fetcher: Callable[[str], str | None] = fetch_full_text,
) -> list[dict[str, Any]]:
    """Sıradaki adaylara tam metin ekler; çok kısa olanları eler, `limit` kadar haber döndürür."""
    icfg = cfg["ingest"]
    min_chars = int(icfg.get("min_chars", 200))
    items: list[dict[str, Any]] = []
    for e in candidates:
        if len(items) >= limit:
            break
        text = e.get("text") or (text_fetcher(e["link"]) if icfg.get("fetch_full_text", True) else None)
        text = text or e.get("summary", "")
        if len(text) < min_chars:
            logger.info("Çok kısa (%d karakter), elendi: %s", len(text), e["title"])
            continue
        items.append(
            {
                "id": e["id"],
                "title": e["title"],
                "link": e["link"],
                "published": e.get("published", ""),
                "summary": e.get("summary", ""),
                "text": text,
                **{k: e[k] for k in ("idea_id", "aci") if e.get(k)},
            }
        )
    return items


def fetch_feed_items(
    cfg: dict[str, Any],
    seen: set[str] | None = None,
    reader: Callable[[str], list[dict]] = _read_feed,
    text_fetcher: Callable[[str], str | None] = fetch_full_text,
) -> list[dict[str, Any]]:
    """Feed'lerden işlenmeye hazır en yeni haberleri döndürür."""
    candidates = fetch_candidates(cfg, seen, reader)
    items = hydrate(candidates, cfg, int(cfg["ingest"].get("max_items", 8)), text_fetcher)
    logger.info("İşlenecek haber sayısı: %d", len(items))
    return items
