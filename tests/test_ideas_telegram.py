import json

import pytest

from bulten import ideas, telegram_sync
from bulten.db import SqliteRepo, kv_get
from tests.fakes import FakeChat

OWNER = 111


@pytest.fixture
def repo():
    return SqliteRepo()


def test_add_idea_saves_even_if_enrich_fails(repo):
    class Broken(FakeChat):
        def chat(self, *a, **k):
            raise RuntimeError("api down")

    row = ideas.add_idea(repo, "  çok   iyi bir fikir ", client=Broken())
    assert repo.get("ideas", row["id"])["text"] == "çok iyi bir fikir"
    with pytest.raises(ideas.IdeaError):
        ideas.add_idea(repo, "   ")
    with pytest.raises(ideas.IdeaError):
        ideas.add_idea(repo, "x" * 3000)
    with pytest.raises(ideas.IdeaError):
        ideas.add_idea(repo, "a", priority=9)


def test_enrich_and_listing(repo):
    chat = FakeChat([json.dumps({"kategori": "bilim", "etiketler": ["kuş", "doğa"], "format": "dikey"})])
    rich = ideas.add_idea(repo, "Kuşlar neden V uçar", client=chat)
    assert rich["category"] == "bilim" and rich["suggested_format"] == "dikey" and rich["tags"] == ["kuş", "doğa"]
    low = ideas.add_idea(repo, "düşük", priority=1)
    urgent = ideas.add_idea(repo, "acil", priority=5)
    assert [i["id"] for i in ideas.list_open(repo)] == [urgent["id"], rich["id"], low["id"]]
    ideas.set_status(repo, low["id"], "arsiv")
    assert low["id"] not in [i["id"] for i in ideas.list_open(repo)]
    with pytest.raises(ideas.IdeaError):
        ideas.set_status(repo, low["id"], "yok")
    assert ideas.edit_text(repo, urgent["id"], "acil 2")["text"] == "acil 2"
    assert ideas.find_by_prefix(repo, urgent["id"][:6])["id"] == urgent["id"]
    assert ideas.find_by_prefix(repo, "ab") is None
    assert ideas.mark_used(repo, rich["id"], "c1")["used_in"] == ["c1"]
    assert ideas.mark_used(repo, "yok", "c1") is None


class FakeHttp:
    def __init__(self, updates):
        self.updates = updates
        self.sent = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        if method == "getUpdates":
            result = [u for u in self.updates if u["update_id"] >= json["offset"]]
        else:
            self.sent.append(json)
            result = {}
        return type("R", (), {"json": lambda self_: {"ok": True, "result": result}})()


def msg(update_id, text, sender=OWNER, message_id=None):
    return {"update_id": update_id, "message": {"message_id": message_id or update_id, "from": {"id": sender},
                                                "chat": {"id": -5}, "text": text}}


def test_sync_saves_ideas_and_commands(repo):
    http = FakeHttp([
        msg(1, "Uzayda yaşam var mı?"),
        msg(2, "!Acil fikir"),
        msg(3, "yabancı", sender=999),
        msg(4, "/liste"),
        {"update_id": 5},
    ])
    api = telegram_sync.TelegramApi("tok", http=http)
    assert telegram_sync.sync(repo, api, OWNER) == 5
    rows = ideas.list_open(repo)
    assert [r["text"] for r in rows] == ["Acil fikir", "Uzayda yaşam var mı?"] and rows[0]["priority"] == 5
    assert rows[0]["source"] == "telegram"
    assert kv_get(repo, telegram_sync.OFFSET_KEY) == 6
    texts = [s["text"] for s in http.sent]
    assert texts[0].startswith("✅ Kaydedildi") and "acil" in texts[1] and texts[2] == "Bu bot özeldir."
    assert "Uzayda" in texts[3]

    # aynı mesaj tekrar gelirse (iki senkron yarıştı) çift kayıt olmaz
    http2 = FakeHttp([msg(1, "Uzayda yaşam var mı?")])
    from bulten.db import kv_set
    kv_set(repo, telegram_sync.OFFSET_KEY, 0)
    telegram_sync.sync(repo, telegram_sync.TelegramApi("tok", http=http2), OWNER)
    assert len(repo.select("ideas")) == 2 and http2.sent == []


def test_commands(repo):
    idea = ideas.add_idea(repo, "fikir bir")
    code = idea["id"][:6]
    handle = lambda text: telegram_sync.handle_message(repo, msg(1, text)["message"], OWNER)
    assert "Öncelik" in handle(f"/oncelik {code} 4") and repo.get("ideas", idea["id"])["priority"] == 4
    assert "Kullanım" in handle(f"/oncelik {code} 9")
    assert "Arşivlendi" in handle(f"/sil {code}") and repo.get("ideas", idea["id"])["status"] == "arsiv"
    assert "bulamadım" in handle("/sil zzzzzz")
    assert handle("/start") == telegram_sync.HELP_TEXT == handle("/bilinmeyen")
    assert "Açık fikir yok" in handle("/liste")
    assert "yazılı" in telegram_sync.handle_message(repo, {"from": {"id": OWNER}, "chat": {"id": 1}}, OWNER)
    assert "⚠️" in handle("!")


def test_api_errors_and_config():
    with pytest.raises(telegram_sync.TelegramError):
        telegram_sync.TelegramApi("")

    class Bad:
        def post(self, *a, **k):
            return type("R", (), {"json": lambda s: {"ok": False, "description": "Unauthorized"}})()

    with pytest.raises(telegram_sync.TelegramError, match="Unauthorized"):
        telegram_sync.TelegramApi("t", http=Bad()).call("getMe")
    telegram_sync.TelegramApi("t", http=Bad()).reply(1, "x")  # hata yutulur, loglanır
    with pytest.raises(telegram_sync.TelegramError, match="ALLOWED"):
        telegram_sync.from_config({"env": {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_USER_ID": "abc"}})
    with pytest.raises(telegram_sync.TelegramError, match="virgül"):
        telegram_sync.from_config({"env": {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_USER_ID": ""}})
    api, ids = telegram_sync.from_config({"env": {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_USER_ID": "4242"}})
    assert ids == {4242}
    _, ids = telegram_sync.from_config({"env": {"TELEGRAM_ALLOWED_USER_ID": "1111, 2222;3333", "TELEGRAM_BOT_TOKEN": "t"}})
    assert ids == {1111, 2222, 3333}


def test_team_members_accepted_and_author_recorded(repo):
    team = frozenset({OWNER, 5555})
    message = {"message_id": 7, "chat": {"id": 5555}, "from": {"id": 5555, "first_name": "Ayşe", "last_name": "Y"},
               "text": "ekip fikri"}
    assert "Kaydedildi" in telegram_sync.handle_message(repo, message, team)
    stranger = {**message, "message_id": 8, "from": {"id": 9999}}
    assert telegram_sync.handle_message(repo, stranger, team) == "Bu bot özeldir."
    rows = repo.select("ideas")
    assert len(rows) == 1 and rows[0]["source"] == "telegram:Ayşe Y"
