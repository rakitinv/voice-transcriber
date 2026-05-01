"""effective_turn_level_retranscription merge (server YAML + user.preferences)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.config import app_config
from core.diarization_prefs import effective_turn_level_retranscription


def _user(prefs: dict) -> SimpleNamespace:
    return SimpleNamespace(preferences=prefs)


@pytest.fixture
def server_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_config.diarization, "turn_level_retranscription", False)


@pytest.fixture
def server_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_config.diarization, "turn_level_retranscription", True)


def test_none_user_follows_server(server_on: None) -> None:
    assert effective_turn_level_retranscription(None) is True


def test_no_prefs_follows_server(server_off: None) -> None:
    assert effective_turn_level_retranscription(_user({})) is False


def test_use_custom_true_respects_bool(server_off: None) -> None:
    u = _user(
        {
            "diarization_turn_level_retranscription_use_custom": True,
            "diarization_turn_level_retranscription": True,
        }
    )
    assert effective_turn_level_retranscription(u) is True


def test_use_custom_true_false_overrides_server_on(server_on: None) -> None:
    u = _user(
        {
            "diarization_turn_level_retranscription_use_custom": True,
            "diarization_turn_level_retranscription": False,
        }
    )
    assert effective_turn_level_retranscription(u) is False


def test_use_custom_missing_value_falls_back_to_server(server_on: None) -> None:
    u = _user({"diarization_turn_level_retranscription_use_custom": True})
    assert effective_turn_level_retranscription(u) is True
