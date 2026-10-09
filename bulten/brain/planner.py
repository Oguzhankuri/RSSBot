"""Günün planı: RSS gündemi + fikir kutusu + hafıza → yatay ve dikey için konu seçimi."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from bulten import ideas as ideas_mod
from bulten import ingest
from bulten.brain import memory
from bulten.db import Repo
from bulten.rewrite import _clean_json_text

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """Sen bir YouTube haber kanalının yayın planlayıcısısın. Bugünün haber adaylarını, kullanıcının fikir kutusunu ve kanalın geçmiş performansını harmanlayarak günün içerik planını yaparsın.

Kurallar:
- YATAY bülten için: önemli, geniş kitleyi ilgilendiren, birbirinden farklı haberler seç ({yatay_n} adet, öncelik sırasıyla).
- DİKEY Shorts için ({dikey_n} adet): tek cümlede anlatılabilen, şaşırtıcı, merak uyandıran konular seç. Fikir kutusundaki uygun fikirleri KULLAN (özellikle yüksek öncelikliler); bir fikri bir haberle birleştirebilirsin.
- Son günlerde işlenen konuları tekrar etme. Öğrenilmiş kurallara uy.
- Her dikey seçim için kısa bir "aci" (hangi açıdan anlatılacak) yaz.

Yanıtı YALNIZCA şu JSON olarak ver:
{{"yatay": [haber_no, ...], "dikey": [{{"haber_no": 3 | null, "fikir_id": "a1b2c3" | null, "aci": "..."}}], "gerekce": "1-3 cümle"}}"""


def _candidate_lines(pool: list[dict]) -> str:
    return "\n".join(f"{i}. {c['title']} — {c.get('summary', '')[:200]}" for i, c in enumerate(pool))


def _idea_item(idea: dict, angle: str) -> dict[str, Any]:
    text = idea["text"] + (f"\n\nAnlatım açısı: {angle}" if angle else "")
    return {
        "id": f"fikir:{idea['id']}",
        "title": idea["text"][:80],
        "link": "",
        "published": "",
        "summary": idea["text"][:200],
        "text": text,
        "idea_id": idea["id"],
    }


def _ask_llm(client: Any, pool: list[dict], context: str, counts: dict[str, int]) -> dict[str, Any]:
    system = PLANNER_SYSTEM.format(yatay_n=counts.get("yatay", 0), dikey_n=counts.get("dikey", 0))
    user = f"{context}\n\nBUGÜNÜN HABER ADAYLARI:\n{_candidate_lines(pool)}"
    raw = client.chat(system, user, temperature=0.4, json_mode=True)
    return json.loads(_clean_json_text(raw))


def _valid_index(value: Any, size: int) -> int | None:
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return None
    return idx if 0 <= idx < size else None


def _ranked_news(indices: list[Any], pool: list[dict]) -> list[dict]:
    """LLM sırası + kalan adaylar (yedek): kısa çıkan haber elenirse sıradaki gelir."""
    picked = [pool[i] for i in (_valid_index(x, len(pool)) for x in indices) if i is not None]
    seen = {p["id"] for p in picked}
    return picked + [c for c in pool if c["id"] not in seen]


def _vertical_items(choices: list[Any], pool: list[dict], open_ideas: list[dict]) -> tuple[list[dict], list[dict]]:
    """(fikirden doğan hazır öğeler, tam metin çekilecek haber öğeleri) döndürür."""
    by_prefix = {i["id"][:6]: i for i in open_ideas}
    idea_items, news = [], []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        angle = str(choice.get("aci") or "").strip()
        idea = by_prefix.get(str(choice.get("fikir_id") or "")[:6])
        idx = _valid_index(choice.get("haber_no"), len(pool))
        if idx is not None:
            extra = {"aci": angle, **({"idea_id": idea["id"]} if idea else {})}
            news.append({**pool[idx], **extra})
        elif idea:
            idea_items.append(_idea_item(idea, angle))
    return idea_items, news


def plan_day(
    candidates: list[dict],
    cfg: dict[str, Any],
    repo: Repo,
    profiles: list[dict],
    client: Any | None = None,
    today: str | None = None,
    text_fetcher: Callable[[str], str | None] = ingest.fetch_full_text,
) -> dict[str, Any]:
    bcfg = cfg["brain"]
    counts = {p["name"]: int(p["max_items"]) for p in profiles}
    recent = memory.recent_titles(repo, int(bcfg["repeat_days"]), today)
    pool = memory.filter_repeats(candidates, recent, float(bcfg["repeat_threshold"]))[: int(bcfg["candidate_pool"])]
    open_ideas = ideas_mod.list_open(repo)

    decision: dict[str, Any] = {}
    if bcfg.get("enabled", True) and client is not None and (pool or open_ideas):
        try:
            decision = _ask_llm(client, pool, memory.planner_context(repo, open_ideas, recent), counts)
        except Exception as exc:  # noqa: BLE001 — beyin çökerse en yeni haberlerle devam
            logger.warning("Planlayıcı yanıtı kullanılamadı, en yeni haberler seçilecek: %s", exc)

    plan: dict[str, Any] = {"gerekce": str(decision.get("gerekce") or "Otomatik: en yeni haberler.")}
    if "yatay" in counts:
        ranked = _ranked_news(decision.get("yatay") or [], pool)
        plan["yatay"] = ingest.hydrate(ranked, cfg, counts["yatay"], text_fetcher)
    if "dikey" in counts:
        idea_items, news = _vertical_items(decision.get("dikey") or [], pool, open_ideas)
        need = max(0, counts["dikey"] - len(idea_items))
        fallback = [c for c in pool if c["id"] not in {n["id"] for n in news}]
        plan["dikey"] = (idea_items + ingest.hydrate(news + fallback, cfg, need, text_fetcher))[: counts["dikey"]]
    logger.info("Plan hazır: %s", {k: len(v) for k, v in plan.items() if isinstance(v, list)})
    return plan
