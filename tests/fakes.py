"""Testlerde DeepSeek, görsel ve ses modellerinin yerine geçen sahte nesneler."""

import json

import numpy as np
from PIL import Image


class FakeChat:
    """DeepSeekClient.chat imzasını taklit eder; JSON yanıtlarını sırayla döndürür."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def chat(self, system, user, temperature=0.7, json_mode=False):
        self.calls.append({"system": system, "user": user, "temperature": temperature, "json_mode": json_mode})
        if json_mode:
            if self.responses:
                return self.responses.pop(0)
            return json.dumps(
                {
                    "baslik": "Test Başlığı Şehirde Önemli Gelişme",
                    "senaryo": "Bu bir test senaryosudur. " * 10,
                    "ozet": "Tek cümle özet.",
                    "gorsel_promptleri": ["city at night", "abstract map", "empty office"],
                    "etiketler": ["gündem", "test", "şehir"],
                }
            )
        return "translated: " + user[:40]


class FakeImageBackend:
    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if len(self.prompts) in self.fail_on:
            raise RuntimeError("boom")
        return Image.new("RGB", (64, 36), "navy")


class FakeTTSModel:
    sr = 24000

    def __init__(self):
        self.calls = []

    def generate(self, text, language_id, audio_prompt_path, exaggeration, cfg_weight):
        self.calls.append((text, language_id))
        return np.ones((1, 2400), dtype=np.float32) * 0.1


def make_item(i=1, text_len=400):
    return {
        "id": f"https://example.com/{i}",
        "title": f"Haber {i}: Çarşıda Gelişme",
        "link": f"https://example.com/{i}",
        "published": "Wed, 07 Oct 2026 10:00:00 GMT",
        "summary": "Kısa özet metni.",
        "text": "Uzun haber metni. " * (text_len // 18 + 1),
    }


class FakeChatterboxModel(FakeTTSModel):
    """prepare_conditionals destekleyen gerçek API'ye daha yakın sahte model."""

    def __init__(self):
        super().__init__()
        self.prepared = []
        self.prompt_paths = []

    def prepare_conditionals(self, wav_fpath, exaggeration=0.5):
        self.prepared.append(wav_fpath)

    def generate(self, text, language_id, audio_prompt_path, exaggeration, cfg_weight):
        self.prompt_paths.append(audio_prompt_path)
        return super().generate(text, language_id, audio_prompt_path, exaggeration, cfg_weight)
