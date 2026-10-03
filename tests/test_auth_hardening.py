"""The edit password and session key: no public fallback on Railway, and a
cap on how fast the password can be guessed."""

import pytest

# Through the module, never `from app import ...` — see test_places.py for why.
import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    app_module._login_failures.clear()
    with app_module.app.test_client() as c:
        yield c
    app_module._login_failures.clear()


def _login(c, password, ip="203.0.113.7"):
    return c.post("/api/auth/login", json={"password": password},
                  environ_base={"REMOTE_ADDR": ip})


# ── required secrets ─────────────────────────────────────────────────────────

def test_secret_falls_back_locally(monkeypatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    monkeypatch.delenv("SOME_SECRET", raising=False)
    assert app_module._required_secret("SOME_SECRET", "dev-default") == "dev-default"


def test_secret_missing_on_railway_refuses_to_boot(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.delenv("SOME_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SOME_SECRET"):
        app_module._required_secret("SOME_SECRET", "dev-default")


def test_secret_blank_on_railway_refuses_to_boot(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("SOME_SECRET", "   ")
    with pytest.raises(RuntimeError, match="SOME_SECRET"):
        app_module._required_secret("SOME_SECRET", "dev-default")


def test_secret_equal_to_public_default_on_railway_refuses_to_boot(monkeypatch):
    # Pasting the repo's default into Railway is the same as not setting it.
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("SOME_SECRET", "dev-default")
    with pytest.raises(RuntimeError, match="SOME_SECRET"):
        app_module._required_secret("SOME_SECRET", "dev-default")


def test_secret_set_on_railway_is_used(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("SOME_SECRET", "a-real-value")
    assert app_module._required_secret("SOME_SECRET", "dev-default") == "a-real-value"


# ── login rate limit ─────────────────────────────────────────────────────────

def test_wrong_password_is_403_until_the_limit(client):
    for _ in range(app_module.LOGIN_MAX_FAILURES):
        assert _login(client, "nope").status_code == 403


def test_locked_out_after_too_many_failures(client):
    for _ in range(app_module.LOGIN_MAX_FAILURES):
        _login(client, "nope")
    r = _login(client, "nope")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_lockout_blocks_even_the_right_password(client):
    # Otherwise the lockout only slows guessing down by one request.
    for _ in range(app_module.LOGIN_MAX_FAILURES):
        _login(client, "nope")
    assert _login(client, app_module.EDIT_PASSWORD).status_code == 429


def test_lockout_is_per_client(client):
    for _ in range(app_module.LOGIN_MAX_FAILURES):
        _login(client, "nope", ip="203.0.113.7")
    assert _login(client, app_module.EDIT_PASSWORD, ip="198.51.100.2").status_code == 200


def test_lockout_expires(client, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(app_module.time, "monotonic", lambda: now[0])
    for _ in range(app_module.LOGIN_MAX_FAILURES):
        _login(client, "nope")
    assert _login(client, "nope").status_code == 429
    now[0] += app_module.LOGIN_WINDOW_SECONDS + 1
    assert _login(client, app_module.EDIT_PASSWORD).status_code == 200


def test_success_clears_earlier_failures(client):
    for _ in range(app_module.LOGIN_MAX_FAILURES - 1):
        _login(client, "nope")
    assert _login(client, app_module.EDIT_PASSWORD).status_code == 200
    for _ in range(app_module.LOGIN_MAX_FAILURES):
        assert _login(client, "nope").status_code == 403


def test_client_ip_is_the_hop_railway_appended(client):
    # Railway's proxy appends the real address to X-Forwarded-For; anything to
    # its left came from the client and is forgeable. Rotating the forged part
    # must not buy fresh attempts.
    for i in range(app_module.LOGIN_MAX_FAILURES):
        client.post("/api/auth/login", json={"password": "nope"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"})
    r = client.post("/api/auth/login", json={"password": "nope"},
                    headers={"X-Forwarded-For": "10.0.0.99, 203.0.113.7"})
    assert r.status_code == 429


def test_non_string_password_is_rejected_not_500(client):
    assert client.post("/api/auth/login", json={"password": 123}).status_code == 403
