"""Adımların gerçek işi. Her otomatik adım bir mesaj döndürür; hata olursa istisna fırlatır."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from bulten import formats, ideas, images, ingest, montage, organize, rewrite, state, translate
from bulten.brain import memory, planner
from bulten.db import Repo, new_id
from bulten.utils import read_json, write_json

logger = logging.getLogger(__name__)


@dataclass
class Deps:
    """Dış dünyaya bağlanan her şey; testlerde sahteleriyle değiştirilir."""

    chat_factory: Callable[[dict], Any] | None = None
    image_backend_factory: Callable[[dict], Any] | None = None
    synth_factory: Callable[[dict], Any] | None = None
    feed_reader: Callable[[str], list[dict]] | None = None
    text_fetcher: Callable[[str], str | None] | None = None
    _cache: dict[str, Any] = field(default_factory=dict)

    def chat(self, cfg: dict) -> Any:
        if "chat" not in self._cache:
            from bulten.llm import DeepSeekClient

            self._cache["chat"] = (self.chat_factory or DeepSeekClient)(cfg)
        return self._cache["chat"]


@dataclass
class Ctx:
    cfg: dict[str, Any]
    repo: Repo
    date: str
    run: dict[str, Any]
    deps: Deps


# ---------------------------------------------------------------- plan

def task_plan(ctx: Ctx) -> str:
    state.import_legacy_seen(ctx.repo)
    reader = ctx.deps.feed_reader or ingest._read_feed
    candidates = ingest.fetch_candidates(ctx.cfg, state.load_seen_db(ctx.repo), reader)
    profiles = formats.enabled_profiles(ctx.cfg)
    plan = planner.plan_day(
        candidates,
        ctx.cfg,
        ctx.repo,
        profiles,
        client=ctx.deps.chat(ctx.cfg),
        today=ctx.date,
        text_fetcher=ctx.deps.text_fetcher or ingest.fetch_full_text,
    )
    if not any(plan.get(p["name"]) for p in profiles):
        raise RuntimeError("İşlenecek yeni haber ya da fikir yok. (Hepsi daha önce işlenmiş olabilir.)")
    plan = {**plan, "profiles": {p["name"]: p for p in profiles}}
    ctx.repo.update("runs", ctx.run["id"], {"plan": plan})
    counts = ", ".join(f"{len(plan.get(p['name'], []))} {p['name']}" for p in profiles)
    return f"Seçildi: {counts}. {plan.get('gerekce', '')}".strip()


# ---------------------------------------------------------------- write

def _existing_sources(repo: Repo, run_id: str, fmt: str) -> set[str]:
    rows = repo.select("contents", {"run_id": run_id, "format": fmt})
    return {(r.get("features") or {}).get("source_id") for r in rows}


def _run_profile(ctx: Ctx, name: str) -> dict:
    """Planlama anındaki formül: panelde sonradan yapılan düzenleme Colab'ı bozmaz."""
    plan = (ctx.repo.get("runs", ctx.run["id"]) or {}).get("plan") or {}
    return (plan.get("profiles") or {}).get(name) or formats.load_profile(name, ctx.cfg)


def _write_one(ctx: Ctx, item: dict, profile: dict, guidance: str, idx: int) -> dict:
    client = ctx.deps.chat(ctx.cfg)
    errors: list[str] = []
    try:
        script = rewrite.rewrite_item(item, ctx.cfg, client, profile, guidance)
    except Exception as exc:  # noqa: BLE001
        logger.error("Senaryo üretilemedi: %s", exc)
        script = rewrite.fallback_script(item, profile)
        errors.append(f"senaryo: {exc}")
    if script.get("uyari"):
        errors.append(script["uyari"])

    translations: dict[str, str] = {}
    if profile.get("translate", True):
        translations, t_errors = translate.translate_all(script["senaryo"], ctx.cfg, client)
        errors += [f"ceviri/{lang}: {msg}" for lang, msg in t_errors.items()]

    root = organize.format_dir(ctx.date, profile["name"], ctx.cfg)
    folder = organize.unique_dir(root / organize.item_dir_name(idx, script["baslik"]))
    content_id = new_id()
    data = {**item, **script, "format": profile["name"], "ceviriler": translations, "gorseller": [],
            "hatalar": errors, "content_id": content_id}
    organize.save_item(folder, data)
    content = ctx.repo.insert(
        "contents",
        {
            "id": content_id,
            "run_id": ctx.run["id"],
            "date": ctx.date,
            "format": profile["name"],
            "title": script["baslik"],
            "source_title": item["title"],
            "source_url": item.get("link", ""),
            "script": script["senaryo"],
            "summary": script.get("ozet", ""),
            "hook": script.get("kanca") or None,
            "tags": script.get("etiketler", []),
            "idea_id": item.get("idea_id"),
            "folder": organize.relative_folder(folder, ctx.cfg),
            "features": {
                "source_id": item["id"],
                "words": len(script["senaryo"].split()),
                "has_hook": bool(script.get("kanca")),
                "angle": item.get("aci", ""),
            },
        },
    )
    if item.get("idea_id"):
        ideas.mark_used(ctx.repo, item["idea_id"], content["id"])
    if not item["id"].startswith("fikir:") and not script.get("uyari"):
        state.mark_seen_db(ctx.repo, [item["id"]])
    return content


