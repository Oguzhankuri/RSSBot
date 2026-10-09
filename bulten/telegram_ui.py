"""Telegram botunun düğmeli arayüzü: fikir kartları, liste ve düğme (callback) işlemleri.

Callback verisi kısa ve doğrulanır: "<eylem>:<fikir-id>[:<değer>]" (Telegram sınırı 64 bayt).
Düğmeye kimin bastığı telegram_sync tarafında, izinli kimlik listesiyle kontrol edilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bulten import ideas
from bulten.db import Repo

LIST_LIMIT = 15
LIST_LABEL_CHARS = 42
CARD_TEXT_CHARS = 700

MENU_LIST = "📋 Fikirlerim"
MENU_HELP = "❓ Yardım"
MENU_BUTTONS = {MENU_LIST: "/liste", MENU_HELP: "/yardim"}
MENU_KEYBOARD = {
    "keyboard": [[{"text": MENU_LIST}, {"text": MENU_HELP}]],
    "resize_keyboard": True,
    "is_persistent": True,
    "input_field_placeholder": "Fikrini yaz…",
}

FORMAT_LABELS = {"dikey": "📱 Dikey", "yatay": "🖥️ Yatay"}
STATUS_LABELS = {"yeni": "", "kullanildi": "✅ kullanıldı", "arsiv": "🗄️ arşivde"}


@dataclass(frozen=True)
class Reply:
    text: str
    markup: dict[str, Any] | None = None


@dataclass(frozen=True)
class CallbackResult:
    toast: str                      # düğmeye basınca üstte beliren kısa bilgi
    edit: Reply | None = None       # düğmenin bulunduğu mesajı güncelle
    send: Reply | None = None       # yeni mesaj gönder


def _button(text: str, data: str) -> dict[str, str]:
    return {"text": text, "callback_data": data}


def card_text(idea: dict) -> str:
    meta = [
        f"⭐{idea.get('priority', 3)}",
        FORMAT_LABELS.get(idea.get("suggested_format") or "", "format yok"),
        idea.get("category") or "",
        STATUS_LABELS.get(idea.get("status") or "yeni", ""),
        f"kod: {ideas.short_id(idea)}",
    ]
    return f"💡 {idea['text'][:CARD_TEXT_CHARS]}\n\n" + " · ".join(m for m in meta if m)


def card_markup(idea: dict) -> dict[str, Any]:
    iid, status = idea["id"], idea.get("status") or "yeni"
    if status == "arsiv":
        return {"inline_keyboard": [[_button("↩️ Geri al", f"r:{iid}"), _button("📋 Liste", "l")]]}
    priority = int(idea.get("priority") or 3)
    fmt = idea.get("suggested_format")
    rows = [
        [_button(f"{'⭐' if n == priority else ''}{n}", f"p:{iid}:{n}") for n in ideas.PRIORITY_RANGE],
        [_button(("✓ " if fmt == key else "") + label, f"f:{iid}:{key}") for key, label in FORMAT_LABELS.items()],
        [_button("🗄️ Arşivle", f"a:{iid}"), _button("📋 Liste", "l")],
    ]
    return {"inline_keyboard": rows}


def card(idea: dict, header: str = "") -> Reply:
    text = card_text(idea)
    return Reply(f"{header}\n{text}" if header else text, card_markup(idea))


def idea_list(repo: Repo) -> Reply:
    rows = ideas.list_open(repo, limit=LIST_LIMIT)
    if not rows:
        return Reply("Açık fikir yok. Bir şey yaz, kaydedeyim.", MENU_KEYBOARD)
    buttons = [
        [_button(f"⭐{r.get('priority', 3)} {r['text'][:LIST_LABEL_CHARS]}", f"v:{r['id']}")] for r in rows
    ]
    return Reply(f"📋 Açık fikirler ({len(rows)}) — düzenlemek için dokun:", {"inline_keyboard": buttons})


def _parse(data: str) -> tuple[str, str, str]:
    action, _, rest = (data or "").partition(":")
    idea_id, _, value = rest.partition(":")
    return action, idea_id, value


def handle_callback(repo: Repo, data: str) -> CallbackResult:
    """Düğme verisini uygular. Bilinmeyen/bozuk veri sessizce reddedilir (hiçbir şey değişmez)."""
    action, idea_id, value = _parse(data)
    if action == "l":
        return CallbackResult("📋", send=idea_list(repo))
    if action not in ("v", "p", "f", "a", "r") or not idea_id:
        return CallbackResult("Bu düğme artık geçerli değil.")
    idea = repo.get("ideas", idea_id)
    if idea is None:
        return CallbackResult("Fikir bulunamadı (silinmiş olabilir).")
    if action == "v":
        return CallbackResult("💡", send=card(idea))
    try:
        if action == "p":
            idea, toast = ideas.set_priority(repo, idea_id, int(value)), f"⭐ Öncelik {value}"
        elif action == "f":
            idea, toast = ideas.set_format(repo, idea_id, value), f"{FORMAT_LABELS[value]} olarak işaretlendi"
        elif action == "a":
            idea, toast = ideas.set_status(repo, idea_id, "arsiv"), "🗄️ Arşivlendi (kaybolmaz, geri alınabilir)"
        else:
            idea, toast = ideas.set_status(repo, idea_id, "yeni"), "↩️ Geri alındı"
    except (ValueError, KeyError, ideas.IdeaError):
        return CallbackResult("Geçersiz seçim.")
    return CallbackResult(toast, edit=card(idea))
