"""Fikir kutusu: fikirler önce kaydedilir (asla kaybolmaz), sonra AI ile zenginleştirilir."""

from __future__ import annotations

import json
import logging
from typing import Any

from bulten.db import Repo, now_iso

logger = logging.getLogger(__name__)

MAX_IDEA_CHARS = 2000
STATUSES = ("yeni", "kullanildi", "arsiv")
PRIORITY_RANGE = range(1, 6)
VALID_FORMATS = ("yatay", "dikey")

ENRICH_SYSTEM = (
    "Sen bir YouTube haber kanalının içerik editörüsün. Verilen ham fikri sınıflandır. "
    "Yanıtı YALNIZCA şu JSON olarak ver: "
    '{"kategori": "tek kelime/kısa", "etiketler": ["2-4 Türkçe etiket"], "format": "dikey" | "yatay"}. '
    "Hızlı, tek mesajlı, merak uyandıran fikirler dikey (Shorts); derin, çok başlıklı konular yatay."
)


class IdeaError(ValueError):
    """Geçersiz fikir girdisi."""


def _clean_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        raise IdeaError("Fikir boş olamaz.")
    if len(cleaned) > MAX_IDEA_CHARS:
        raise IdeaError(f"Fikir en fazla {MAX_IDEA_CHARS} karakter olabilir.")
    return cleaned


def _check_priority(priority: int) -> int:
    value = int(priority)
    if value not in PRIORITY_RANGE:
        raise IdeaError("Öncelik 1 ile 5 arasında olmalı.")
    return value


def add_idea(
    repo: Repo,
    text: str,
    source: str = "panel",
    priority: int = 3,
    client: Any | None = None,
    idea_id: str | None = None,
) -> dict:
    """Fikri HEMEN kaydeder; AI zenginleştirmesi başarısız olsa bile fikir kalır.

    idea_id verilirse (ör. Telegram mesaj kimliği) aynı fikir iki kez kaydedilemez: RepoError.
    """
    row = repo.insert(
        "ideas",
        {
            **({"id": idea_id} if idea_id else {}),
            "text": _clean_text(text),
            "source": source,
            "priority": _check_priority(priority),
            "status": "yeni",
            "tags": [],
            "used_in": [],
        },
    )
    if client is None:
        return row
    try:
        return repo.update("ideas", row["id"], enrich(row["text"], client))
    except Exception as exc:  # noqa: BLE001 — zenginleştirme opsiyonel
        logger.warning("Fikir zenginleştirilemedi (fikir kaydedildi): %s", exc)
        return row


def enrich(text: str, client: Any) -> dict[str, Any]:
    raw = client.chat(ENRICH_SYSTEM, text, temperature=0.3, json_mode=True)
    data = json.loads(raw)
    fmt = data.get("format") if data.get("format") in VALID_FORMATS else None
    tags = [str(t).strip() for t in data.get("etiketler") or [] if str(t).strip()][:4]
    return {"category": str(data.get("kategori") or "").strip()[:40] or None, "tags": tags, "suggested_format": fmt}


def list_ideas(repo: Repo, status: str | None = None) -> list[dict]:
    """Önce yüksek öncelik, aynı öncelikte en yeni fikir üstte."""
    rows = repo.select("ideas", {"status": status} if status else None, order_by="created_at", desc=True)
    return sorted(rows, key=lambda r: -int(r.get("priority") or 3))


def list_open(repo: Repo, limit: int = 20) -> list[dict]:
    return list_ideas(repo, "yeni")[:limit]


def find_by_prefix(repo: Repo, prefix: str) -> dict | None:
    """Telegram'da kısa kimlikle (/sil a1b2) işlem yapabilmek için."""
    prefix = prefix.strip().lower()
    if len(prefix) < 3:
        return None
    matches = [r for r in repo.select("ideas") if r["id"].startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def set_priority(repo: Repo, idea_id: str, priority: int) -> dict:
    return repo.update("ideas", idea_id, {"priority": _check_priority(priority)})


def set_status(repo: Repo, idea_id: str, status: str) -> dict:
    if status not in STATUSES:
        raise IdeaError(f"Durum şunlardan biri olmalı: {STATUSES}")
    return repo.update("ideas", idea_id, {"status": status})


def edit_text(repo: Repo, idea_id: str, text: str) -> dict:
    return repo.update("ideas", idea_id, {"text": _clean_text(text)})


def mark_used(repo: Repo, idea_id: str, content_id: str) -> dict | None:
    idea = repo.get("ideas", idea_id)
    if idea is None:
        return None
    used = [*(idea.get("used_in") or []), content_id]
    return repo.update("ideas", idea_id, {"status": "kullanildi", "used_in": used, "updated_at": now_iso()})


def short_id(idea: dict) -> str:
    return idea["id"][:6]
