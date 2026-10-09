"""Adım makinesi: günü başlatır, sırası gelen otomatik adımları çalıştırır, sırayı devreder."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from bulten.db import Repo, RepoError
from bulten.pipeline import model
from bulten.pipeline.tasks import AUTO_TASKS, USER_CHECKS, Ctx, Deps

logger = logging.getLogger(__name__)


STALE_AFTER = timedelta(hours=3)  # Colab'da 8+3 haberin görselleri bile bundan kısa sürer


class PipelineBusy(RuntimeError):
    """Başka bir süreç (panel ya da Colab) aynı günü zaten işliyor."""


def ensure_run(repo: Repo, cfg: dict[str, Any], date_str: str) -> dict:
    """Günün kaydını ve adımlarını oluşturur; zaten varsa olduğu gibi döndürür."""
    run_id = model.run_id_for(date_str)
    run = repo.get("runs", run_id)
    if run is None:
        try:
            run = repo.insert("runs", {"id": run_id, "date": date_str, "status": "aktif", "plan": None})
        except RepoError:
            run = repo.get("runs", run_id)  # aynı anda iki yerden başlatıldı
    existing = {s["key"] for s in repo.select("run_steps", {"run_id": run_id})}
    for position, sdef in enumerate(model.STEPS, start=1):
        if sdef.key in existing:
            continue
        _insert_step(
            repo,
            {
                "id": model.step_id(run_id, sdef.key),
                "run_id": run_id,
                "key": sdef.key,
                "position": position,
                "actor": model.actor_for(sdef, cfg),
                "status": model.WAITING,
                "message": None,
            },
        )
    return run


def _insert_step(repo: Repo, row: dict) -> None:
    """Aynı anda iki süreç başlatırsa var olan adımın durumu sıfırlanmaz."""
    try:
        repo.insert("run_steps", row)
    except RepoError as exc:
        if not exc.conflict:
            raise


def _is_live(row: dict) -> bool:
    stamp = row.get("updated_at") or row.get("created_at")
    if not stamp:
        return True
    when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - when < STALE_AFTER


def list_steps(repo: Repo, run_id: str) -> list[dict]:
    return sorted(repo.select("run_steps", {"run_id": run_id}), key=lambda s: s["position"])


def _set(repo: Repo, row: dict, status: str, message: str | None = None) -> dict:
    return repo.update("run_steps", row["id"], {"status": status, "message": message})


def turn_for_date(repo: Repo, date_str: str) -> model.Turn | None:
    steps = list_steps(repo, model.run_id_for(date_str))
    return model.current_turn(steps) if steps else None


def advance(
    repo: Repo,
    cfg: dict[str, Any],
    date_str: str,
    actors: Iterable[str] = (model.PC,),
    only: Iterable[str] | None = None,
    deps: Deps | None = None,
    force: bool = False,
) -> model.Turn:
    """Sıradaki adımları, verilen aktörlere ait oldukça çalıştırır; başkasına geçince durur.

    actors: bu süreç hangi işleri yapabilir (PC'deki panel: pc; Colab: colab).
    only: yalnızca bu adımlar (Colab'da kütüphane çakışması yüzünden images ve voices ayrı çalışır).
    """
    actors, only_set = set(actors), set(only) if only else None
    run = ensure_run(repo, cfg, date_str)
    steps = list_steps(repo, run["id"])
    if not force and any(s["status"] == model.RUNNING and _is_live(s) for s in steps):
        raise PipelineBusy("Bu gün zaten başka bir yerde işleniyor. Takıldıysa paneldeki 'Kilidi aç' ile sıfırla.")
    ctx = Ctx(cfg=cfg, repo=repo, date=date_str, run=run, deps=deps or Deps())

    for row in steps:
        if row["status"] in model.FINISHED:
            continue
        sdef = model.STEP_BY_KEY[row["key"]]
        if model.should_skip(sdef, cfg):
            _set(repo, row, model.SKIPPED, "Yapılandırmada kapalı.")
            continue
        if row["key"] in USER_CHECKS:
            done, message = USER_CHECKS[row["key"]](ctx)
            if done:
                _set(repo, row, model.DONE, message)
                continue
            _set(repo, row, model.QUEUED, message)
            break
        if row["actor"] not in actors or (only_set is not None and row["key"] not in only_set):
            if row["status"] != model.FAILED:
                _set(repo, row, model.QUEUED, sdef.hint)
            break
        _set(repo, row, model.RUNNING, sdef.hint)
        logger.info("▶ %s", sdef.label)
        try:
            message = AUTO_TASKS[row["key"]](ctx)
        except Exception as exc:  # noqa: BLE001 — hata adımda saklanır, panel gösterir
            logger.exception("%s başarısız", sdef.label)
            _set(repo, row, model.FAILED, str(exc)[:500])
            break
        _set(repo, row, model.DONE, message)
        logger.info("✔ %s — %s", sdef.label, message)

    final = list_steps(repo, run["id"])
    if all(s["status"] in model.FINISHED for s in final):
        repo.update("runs", run["id"], {"status": "bitti"})
    return model.current_turn(final)


def complete_user_step(repo: Repo, date_str: str, key: str, message: str = "Kullanıcı tamamladı.") -> None:
    """Kullanıcı bir adımı elle tamamlar ya da atlar (ör. TR kaydını sonra yapacak)."""
    if key not in USER_CHECKS:
        raise ValueError(f"{key} kullanıcı adımı değil.")
    repo.update("run_steps", model.step_id(model.run_id_for(date_str), key), {"status": model.SKIPPED, "message": message})


def unlock(repo: Repo, date_str: str) -> int:
    """Çöken bir süreçten kalan 'çalışıyor' kilitlerini 'hata' yapar ki tekrar denenebilsin."""
    count = 0
    for row in list_steps(repo, model.run_id_for(date_str)):
        if row["status"] == model.RUNNING:
            _set(repo, row, model.FAILED, "Yarıda kaldı; tekrar denenebilir.")
            count += 1
    return count


def reset_step(repo: Repo, date_str: str, key: str) -> None:
    """Bir adımı (ve sonrakileri) yeniden çalıştırılmak üzere bekliyor durumuna alır."""
    target = model.STEP_BY_KEY[key]
    position = model.STEPS.index(target) + 1
    for row in list_steps(repo, model.run_id_for(date_str)):
        if row["position"] >= position:
            _set(repo, row, model.WAITING, None)
    if repo.get("runs", model.run_id_for(date_str)):
        repo.update("runs", model.run_id_for(date_str), {"status": "aktif"})
