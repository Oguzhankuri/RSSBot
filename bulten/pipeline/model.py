"""Günlük akışın adımları ve "sıra kimde" hesabı."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Durumlar
WAITING = "bekliyor"     # henüz sırası gelmedi
QUEUED = "sirada"        # sıra bu adımda; Colab'ın ya da kullanıcının yapması bekleniyor
RUNNING = "calisiyor"
DONE = "tamam"
FAILED = "hata"
SKIPPED = "atlandi"
FINISHED = (DONE, SKIPPED)

PC, COLAB, USER = "pc", "colab", "user"


@dataclass(frozen=True)
class StepDef:
    key: str
    label: str
    actor: str          # varsayılan aktör; images için yapılandırmaya göre değişir
    hint: str           # kullanıcıya "şimdi ne yapmalı" açıklaması


STEPS: tuple[StepDef, ...] = (
    StepDef("plan", "Planla (Beyin)", PC, "Gündem, fikirler ve hafıza harmanlanıyor."),
    StepDef("write", "Senaryolar + çeviriler", PC, "DeepSeek senaryoları ve çevirileri yazıyor."),
    StepDef("images", "Görseller", COLAB, "Colab'ı aç ve tek hücreyi çalıştır: görseller GPU'da üretilecek."),
    StepDef("voices", "Klon sesler (4 dil)", COLAB, "Colab hücresi görsellerden sonra klon sesleri de üretir."),
    StepDef("tr_voice", "TR ses kaydı", USER, "Her klasördeki senaryo_tr.md'yi oku, ses/tr.wav olarak kaydet."),
    StepDef("package", "Grafikçi paketi", PC, "Montaj notları ve TESLIM.md hazırlanıyor."),
    StepDef("publish", "Yayın + YouTube linkleri", USER, "Videolar yayınlanınca linklerini panelde İçerikler'e yapıştır."),
)
STEP_BY_KEY = {s.key: s for s in STEPS}


def actor_for(step: StepDef, cfg: dict[str, Any]) -> str:
    if step.key == "images" and cfg["images"].get("provider") == "hf_api":
        return PC  # Hugging Face API'si GPU istemez
    return step.actor


def hint_for(step: StepDef, actor: str) -> str:
    if step.key == "images" and actor == PC:
        return "Görseller Hugging Face API ile üretiliyor (Colab gerekmez)."
    return step.hint


def should_skip(step: StepDef, cfg: dict[str, Any]) -> bool:
    return step.key == "voices" and not (cfg["voice"].get("enabled", True) and cfg["translate"].get("enabled", True))


def step_id(run_id: str, key: str) -> str:
    return f"{run_id}:{key}"


def run_id_for(date_str: str) -> str:
    return f"run-{date_str}"


@dataclass(frozen=True)
class Turn:
    """Panelde gösterilen 'şu an sıra kimde' bilgisi."""

    actor: str | None       # pc | colab | user | None (bitti)
    step_key: str | None
    status: str | None
    title: str
    detail: str


def current_turn(steps: list[dict[str, Any]]) -> Turn:
    ordered = sorted(steps, key=lambda s: s["position"])
    for row in ordered:
        if row["status"] in FINISHED:
            continue
        sdef = STEP_BY_KEY[row["key"]]
        actor = row["actor"]
        if row["status"] == FAILED:
            return Turn(actor, row["key"], FAILED, f"❌ {sdef.label} hata verdi", row.get("message") or "")
        if row["status"] == RUNNING:
            where = "Colab'da" if actor == COLAB else "bilgisayarda"
            return Turn(actor, row["key"], RUNNING, f"⏳ {sdef.label} {where} çalışıyor…", row.get("message") or "")
        titles = {
            COLAB: "🚀 Sıra Colab'da — git orayı hallet!",
            USER: f"🎙️ Sıra sende: {sdef.label}",
            PC: f"▶️ Sıradaki: {sdef.label}",
        }
        return Turn(actor, row["key"], row["status"], titles[actor], row.get("message") or hint_for(sdef, actor))
    return Turn(None, None, None, "✅ Bugünün işi bitti!", "Tüm adımlar tamamlandı.")
