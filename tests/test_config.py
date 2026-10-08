import pytest

from bulten.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)


def test_load_config_ok(write_cfg, tmp_path):
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=abc\n", encoding="utf-8")
    cfg = load_config(write_cfg(), require_text=True)
    assert cfg["env"]["DEEPSEEK_API_KEY"] == "abc"
    assert cfg["ingest"]["max_items"] == 8


def test_missing_key_raises(write_cfg):
    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        load_config(write_cfg(), require_text=True)


def test_missing_key_ok_without_text(write_cfg):
    assert load_config(write_cfg())["env"]["DEEPSEEK_API_KEY"] is None


def test_empty_feeds(write_cfg):
    with pytest.raises(ConfigError, match="feeds"):
        load_config(write_cfg({"feeds": []}))


def test_placeholder_feed_rejected_for_text(write_cfg, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    with pytest.raises(ConfigError, match="örnek"):
        load_config(write_cfg({"feeds": ["https://ORNEK-HABER-SITESI.com/rss"]}), require_text=True)


def test_language_mismatch(write_cfg, base_cfg):
    voice = {**base_cfg["voice"], "languages": ["en", "fr"]}
    with pytest.raises(ConfigError, match="aynı olmalı"):
        load_config(write_cfg({"voice": voice}))


def test_bad_provider(write_cfg, base_cfg):
    with pytest.raises(ConfigError, match="provider"):
        load_config(write_cfg({"images": {**base_cfg["images"], "provider": "x"}}))


def test_fal_key_required(write_cfg, base_cfg, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    with pytest.raises(ConfigError, match="FAL_KEY"):
        load_config(write_cfg({"images": {**base_cfg["images"], "provider": "fal"}}), require_text=True)


def test_ref_audio_required(write_cfg, base_cfg):
    voice = {**base_cfg["voice"], "ref_audio": "yok/ref.wav"}
    with pytest.raises(ConfigError, match="referans"):
        load_config(write_cfg({"voice": voice}), require_voice=True)


def test_missing_file():
    with pytest.raises(ConfigError):
        load_config("olmayan.yaml")


def test_translate_disabled_voice_enabled_ok(write_cfg):
    cfg = load_config(write_cfg({"translate": {"enabled": False, "languages": []}}))
    assert cfg["translate"]["enabled"] is False


def test_unknown_language(write_cfg, base_cfg):
    langs = ["en", "xx"]
    with pytest.raises(ConfigError, match="Desteklenmeyen"):
        load_config(write_cfg({"translate": {"enabled": True, "languages": langs},
                               "voice": {**base_cfg["voice"], "languages": langs}}))


def test_tr_in_voice_rejected(write_cfg, base_cfg):
    langs = ["en", "tr"]
    with pytest.raises(ConfigError, match="'tr'"):
        load_config(write_cfg({"translate": {"enabled": True, "languages": langs},
                               "voice": {**base_cfg["voice"], "languages": langs}}))
