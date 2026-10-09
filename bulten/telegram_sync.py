"""Telegram → Fikir Kutusu senkronu (getUpdates ile; sunucu gerekmez).

Panel açıkken panelden, PC kapalıyken GitHub Actions'tan (15 dk'da bir) çalışır.
Aynı mesaj iki kez işlense bile fikir kimliği mesajdan türediği için tekrar kaydedilmez.

    python -m bulten.telegram_sync
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from typing import Any, Collection

import requests

from bulten import ideas, telegram_ui
from bulten.config import ConfigError, load_config
from bulten.db import Repo, RepoError, create_repo, kv_get, kv_set
from bulten.telegram_ui import Reply

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"
OFFSET_KEY = "telegram_offset"
COMMANDS_KEY = "telegram_commands"
# "/" yazınca Telegram'ın gösterdiği menü. Değiştirince bir sonraki senkronda bota yeniden bildirilir.
BOT_COMMANDS = (
    ("liste", "Açık fikirleri listele"),
    ("oncelik", "Önceliği değiştir: /oncelik <kod> <1-5>"),
    ("sil", "Fikri arşivle: /sil <kod>"),
    ("yardim", "Nasıl kullanılır?"),
)
TIMEOUT = 20
URGENT_PREFIX = "!"
MAX_AUTHOR_LEN = 40
HELP_TEXT = (
    "💡 Fikir kutusu\n"
    "• Ne yazarsan fikir olarak kaydedilir; altındaki düğmelerle öncelik, format ve arşiv ayarlanır.\n"
    "• Başına ! koyarsan acil (öncelik 5) olur.\n"
    "• 📋 Fikirlerim (ya da /liste) — açık fikirler; dokununca düzenlenir.\n"
    "• /oncelik <kod> <1-5>, /sil <kod> — düğmesiz kısayollar (sil = arşivle, kaybolmaz)"
)


class TelegramError(RuntimeError):
    pass


class TelegramApi:
    def __init__(self, token: str, http: Any = requests) -> None:
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN gerekli (.env veya GitHub Secrets).")
        self._token = token
        self._http = http

    def call(self, method: str, **params: Any) -> Any:
        url = API_URL.format(token=self._token, method=method)
        try:
            resp = self._http.post(url, json=params, timeout=TIMEOUT)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            # URL token içerir; hata mesajına koymuyoruz.
            raise TelegramError(f"Telegram'a ulaşılamadı ({method}): {type(exc).__name__}") from exc
        if not data.get("ok"):
            raise TelegramError(f"Telegram {method} hatası: {data.get('description', 'bilinmiyor')}")
        return data["result"]

    def _safe(self, method: str, **params: Any) -> None:
        """Yanıt/arayüz çağrıları: başarısız olsa da fikir senkronu durmaz."""
        try:
            self.call(method, **params)
        except TelegramError as exc:
            logger.warning("%s başarısız: %s", method, exc)

    def reply(self, chat_id: int, reply: Reply | str) -> None:
        reply = Reply(reply) if isinstance(reply, str) else reply
        extra = {"reply_markup": reply.markup} if reply.markup else {}
        self._safe("sendMessage", chat_id=chat_id, text=reply.text, **extra)

    def edit(self, chat_id: int, message_id: int, reply: Reply) -> None:
        extra = {"reply_markup": reply.markup} if reply.markup else {}
        self._safe("editMessageText", chat_id=chat_id, message_id=message_id, text=reply.text, **extra)

    def answer(self, callback_id: str, text: str) -> None:
        self._safe("answerCallbackQuery", callback_query_id=callback_id, text=text[:190])


def ensure_commands(repo: Repo, api: TelegramApi) -> None:
    """Komut menüsünü bota bildirir; liste değişmediyse Telegram'a tekrar gitmez."""
    signature = "|".join(f"{c}:{d}" for c, d in BOT_COMMANDS)
    if kv_get(repo, COMMANDS_KEY) == signature:
        return
    try:
        api.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in BOT_COMMANDS])
    except TelegramError as exc:
        logger.warning("Komut menüsü ayarlanamadı (fikirler etkilenmez): %s", exc)
        return
    kv_set(repo, COMMANDS_KEY, signature)


def _command(repo: Repo, text: str) -> Reply:
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    if cmd == "/liste":
        return telegram_ui.idea_list(repo)
    if cmd in ("/sil", "/oncelik") and len(parts) >= 2:
        idea = ideas.find_by_prefix(repo, parts[1])
        if idea is None:
            return Reply("Bu kodla tek bir fikir bulamadım. /liste ile kodlara bak.")
        if cmd == "/sil":
            return telegram_ui.card(ideas.set_status(repo, idea["id"], "arsiv"), "🗄️ Arşivlendi")
        try:
            updated = ideas.set_priority(repo, idea["id"], int(parts[2]) if len(parts) > 2 else 0)
        except (ValueError, ideas.IdeaError):
            return Reply("Kullanım: /oncelik <kod> <1-5>")
        return telegram_ui.card(updated, "⭐ Öncelik güncellendi")
    return Reply(HELP_TEXT, telegram_ui.MENU_KEYBOARD)  # /start, /yardim ve bilinmeyen komutlar


