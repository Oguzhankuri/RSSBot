import os
import stat
import sys

import pytest

from bulten import auth, envfile
from tests.test_auth import PASSWORD, _isolate_env
from tests.test_panel import PANEL, _run, panel_env  # noqa: F401 — fixture

TOKEN = "123456789:" + "A" * 35


@pytest.fixture
def env(tmp_path, monkeypatch):
    _isolate_env(monkeypatch)
    for key in ("TELEGRAM_BOT_TOKEN", "HF_TOKEN", "SUPABASE_URL"):
        monkeypatch.setenv(key, "x")
        monkeypatch.delenv(key)
    path = tmp_path / ".env"
    path.write_text("# yorum\nDEEPSEEK_API_KEY=eski-anahtar-123456\nBASKA=dokunma\n", encoding="utf-8")
    return path


def test_update_preserves_other_lines_and_sets_environ(env):
    saved = envfile.update(env, {"DEEPSEEK_API_KEY": "  yeni-anahtar-987654 ", "TELEGRAM_BOT_TOKEN": TOKEN})
    assert saved == ["DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN"]
    assert env.read_text(encoding="utf-8") == (
        f"# yorum\nDEEPSEEK_API_KEY=yeni-anahtar-987654\nBASKA=dokunma\nTELEGRAM_BOT_TOKEN={TOKEN}\n"
    )
    assert os.environ["DEEPSEEK_API_KEY"] == "yeni-anahtar-987654"
    envfile.update(env, {"DEEPSEEK_API_KEY": None})
    assert "DEEPSEEK_API_KEY" not in envfile.read(env) and "DEEPSEEK_API_KEY" not in os.environ


@pytest.mark.parametrize("key,value,msg", [
    ("PANEL_PASSWORD_HASH", "x", "düzenlenemez"),
    ("DEEPSEEK_API_KEY", "a\nEVIL=1", "satır sonu"),
    ("DEEPSEEK_API_KEY", "   ", "Boş"),
    ("TELEGRAM_ALLOWED_USER_ID", "abc", "rakam"),
    ("TELEGRAM_BOT_TOKEN", "yanlis", "BotFather"),
    ("SUPABASE_URL", "https://x.com/rest/v1", "yol olmadan"),
    ("lower_key", "x", "Geçersiz anahtar"),
])
def test_invalid_values_rejected_and_file_untouched(env, key, value, msg):
    before = env.read_text(encoding="utf-8")
    with pytest.raises(envfile.EnvError, match=msg):
        envfile.update(env, {key: value})
    assert env.read_text(encoding="utf-8") == before


def test_mask_never_reveals():
    assert envfile.mask("sk-cok-gizli-anahtar-1234") == "••••1234"
    assert envfile.mask("kisa") == "••••" and envfile.mask(None) == ""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX izinleri")
def test_permissions_preserved(env):
    os.chmod(env, 0o600)
    envfile.update(env, {"HF_TOKEN": "hf_anahtar-123"})
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_change_password(env, monkeypatch):
    auth.set_password(env, PASSWORD)
    assert auth.verify_password(PASSWORD, os.environ["PANEL_PASSWORD_HASH"])
    with pytest.raises(auth.PasswordError, match="Mevcut"):
        auth.change_password(env, "yanlis", "yeni-sifre-12345", "yeni-sifre-12345")
    with pytest.raises(auth.PasswordError, match="uyuşmuyor"):
        auth.change_password(env, PASSWORD, "yeni-sifre-12345", "baska-sifre-1234")
    with pytest.raises(auth.PasswordError, match="en az"):
        auth.change_password(env, PASSWORD, "kisa", "kisa")
    auth.change_password(env, PASSWORD, "yeni-sifre-12345", "yeni-sifre-12345")
    assert auth.verify_password("yeni-sifre-12345", envfile.read(env)["PANEL_PASSWORD_HASH"])
    auth.THROTTLE.record_success()


def test_settings_page_updates_env(panel_env, env, monkeypatch):  # noqa: F811
    import common

    AppTest, *_ = panel_env
    monkeypatch.setattr(common, "ENV_PATH", env)
    at = _run(AppTest, PANEL / "pages" / "4_⚙️_Ayarlar.py")
    labels = [t.label for t in at.text_input]
    assert any("DeepSeek" in lbl and "••••3456" in lbl for lbl in labels)
    assert not any("eski-anahtar" in lbl for lbl in labels)
    field = next(t for t in at.text_input if t.label.startswith("Telegram kullanıcı"))
    field.input("987654321")
    next(b for b in at.button if "Kaydet" in b.label).click().run()
    assert not at.exception
    assert envfile.read(env)["TELEGRAM_ALLOWED_USER_ID"] == "987654321"
    assert envfile.read(env)["DEEPSEEK_API_KEY"] == "eski-anahtar-123456"