def task_write(ctx: Ctx) -> str:
    plan = (ctx.repo.get("runs", ctx.run["id"]) or {}).get("plan") or {}
    written = 0
    for name in [p["name"] for p in formats.enabled_profiles(ctx.cfg)]:
        profile = _run_profile(ctx, name)
        fmt = profile["name"]
        done = _existing_sources(ctx.repo, ctx.run["id"], fmt)
        guidance = memory.format_guidance(ctx.repo, fmt)
        root = organize.format_dir(ctx.date, fmt, ctx.cfg)
        for item in plan.get(fmt, []):
            if item["id"] in done:
                continue  # yarıda kalan çalıştırma devam ediyor
            idx = organize.next_index(root)
            logger.info("[%s %02d] %s", fmt, idx, item["title"])
            _write_one(ctx, item, profile, guidance, idx)
            written += 1
    for profile in formats.enabled_profiles(ctx.cfg):
        root = organize.format_dir(ctx.date, profile["name"], ctx.cfg)
        if root.exists():
            organize.write_index(root, ctx.date, ctx.cfg, label=profile["label"])
    return f"{written} içerik yazıldı."


# ---------------------------------------------------------------- images

def _run_contents(ctx: Ctx) -> list[dict]:
    return ctx.repo.select("contents", {"run_id": ctx.run["id"]}, order_by="created_at")


def task_images(ctx: Ctx) -> str:
    factory = ctx.deps.image_backend_factory or images.create_backend
    backend = None
    made, failed = 0, 0
    for content in _run_contents(ctx):
        folder = organize.absolute_folder(content["folder"], ctx.cfg)
        meta = read_json(folder / "metadata.json", default=None)
        if not meta or not meta.get("gorsel_promptleri"):
            raise RuntimeError(
                f"{folder} bulunamadı ya da eksik. Drive senkronu bitti mi? (output.base_dir PC ve Colab'da aynı klasör olmalı)"
            )
        profile = _run_profile(ctx, content["format"])
        fcfg = formats.with_format(ctx.cfg, profile)
        if len(meta.get("gorseller") or []) >= fcfg["images"]["count_per_item"]:
            continue
        backend = backend or factory(fcfg)
        images.configure_size(backend, fcfg["images"]["width"], fcfg["images"]["height"])
        saved, errors = images.generate_images(meta.get("gorsel_promptleri", []), folder / "gorseller", fcfg, backend)
        made += len(saved)
        failed += len(errors)
        write_json(folder / "metadata.json", {
            **meta,
            "gorseller": [Path(p).name for p in saved],
            "hatalar": [*meta.get("hatalar", []), *[f"gorsel/{e}" for e in errors]],
        })
    if failed:
        raise RuntimeError(
            f"{failed} görsel üretilemedi ({made} başarılı). Tekrar çalıştırınca sadece eksikler üretilir; "
            "sürerse GPU/VRAM yetersiz olabilir."
        )
    return f"{made} görsel üretildi."


# ---------------------------------------------------------------- voices

def task_voices(ctx: Ctx) -> str:
    from run_voice import find_jobs  # GPU bağımlılığı yalnızca bu adımda yüklenir
    from bulten.utils import read_text

    languages = list(ctx.cfg["voice"]["languages"])
    missing = [c["folder"] for c in _run_contents(ctx) if not organize.absolute_folder(c["folder"], ctx.cfg).exists()]
    if missing:
        raise RuntimeError(f"{len(missing)} içerik klasörü bu makinede yok (ör. {missing[0]}). Drive senkronunu bekle.")
    jobs = []
    for profile in formats.enabled_profiles(ctx.cfg):
        root = organize.format_dir(ctx.date, profile["name"], ctx.cfg)
        if root.exists():
            jobs += find_jobs(root, languages, overwrite=False)
    if not jobs:
        return "Üretilecek yeni ses yok."
    if ctx.deps.synth_factory:
        synth = ctx.deps.synth_factory(ctx.cfg)
    else:
        from bulten.voice import VoiceSynthesizer

        synth = VoiceSynthesizer(ctx.cfg)
    failures = 0
    for src, lang, dst in jobs:
        try:
            synth.synthesize_to_file(read_text(src), lang, dst)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.error("Ses üretilemedi (%s): %s", dst, exc)
    if failures:
        raise RuntimeError(
            f"{failures}/{len(jobs)} ses üretilemedi. refs/ref_voice.wav ve GPU'yu kontrol et; tekrar çalıştırınca sadece eksikler üretilir."
        )
    return f"{len(jobs) - failures}/{len(jobs)} ses dosyası üretildi."


# ---------------------------------------------------------------- kullanıcı adımları

def check_tr_voice(ctx: Ctx) -> tuple[bool, str]:
    contents = _run_contents(ctx)
    missing = [c["title"] for c in contents
               if not (organize.absolute_folder(c["folder"], ctx.cfg) / "ses" / "tr.wav").exists()]
    if not missing:
        return True, "Tüm TR ses kayıtları yerinde."
    return False, f"{len(contents) - len(missing)}/{len(contents)} kayıt hazır. Eksik: " + "; ".join(missing[:5])


def check_publish(ctx: Ctx) -> tuple[bool, str]:
    contents = _run_contents(ctx)
    linked = [c for c in contents if c.get("yt_video_id")]
    if contents and len(linked) == len(contents):
        return True, "Tüm içeriklerin YouTube linki eklendi."
    return False, f"{len(linked)}/{len(contents)} içeriğin YouTube linki eklendi."


# ---------------------------------------------------------------- package

def task_package(ctx: Ctx) -> str:
    notes = montage.write_montage_notes(ctx.date, ctx.cfg)
    delivery = montage.write_delivery(ctx.date, ctx.cfg)
    return f"{len(notes)} montaj notu + {delivery.name} hazır."


AUTO_TASKS: dict[str, Callable[[Ctx], str]] = {
    "plan": task_plan,
    "write": task_write,
    "images": task_images,
    "voices": task_voices,
    "package": task_package,
}
USER_CHECKS: dict[str, Callable[[Ctx], tuple[bool, str]]] = {
    "tr_voice": check_tr_voice,
    "publish": check_publish,
}
