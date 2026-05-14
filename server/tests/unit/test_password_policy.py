"""Sprint 6: password policy helper (Epic R)."""

from __future__ import annotations

import pytest

from app.services.password_policy import PasswordPolicyError, assert_password_meets_product_policy


def test_password_too_short() -> None:
    with pytest.raises(PasswordPolicyError):
        assert_password_meets_product_policy("Short1!")


def test_password_requires_character_classes() -> None:
    with pytest.raises(PasswordPolicyError):
        assert_password_meets_product_policy("onlylowercaseonly")


def test_password_ok() -> None:
    assert_password_meets_product_policy("CorrectHorseBattery99!")


def test_password_rejects_whitespace_padding() -> None:
    with pytest.raises(PasswordPolicyError):
        assert_password_meets_product_policy("  ValidHorse99!  ")
