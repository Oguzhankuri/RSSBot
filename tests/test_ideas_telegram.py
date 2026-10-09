import json

import pytest

from bulten import ideas, telegram_sync, telegram_ui
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
            if method == "sendMessage":
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
    list_buttons = http.sent[3]["reply_markup"]["inline_keyboard"]
    assert texts[3].startswith("📋") and any("Uzayda" in row[0]["text"] for row in list_buttons)
    assert "inline_keyboard" in http.sent[0]["reply_markup"]  # kayıt kartında düğmeler var

    # aynı mesaj tekrar gelirse (iki senkron yarıştı) çift kayıt olmaz
    http2 = FakeHttp([msg(1, "Uzayda yaşam var mı?")])
    from bulten.db import kv_set
    kv_set(repo, telegram_sync.OFFSET_KEY, 0)
    telegram_sync.sync(repo, telegram_sync.TelegramApi("tok", http=http2), OWNER)
    assert len(repo.select("ideas")) == 2 and http2.sent == []


def test_commands(repo):
    idea = ideas.add_idea(repo, "fikir bir")
    code = idea["id"][:6]
    handle = lambda text: telegram_sync.handle_message(repo, msg(1, text)["message"], OWNER).text
    assert "Öncelik" in handle(f"/oncelik {code} 4") and repo.get("ideas", idea["id"])["priority"] == 4
    assert "Kullanım" in handle(f"/oncelik {code} 9")
    assert "Arşivlendi" in handle(f"/sil {code}") and repo.get("ideas", idea["id"])["status"] == "arsiv"
    assert "bulamadım" in handle("/sil zzzzzz")
    assert handle("/start") == telegram_sync.HELP_TEXT == handle("/bilinmeyen")
    assert "Açık fikir yok" in handle("/liste")
    assert "yazılı" in telegram_sync.handle_message(repo, {"from": {"id": OWNER}, "chat": {"id": 1}}, OWNER).text
    assert handle(telegram_ui.MENU_LIST) == handle("/liste") and handle(telegram_ui.MENU_HELP) == telegram_sync.HELP_TEXT
    assert repo.get("ideas", idea["id"])["status"] == "arsiv"  # menü düğmeleri fikir olarak kaydedilmez
    assert len(repo.select("ideas")) == 1
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
    assert "Kaydedildi" in telegram_sync.handle_message(repo, message, team).text
    stranger = {**message, "message_id": 8, "from": {"id": 9999}}
    assert telegram_sync.handle_message(repo, stranger, team).text == "Bu bot özeldir."
    rows = repo.select("ideas")
    assert len(rows) == 1 and rows[0]["source"] == "telegram:Ayşe Y"


def test_command_menu_registered_once(repo):
    calls = []

    class Api:
        def call(self, method, **params):
            calls.append((method, params))
            return []

    telegram_sync.sync(repo, Api(), OWNER)
    telegram_sync.sync(repo, Api(), OWNER)
    menus = [p for m, p in calls if m == "setMyCommands"]
    assert len(menus) == 1
    assert [c["command"] for c in menus[0]["commands"]] == ["liste", "oncelik", "sil", "yardim"]


def test_command_menu_failure_does_not_block_sync(repo):
    class Api:
        def call(self, method, **params):
            if method == "setMyCommands":
                raise telegram_sync.TelegramError("yok")
            return []

    assert telegram_sync.sync(repo, Api(), OWNER) == 0
    assert kv_get(repo, telegram_sync.COMMANDS_KEY) is None


class RecordingApi:
    """Telegram API çağrılarını kaydeder; getUpdates için verilen güncellemeleri döndürür."""

    def __init__(self, updates=()):
        self.updates, self.calls = list(updates), []

    def call(self, method, **params):
        self.calls.append((method, params))
        return self.updates if method == "getUpdates" else {}

    def calls_of(self, method):
        return [p for m, p in self.calls if m == method]


def press(update_id, data, sender=OWNER, message_id=50):
    return {"update_id": update_id, "callback_query": {
        "id": f"cb{update_id}", "from": {"id": sender}, "data": data,
        "message": {"message_id": message_id, "chat": {"id": -5}},
    }}


def test_buttons_change_priority_format_archive_and_restore(repo):
    idea = ideas.add_idea(repo, "Kara delikler buharlaşır mı")
    iid = idea["id"]
    api = RecordingApi([
        press(1, f"p:{iid}:5"),
        press(2, f"f:{iid}:dikey"),
        press(3, f"a:{iid}"),
        press(4, f"r:{iid}"),
    ])
    tapi = _wrap(api)
    assert telegram_sync.sync(repo, tapi, OWNER) == 4
    row = repo.get("ideas", iid)
    assert row["priority"] == 5 and row["suggested_format"] == "dikey" and row["status"] == "yeni"
    toasts = [p["text"] for p in api.calls_of("answerCallbackQuery")]
    assert toasts[0].startswith("⭐") and "Dikey" in toasts[1] and "Arşiv" in toasts[2] and "Geri" in toasts[3]
    edits = api.calls_of("editMessageText")
    assert len(edits) == 4 and all(e["message_id"] == 50 for e in edits)
    archived_buttons = edits[2]["reply_markup"]["inline_keyboard"][0]
    assert archived_buttons[0]["callback_data"] == f"r:{iid}"
    assert all(len(b["callback_data"].encode()) <= 64 for row in edits[0]["reply_markup"]["inline_keyboard"] for b in row)


def test_list_and_view_buttons_send_new_messages(repo):
    idea = ideas.add_idea(repo, "Mars kolonisi")
    api = RecordingApi([press(1, "l"), press(2, f"v:{idea['id']}")])
    telegram_sync.sync(repo, _wrap(api), OWNER)
    sent = api.calls_of("sendMessage")
    assert sent[0]["text"].startswith("📋") and sent[1]["text"].startswith("💡 Mars kolonisi")
    assert api.calls_of("editMessageText") == []


def test_bad_and_unauthorized_button_presses_change_nothing(repo):
    idea = ideas.add_idea(repo, "dokunulmaz")
    iid = idea["id"]
    api = RecordingApi([
        press(1, f"p:{iid}:5", sender=999),       # yabancı
        press(2, f"p:{iid}:9"),                   # geçersiz öncelik
        press(3, f"f:{iid}:kare"),                # geçersiz format
        press(4, "p:yok-boyle-bir-id:3"),         # olmayan fikir
        press(5, "zzz:bozuk"),                    # bozuk veri
    ])
    assert telegram_sync.sync(repo, _wrap(api), OWNER) == 5
    assert repo.get("ideas", iid) == idea
    toasts = [p["text"] for p in api.calls_of("answerCallbackQuery")]
    assert toasts[0] == "Bu bot özeldir." and toasts[1] == toasts[2] == "Geçersiz seçim."
    assert "bulunamadı" in toasts[3] and "geçerli değil" in toasts[4]
    assert api.calls_of("editMessageText") == []


def _wrap(recording):
    """Gerçek TelegramApi sınıfını (reply/edit/answer) kayıt yapan çağrıyla kullanır."""
    api = telegram_sync.TelegramApi("tok")
    api.call = recording.call
    return api
