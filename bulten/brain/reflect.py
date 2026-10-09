"""Öğrenme döngüsü: performans + puanlar → 'öğrenilmiş kurallar' (insights).

Model fine-tune edilmez; kurallar veritabanında saklanır ve her yeni senaryo
prompt'una eklenir. Kullanıcının onayladığı kurallar asla otomatik silinmez.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bulten.brain import memory
from bulten.db import Repo
from bulten.rewrite import _clean_json_text

logger = logging.getLogger(__name__)

MIN_ITEMS = 3
MAX_RULES = 10
MAX_ROWS = 60

REFLECT_SYSTEM = """Sen bir YouTube kanal analistisin. Kanalın geçmiş içeriklerini ve performanslarını inceleyip, gelecekteki senaryolar için UYGULANABİLİR kurallar çıkarırsın.

Kurallar:
- Her kural tek cümle, emir kipinde ve somut olsun (ör. "Dikey videolarda kancayı soru cümlesiyle kur.").
- Yalnızca verinin desteklediği kuralları yaz; "kanit" = kuralı destekleyen içerik sayısı.
- "guven" 0–1 arası; az veri = düşük güven.
- "format": "yatay", "dikey" ya da null (ikisi için de geçerli).
- En fazla {max_rules} kural. Mevcut onaylı kurallarla çelişme.

Yanıtı YALNIZCA şu JSON olarak ver:
{{"kurallar": [{{"kural": "...", "format": "dikey", "guven": 0.6, "kanit": 4}}], "ozet": "1-2 cümle genel değerlendirme"}}"""


def build_dataset(repo: Repo) -> list[dict[str, Any]]:
    rows = []
    for row in memory.performance_table(repo)[:MAX_ROWS]:
        c = row["content"]
        rows.append(
            {
                "format": c["format"],
                "baslik": c["title"],
                "kanca": c.get("hook"),
                "etiketler": c.get("tags", []),
                "kelime": (c.get("features") or {}).get("words"),
                "fikirden": bool(c.get("idea_id")),
                "izlenme": row["views"],
                "izlenme_yuzdesi": row["avg_view_pct"],
                "puan": row["rating"],
                "skor": row["score"],
            }
        )
    return rows


def _parse_rules(raw: str) -> tuple[list[dict[str, Any]], str]:
    data = json.loads(_clean_json_text(raw))
    rules = []
    for entry in data.get("kurallar") or []:
        text = str((entry or {}).get("kural") or "").strip()
        if not text:
            continue
        fmt = entry.get("format") if entry.get("format") in ("yatay", "dikey") else None
        try:
            confidence = min(1.0, max(0.0, float(entry.get("guven", 0.5))))
            evidence = max(0, int(entry.get("kanit", 0)))
        except (TypeError, ValueError):
            confidence, evidence = 0.5, 0
        rules.append({"rule": text[:300], "format": fmt, "confidence": confidence, "evidence": evidence})
    return rules[:MAX_RULES], str(data.get("ozet") or "")


def reflect(repo: Repo, client: Any) -> dict[str, Any]:
    """Yeni kuralları üretir; onaysız eski kuralları pasifleştirir. Sonucu özetler."""
    dataset = build_dataset(repo)
    if len(dataset) < MIN_ITEMS:
        return {"rules": [], "summary": f"Öğrenmek için en az {MIN_ITEMS} ölçülmüş/puanlanmış içerik gerekli (şu an {len(dataset)})."}
    approved = [r for r in memory.active_insights(repo) if r.get("approved")]
    user = (
        "ONAYLI KURALLAR:\n" + ("\n".join(f"- {r['rule']}" for r in approved) or "- yok")
        + "\n\nİÇERİK PERFORMANSI (skor yüksek = iyi):\n" + json.dumps(dataset, ensure_ascii=False)
    )
    raw = client.chat(REFLECT_SYSTEM.format(max_rules=MAX_RULES), user, temperature=0.3, json_mode=True)
    rules, summary = _parse_rules(raw)
    if not rules:
        return {"rules": [], "summary": summary or "Model yeni kural önermedi."}

    for old in repo.select("insights", {"active": True}):
        if not old.get("approved"):
            repo.update("insights", old["id"], {"active": False})
    created = [repo.insert("insights", {**r, "active": True, "approved": False}) for r in rules]
    logger.info("Beyin %d yeni kural öğrendi.", len(created))
    return {"rules": created, "summary": summary}


def add_manual_rule(repo: Repo, text: str, fmt: str | None = None) -> dict:
    """Kullanıcının elle yazdığı kural: onaylı ve tam güvenli."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("Kural boş olamaz.")
    return repo.insert(
        "insights",
        {"rule": text[:300], "format": fmt if fmt in ("yatay", "dikey") else None,
         "confidence": 1.0, "evidence": 0, "active": True, "approved": True},
    )
