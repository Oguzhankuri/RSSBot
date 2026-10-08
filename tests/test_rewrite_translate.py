import json

import httpx
import pytest

from bulten import llm, rewrite, translate
from tests.fakes import FakeChat, make_item


def test_rewrite_valid_json(base_cfg):
    chat = FakeChat()
    out = rewrite.rewrite_item(make_item(), base_cfg, chat)
    assert len(out["gorsel_promptleri"]) == 3
    assert out["senaryo"]
    assert chat.calls[0]["json_mode"] is True
    assert "logo" in chat.calls[0]["system"]  # görsel güvenlik kuralı gömülü
    assert "110" in chat.calls[0]["user"]


def test_rewrite_strips_code_fence_and_pads_prompts(base_cfg):
    payload = json.dumps({"baslik": "B" * 100, "senaryo": "metin", "gorsel_promptleri": ["one"]})
    out = rewrite.rewrite_item(make_item(), base_cfg, FakeChat([f"```json\n{payload}\n```"]))
    assert len(out["baslik"]) == 70
    assert len(out["gorsel_promptleri"]) == 3


def test_rewrite_retry_lower_temperature_then_fallback(base_cfg):
    chat = FakeChat(["bozuk", "yine bozuk"])
    out = rewrite.rewrite_item(make_item(), base_cfg, chat)
    assert [c["temperature"] for c in chat.calls] == [0.7, rewrite.RETRY_TEMPERATURE]
    assert out["senaryo"] == "Kısa özet metni."
    assert "uyari" in out


def test_rewrite_retry_succeeds(base_cfg):
    good = json.dumps({"senaryo": "ok", "baslik": "b"})
    out = rewrite.rewrite_item(make_item(), base_cfg, FakeChat(["bozuk", good]))
    assert out["senaryo"] == "ok" and "uyari" not in out


def test_translate_all(base_cfg):
    chat = FakeChat()
    out, errors = translate.translate_all("Merhaba dünya.", base_cfg, chat)
    assert set(out) == {"en", "de", "ar", "ru"} and errors == {}
    assert "Almanca" in chat.calls[1]["system"]


def test_translate_partial_failure(base_cfg):
    class Half(FakeChat):
        def chat(self, system, user, **kw):
            if "Arapça" in system:
                raise RuntimeError("api")
            return "ok"

    out, errors = translate.translate_all("x", base_cfg, Half())
    assert "ar" in errors and "ar" not in out and len(out) == 3


def test_translate_disabled_and_empty(base_cfg):
    cfg = {**base_cfg, "translate": {"enabled": False, "languages": ["en"]}}
    assert translate.translate_all("x", cfg, FakeChat()) == ({}, {})

    class Empty(FakeChat):
        def chat(self, *a, **k):
            return ""

    with pytest.raises(ValueError):
        translate.translate_text("x", "en", base_cfg, Empty())


class _Choice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class FakeOpenAI:
    def __init__(self, fails):
        self.fails = fails
        self.kwargs = None
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.fails:
            self.fails -= 1
            raise llm.APIConnectionError(request=httpx.Request("POST", "http://x"))
        return type("R", (), {"choices": [_Choice(" cevap ")]})()


def test_llm_retries_with_backoff(base_cfg, monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    fake = FakeOpenAI(fails=2)
    client = llm.DeepSeekClient(base_cfg, client=fake)
    assert client.chat("s", "u", json_mode=True) == "cevap"
    assert sleeps == [2.0, 4.0]
    assert fake.kwargs["response_format"] == {"type": "json_object"}
    assert fake.kwargs["model"] == "deepseek-chat"


def test_llm_gives_up(base_cfg, monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    client = llm.DeepSeekClient(base_cfg, client=FakeOpenAI(fails=5))
    with pytest.raises(llm.APIConnectionError):
        client.chat("s", "u")
