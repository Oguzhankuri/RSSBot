import pytest

from bulten import auth
from tests.test_panel import PANEL, _run, panel_env  # noqa: F401 — fixture

PASSWORD = "cok-gizli-sifre-42"


def test_hash_and_verify():
    stored = auth.hash_password(PASSWORD)
    assert stored.startswith("scrypt:") and "$" not in stored and PASSWORD not in stored
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("yanlis", stored)
    assert not auth.verify_password(PASSWORD, "bozuk")
    assert not auth.verify_password(PASSWORD, "md5:1:1:1:aa:bb")
    assert auth.hash_password(PASSWORD) != stored  # her seferinde farklı tuz


def test_token_expiry_and_password_change():
    stored = auth.hash_password(PASSWORD)
    token = auth.issue_token("sir", stored, now=1000)
    assert auth.verify_token(token, "sir", stored, now=1001)
    assert not auth.verify_token(token, "sir", stored, now=1000 + auth.SESSION_DAYS * 86400 + 1)
    assert not auth.verify_token(token, "baska-sir", stored, now=1001)
    assert not auth.verify_token(token, "sir", auth.hash_password(PASSWORD), now=1001)  # şifre yenilendi
    for bad in (None, "", "abc", "x.y", "123.!!!", f"{token}x"):
        assert not auth.verify_token(bad, "sir", stored, now=1001)


def test_throttle_backoff():
    t = auth.Throttle()
    for _ in range(auth.FREE_ATTEMPTS):
        t.record_failure(now=0)
    assert t.wait_seconds(now=0) == 0
    t.record_failure(now=0)
    assert t.wait_seconds(now=0) == 2
    for _ in range(30):
        t.record_failure(now=0)
    assert t.wait_seconds(now=0) == auth.MAX_LOCK_SEC
    t.record_success()
    assert t.wait_seconds(now=0) == 0


def test_set_password_cli(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=abc\n", encoding="utf-8")
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert auth.main(["set-password", "--env", str(env)]) == 0
    text = env.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=abc" in text and "PANEL_SESSION_SECRET=" in text and PASSWORD not in text
    stored = [ln for ln in text.splitlines() if ln.startswith("PANEL_PASSWORD_HASH=")][0].split("=", 1)[1]
    assert auth.verify_password(PASSWORD, stored)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "kisa")
    assert auth.main(["set-password", "--env", str(env)]) == 1
    assert auth.main([]) == 2


@pytest.fixture
def gated(panel_env, monkeypatch):
    monkeypatch.setenv("PANEL_PASSWORD_HASH", auth.hash_password(PASSWORD))
    monkeypatch.setenv("PANEL_SESSION_SECRET", "sir")
    auth.THROTTLE.record_success()
    yield panel_env
    auth.THROTTLE.record_success()


def test_panel_requires_password(gated):
    AppTest, *_ = gated
    at = _run(AppTest, PANEL / "app.py")
    assert at.title[0].value == "🔒 Bülten Stüdyosu" and not at.date_input
    at.text_input[0].input("yanlis")
    at.button[0].click().run()
    assert any("yanlış" in e.value for e in at.error)
    at.text_input[0].input(PASSWORD)
    at.button[0].click().run()
    assert not at.exception and at.date_input  # içeri girildi


def test_public_without_password_is_blocked(panel_env, monkeypatch):
    AppTest, *_ = panel_env
    monkeypatch.delenv("PANEL_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("BULTEN_PUBLIC", "1")
    at = _run(AppTest, PANEL / "app.py")
    assert any("şifre tanımlı değil" in e.value for e in at.error) and not at.date_input
