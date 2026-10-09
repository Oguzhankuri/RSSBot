"""Beyin hafızası: geçmiş içerikler, performans, puanlar, fikirler ve öğrenilmiş kurallar."""

from __future__ import annotations

import math
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

from bulten.db import Repo
from bulten.utils import slugify_tr

FEW_SHOT_COUNT = 2


def _norm(title: str) -> str:
    return " ".join(sorted(slugify_tr(title, max_len=200).split("-")))


def similarity(a: str, b: str) -> float:
    """0–1 arası başlık benzerliği (kelime sırasından bağımsız)."""
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def recent_titles(repo: Repo, days: int, today: str | None = None) -> list[str]:
    since = (date.fromisoformat(today) if today else date.today()) - timedelta(days=days)
    rows = repo.select("contents", since=("date", since.isoformat()))
    titles = [r.get("source_title") or "" for r in rows] + [r.get("title") or "" for r in rows]
    return [t for t in titles if t]


def filter_repeats(candidates: list[dict], recent: list[str], threshold: float) -> list[dict]:
    """Son günlerde işlenen konulara çok benzeyen adayları eler."""
    return [c for c in candidates if all(similarity(c["title"], t) < threshold for t in recent)]


def _latest_metrics(repo: Repo) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in repo.select("metrics", order_by="created_at"):
        latest[row["content_id"]] = row
    return latest


def _mean_ratings(repo: Repo) -> dict[str, float]:
    scores: dict[str, list[int]] = {}
    for row in repo.select("ratings"):
        scores.setdefault(row["content_id"], []).append(int(row["score"]))
    return {cid: sum(v) / len(v) for cid, v in scores.items()}


def performance_score(metric: dict | None, rating: float | None) -> float | None:
    """İzlenme (log ölçek) × izlenme yüzdesi + kullanıcı puanı. Veri yoksa None."""
    if metric is None and rating is None:
        return None
    score = 0.0
    if metric:
        views = float(metric.get("views") or 0)
        pct = float(metric.get("avg_view_pct") or 0) / 100
        score += math.log10(views + 10) * (0.5 + pct)
    if rating is not None:
        score += (rating - 3) * 0.5
    return round(score, 3)


def performance_table(repo: Repo, fmt: str | None = None) -> list[dict[str, Any]]:
    metrics, ratings = _latest_metrics(repo), _mean_ratings(repo)
    rows = []
    for content in repo.select("contents", {"format": fmt} if fmt else None):
        metric, rating = metrics.get(content["id"]), ratings.get(content["id"])
        score = performance_score(metric, rating)
        if score is None:
            continue
        rows.append(
            {
                "content": content,
                "views": (metric or {}).get("views"),
                "avg_view_pct": (metric or {}).get("avg_view_pct"),
                "rating": rating,
                "score": score,
            }
        )
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def active_insights(repo: Repo, fmt: str | None = None) -> list[dict]:
    rows = repo.select("insights", {"active": True})
    picked = [r for r in rows if not r.get("format") or r.get("format") == fmt or fmt is None]
    return sorted(picked, key=lambda r: (bool(r.get("approved")), float(r.get("confidence") or 0)), reverse=True)


def format_guidance(repo: Repo, fmt: str, limit: int = 8) -> str:
    """Senaryo prompt'una eklenen 'öğrenilmiş kurallar + iyi giden örnekler' metni."""
    lines: list[str] = []
    rules = active_insights(repo, fmt)[:limit]
    if rules:
        lines += ["", "Kanalın geçmiş performansından ÖĞRENİLMİŞ KURALLAR (bunlara uy):"]
        lines += [f"- {r['rule']}" for r in rules]
    best = performance_table(repo, fmt)[:FEW_SHOT_COUNT]
    if best:
        lines += ["", "Bu formatta EN İYİ performans gösteren geçmiş örnekler (tarzını örnek al, konuyu kopyalama):"]
        for row in best:
            c = row["content"]
            hook = f" | kanca: {c['hook']}" if c.get("hook") else ""
            lines.append(f"- \"{c['title']}\"{hook} | açılış: {(c.get('script') or '')[:160]}")
    return "\n".join(lines)


def planner_context(repo: Repo, ideas: list[dict], recent: list[str]) -> str:
    """Planlayıcıya verilen hafıza özeti."""
    lines = ["FİKİR KUTUSU (kullanıcının kendi fikirleri, öncelik 5 = acil):"]
    lines += [f"- [{i['id'][:6]}] (öncelik {i.get('priority', 3)}) {i['text'][:300]}" for i in ideas] or ["- (boş)"]
    rules = active_insights(repo)[:10]
    lines += ["", "ÖĞRENİLMİŞ KURALLAR:"] + ([f"- ({r.get('format') or 'genel'}) {r['rule']}" for r in rules] or ["- (henüz yok)"])
    table = performance_table(repo)
    if table:
        lines += ["", "EN İYİ GİDEN İÇERİKLER:"] + [f"- ({r['content']['format']}) {r['content']['title']}" for r in table[:5]]
        if len(table) > 5:
            lines += ["", "EN KÖTÜ GİDEN İÇERİKLER:"]
            lines += [f"- ({r['content']['format']}) {r['content']['title']}" for r in table[-3:]]
    if recent:
        lines += ["", "SON GÜNLERDE ZATEN İŞLENEN KONULAR (tekrar etme):"] + [f"- {t}" for t in recent[:30]]
    return "\n".join(lines)