def message_idea_id(msg: dict) -> str:
    """Aynı mesaj → aynı kimlik (çift kayıt olmaz); kısa kodları (/sil a1b2c3) çakışmasın diye hash."""
    key = f"telegram:{msg['chat']['id']}:{msg['message_id']}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def parse_allowed_ids(raw: str | None) -> frozenset[int]:
    """'111, 222 333' → {111, 222, 333}. Ekipte herkesin kimliği virgülle yazılır."""
    parts = [p for p in re.split(r"[,\s;]+", (raw or "").strip()) if p]
    if not parts or not all(re.fullmatch(r"-?\d{3,20}", p) for p in parts):
        raise TelegramError(
            "TELEGRAM_ALLOWED_USER_ID sayısal Telegram kimlikleri olmalı; ekip için virgülle ayır "
            "(ör. 111111111,222222222 — @userinfobot verir)."
        )
    return frozenset(int(p) for p in parts)


def _author(msg: dict) -> str:
    sender = msg.get("from") or {}
    name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x) or sender.get("username") or ""
    return re.sub(r"\s+", " ", name).strip()[:MAX_AUTHOR_LEN]


def _is_allowed(sender: Any, allowed: Collection[int] | int) -> bool:
    return sender in ({allowed} if isinstance(allowed, int) else allowed)


def handle_message(
    repo: Repo, msg: dict, allowed: Collection[int] | int, client: Any | None = None
) -> Reply | None:
    """Mesajı işler, gönderilecek yanıtı döndürür (None = yanıt verme)."""
    if not _is_allowed((msg.get("from") or {}).get("id"), allowed):
        logger.warning("Yetkisiz bir Telegram kullanıcısının mesajı yok sayıldı.")  # kimlik public loga yazılmaz
        return Reply("Bu bot özeldir.")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        return Reply("Şimdilik sadece yazılı fikirleri kaydedebiliyorum.")
    text = telegram_ui.MENU_BUTTONS.get(text, text)
    if text.startswith("/"):
        return _command(repo, text)
    priority = 5 if text.startswith(URGENT_PREFIX) else 3
    try:
        author = _author(msg)
        source = f"telegram:{author}" if author else "telegram"
        idea = ideas.add_idea(repo, text.lstrip(URGENT_PREFIX).strip(), source, priority, client,
                              idea_id=message_idea_id(msg))
    except RepoError as exc:
        if exc.conflict:
            return None  # zaten kaydedilmiş (başka senkron yakaladı)
        raise  # ağ/sunucu hatası: offset ilerlemez, mesaj bir sonraki senkronda tekrar denenir
    except ideas.IdeaError as exc:
        return Reply(f"⚠️ {exc}")
    return telegram_ui.card(idea, "✅ Kaydedildi" + (" · 🔥 acil" if priority == 5 else ""))


def handle_callback(repo: Repo, api: TelegramApi, query: dict, allowed: Collection[int] | int) -> None:
    """Düğmeye basılması. Yetki her basışta yeniden kontrol edilir."""
    if not _is_allowed((query.get("from") or {}).get("id"), allowed):
        logger.warning("Yetkisiz bir Telegram kullanıcısının düğme basışı yok sayıldı.")
        api.answer(query["id"], "Bu bot özeldir.")
        return
    result = telegram_ui.handle_callback(repo, str(query.get("data") or ""))
    api.answer(query["id"], result.toast)
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return
    if result.edit:
        api.edit(chat_id, message["message_id"], result.edit)
    if result.send:
        api.reply(chat_id, result.send)


def sync(repo: Repo, api: TelegramApi, allowed: Collection[int] | int, client: Any | None = None) -> int:
    """Bekleyen tüm mesajları işler; işlenen güncelleme sayısını döndürür."""
    ensure_commands(repo, api)
    offset = int(kv_get(repo, OFFSET_KEY, 0) or 0)
    updates = api.call("getUpdates", offset=offset, timeout=0, allowed_updates=["message", "callback_query"])
    for update in updates:
        msg = update.get("message")
        if msg:
            reply = handle_message(repo, msg, allowed, client)
            if reply:
                api.reply(msg["chat"]["id"], reply)
        elif update.get("callback_query"):
            handle_callback(repo, api, update["callback_query"], allowed)
        # Fikir kaydedildikten SONRA ilerlenir: çökme olursa mesaj kaybolmaz, tekrar işlenir.
        kv_set(repo, OFFSET_KEY, int(update["update_id"]) + 1)
    if updates:
        logger.info("Telegram: %d mesaj işlendi.", len(updates))
    return len(updates)


def from_config(cfg: dict[str, Any]) -> tuple[TelegramApi, frozenset[int]]:
    env = cfg.get("env") or {}
    allowed = parse_allowed_ids(env.get("TELEGRAM_ALLOWED_USER_ID"))
    return TelegramApi(env.get("TELEGRAM_BOT_TOKEN") or ""), allowed


def main(argv: list[str] | None = None) -> int:
    from bulten.utils import setup_logging

    setup_logging()
    try:
        cfg = load_config("config.yaml", require_db=True)
        api, allowed = from_config(cfg)
        client = None
        if cfg["env"].get("DEEPSEEK_API_KEY"):
            from bulten.llm import DeepSeekClient

            client = DeepSeekClient(cfg)
        sync(create_repo(cfg), api, allowed, client)
        return 0
    except (ConfigError, RepoError, TelegramError) as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
