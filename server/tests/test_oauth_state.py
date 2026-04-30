"""JWT OAuth state helpers (C7.3)."""

from __future__ import annotations

import pytest

from core.oauth_state import mint_extension_oauth_state, mint_web_oauth_state, parse_extension_oauth_state, parse_web_oauth_state


def test_extension_state_roundtrip() -> None:
    tok = mint_extension_oauth_state(
        provider="google",
        redirect_uri="https://abc.chromiumapp.org/oauth2",
        ux_mode="silent",
        account_prompt="normal",
    )
    payload = parse_extension_oauth_state(tok)
    assert payload["provider"] == "google"
    assert payload["ru"] == "https://abc.chromiumapp.org/oauth2"
    assert payload["ux"] == "silent"


def test_web_state_roundtrip() -> None:
    tok = mint_web_oauth_state(provider="yandex", client=None, next_url=None)
    payload = parse_web_oauth_state(tok)
    assert payload["provider"] == "yandex"


def test_extension_state_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_extension_oauth_state("not-a-jwt")
