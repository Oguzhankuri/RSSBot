"""Telegram → Fikir Kutusu senkronu (getUpdates ile; sunucu gerekmez).

Panel açıkken panelden, PC kapalıyken GitHub Actions'tan (15 dk'da bir) çalışır.
Aynı mesaj iki kez işlense bile fikir kimliği mesajdan türediği için tekrar kaydedilmez.

    python -m bulten.telegram_sync
"""

from __future__ import annotations

import hashlib
import logging
import sys
from typing import Any

import requests

from bulten import ideas
from bulten.config import ConfigError, load_config
from bulten.db import Repo, RepoError, create_repo, kv_get, kv_set

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"
OFFSET_KEY = "telegram_offset"
TIMEOUT = 20
URGENT_PREFIX = "!"
HELP_TEXT = (
    "💡 Fikir kutusu\n"
    "• Ne yazarsan fikir olarak kaydedilir.\n"
    "• Başına ! koyarsan acil (öncelik 5) olur.\n"
    "• /liste — açık fikirler\n"
    "• /oncelik <kod> <1-5> — önceliği değiştir\n"
    "• /sil <kod> — fikri arşivle (silinmez, kaybolmaz)"
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

    def reply(self, chat_id: int, text: str) -> None:
        try:
            self.call("sendMessage", chat_id=chat_id, text=text)
        except TelegramError as exc:
            logger.warning("Yanıt gönderilemedi: %s", exc)


def _format_list(repo: Repo) -> str:
    rows = ideas.list_open(repo, limit=15)
    if not rows:
        return "Açık fikir yok. Bir şey yaz, kaydedeyim."
    return "\n".join(f"[{ideas.short_id(r)}] ⭐{r.get('priority', 3)} {r['text'][:120]}" for r in rows)


def _command(repo: Repo, text: str) -> str:
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    if cmd in ("/start", "/yardim", "/help"):
        return HELP_TEXT
    if cmd == "/liste":
        return _format_list(repo)
    if cmd in ("/sil", "/oncelik") and len(parts) >= 2:
        idea = ideas.find_by_prefix(repo, parts[1])
        if idea is None:
            return "Bu kodla tek bir fikir bulamadım. /liste ile kodlara bak."
        if cmd == "/sil":
            ideas.set_status(repo, idea["id"], "arsiv")
            return f"🗄️ Arşivlendi: {idea['text'][:80]}"
        try:
            ideas.set_priority(repo, idea["id"], int(parts[2]) if len(parts) > 2 else 0)
        except (ValueError, ideas.IdeaError):
            return "Kullanım: /oncelik <kod> <1-5>"
        return f"⭐ Öncelik güncellendi: {idea['text'][:80]}"
    return HELP_TEXT


def message_idea_id(msg: dict) -> str:
    """Aynı mesaj → aynı kimlik (çift kayıt olmaz); kısa kodları (/sil a1b2c3) çakışmasın diye hash."""
    key = f"telegram:{msg['chat']['id']}:{msg['message_id']}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def handle_message(repo: Repo, msg: dict, allowed_user_id: int, client: Any | None = None) -> str | None:
    """Mesajı işler, gönderilecek yanıtı döndürür (None = yanıt verme)."""
    sender = (msg.get("from") or {}).get("id")
    if sender != allowed_user_id:
        logger.warning("Yetkisiz Telegram kullanıcısı yok sayıldı: %s", sender)
        return "Bu bot özeldir."
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        return "Şimdilik sadece yazılı fikirleri kaydedebiliyorum."
    if text.startswith("/"):
        return _command(repo, text)
    priority = 5 if text.startswith(URGENT_PREFIX) else 3
    try:
        idea = ideas.add_idea(repo, text.lstrip(URGENT_PREFIX).strip(), "telegram", priority, client,
                              idea_id=message_idea_id(msg))
    except RepoError as exc:
        if exc.conflict:
            return None  # zaten kaydedilmiş (başka senkron yakaladı)
        raise  # ağ/sunucu hatası: offset ilerlemez, mesaj bir sonraki senkronda tekrar denenir
    except ideas.IdeaError as exc:
        return f"⚠️ {exc}"
    label = f" · {idea['category']}" if idea.get("category") else ""
    return f"✅ Kaydedildi [{ideas.short_id(idea)}]{label}" + (" · 🔥 acil" if priority == 5 else "")


def sync(repo: Repo, api: TelegramApi, allowed_user_id: int, client: Any | None = None) -> int:
    """Bekleyen tüm mesajları işler; işlenen güncelleme sayısını döndürür."""
    offset = int(kv_get(repo, OFFSET_KEY, 0) or 0)
    updates = api.call("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
    for update in updates:
        msg = update.get("message")
        if msg:
            reply = handle_message(repo, msg, allowed_user_id, client)
            if reply:
                api.reply(msg["chat"]["id"], reply)
        # Fikir kaydedildikten SONRA ilerlenir: çökme olursa mesaj kaybolmaz, tekrar işlenir.
        kv_set(repo, OFFSET_KEY, int(update["update_id"]) + 1)
    if updates:
        logger.info("Telegram: %d mesaj işlendi.", len(updates))
    return len(updates)


def from_config(cfg: dict[str, Any]) -> tuple[TelegramApi, int]:
    env = cfg.get("env") or {}
    raw_id = (env.get("TELEGRAM_ALLOWED_USER_ID") or "").strip()
    if not raw_id.lstrip("-").isdigit():
        raise TelegramError("TELEGRAM_ALLOWED_USER_ID sayısal Telegram kullanıcı kimliğin olmalı (ör. @userinfobot).")
    return TelegramApi(env.get("TELEGRAM_BOT_TOKEN") or ""), int(raw_id)


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
