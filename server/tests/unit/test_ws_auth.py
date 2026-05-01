"""Разбор JWT для WebSocket (без поднятия S3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.api.ws_auth import extract_access_token_for_websocket


@pytest.fixture(autouse=True)
def _clear_ws_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VT_WS_REQUIRE_SUBPROTOCOL", raising=False)
    monkeypatch.delenv("VT_WS_ALLOW_QUERY_TOKEN", raising=False)


def test_token_from_query() -> None:
    ws = MagicMock()
    ws.query_params = {"access_token": "eyJ.a.b"}
    ws.headers = {}
    tok, sub, rej = extract_access_token_for_websocket(ws)
    assert tok == "eyJ.a.b"
    assert sub is None
    assert rej is None


def test_token_from_bearer_protocol() -> None:
    ws = MagicMock()
    ws.query_params = {}
    ws.headers = {"sec-websocket-protocol": "bearer.eyJ.x.y"}
    tok, sub, rej = extract_access_token_for_websocket(ws)
    assert tok == "eyJ.x.y"
    assert sub == "bearer.eyJ.x.y"
    assert rej is None


def test_query_wins_over_protocol() -> None:
    ws = MagicMock()
    ws.query_params = {"access_token": "from_query"}
    ws.headers = {"sec-websocket-protocol": "bearer.from_proto"}
    tok, _, rej = extract_access_token_for_websocket(ws)
    assert tok == "from_query"
    assert rej is None


def test_strict_rejects_query_even_with_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_WS_REQUIRE_SUBPROTOCOL", "1")
    ws = MagicMock()
    ws.query_params = {"access_token": "from_query"}
    ws.headers = {"sec-websocket-protocol": "bearer.from_proto"}
    tok, sub, rej = extract_access_token_for_websocket(ws)
    assert tok is None
    assert sub is None
    assert rej == "query_token_forbidden"


def test_strict_bearer_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_WS_REQUIRE_SUBPROTOCOL", "1")
    ws = MagicMock()
    ws.query_params = {}
    ws.headers = {"sec-websocket-protocol": "bearer.only_proto"}
    tok, sub, rej = extract_access_token_for_websocket(ws)
    assert tok == "only_proto"
    assert sub == "bearer.only_proto"
    assert rej is None


def test_allow_query_overrides_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_WS_REQUIRE_SUBPROTOCOL", "1")
    monkeypatch.setenv("VT_WS_ALLOW_QUERY_TOKEN", "1")
    ws = MagicMock()
    ws.query_params = {"access_token": "q"}
    ws.headers = {}
    tok, _, rej = extract_access_token_for_websocket(ws)
    assert tok == "q"
    assert rej is None


def test_missing_token() -> None:
    ws = MagicMock()
    ws.query_params = {}
    ws.headers = {}
    tok, sub, rej = extract_access_token_for_websocket(ws)
    assert tok is None
    assert sub is None
    assert rej == "missing_token"
