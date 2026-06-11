"""Exactly one auth mechanism (static key or OIDC) must be configured."""

import pytest

from notmuchproxy.config import check_auth_config, oidc_config

OIDC_ENV = {
    "NOTMUCHPROXY_OIDC_CONFIG_URL": "https://idp.example.com/.well-known/openid-configuration",
    "NOTMUCHPROXY_OIDC_CLIENT_ID": "notmuchproxy",
    "NOTMUCHPROXY_OIDC_CLIENT_SECRET": "shhh",
    "NOTMUCHPROXY_PUBLIC_URL": "https://notmuch.example.com",
}


def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTMUCHPROXY_API_KEY", raising=False)
    for var in OIDC_ENV:
        monkeypatch.delenv(var, raising=False)


def test_no_oidc_env_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    assert oidc_config() is None


def test_complete_oidc_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    for var, value in OIDC_ENV.items():
        monkeypatch.setenv(var, value)
    cfg = oidc_config()
    assert cfg is not None
    assert cfg.client_id == "notmuchproxy"
    check_auth_config()  # should not raise


def test_partial_oidc_config_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("NOTMUCHPROXY_OIDC_CONFIG_URL", "https://idp.example.com")
    with pytest.raises(RuntimeError, match="NOTMUCHPROXY_OIDC_CLIENT_ID"):
        oidc_config()


def test_no_auth_at_all_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    with pytest.raises(RuntimeError, match="no auth configured"):
        check_auth_config()


def test_both_mechanisms_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("NOTMUCHPROXY_API_KEY", "key")
    for var, value in OIDC_ENV.items():
        monkeypatch.setenv(var, value)
    with pytest.raises(RuntimeError, match="pick one"):
        check_auth_config()


def test_static_key_alone_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("NOTMUCHPROXY_API_KEY", "key")
    check_auth_config()  # should not raise
