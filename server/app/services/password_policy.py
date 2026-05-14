"""Product password rules for future email/password flows (ADMIN_OPS sprint 6 Epic R)."""

from __future__ import annotations

import re

_PASSWORD_MIN_LEN = 12
_PASSWORD_MAX_LEN = 256


class PasswordPolicyError(ValueError):
    pass


def assert_password_meets_product_policy(password: str) -> None:
    """
    Enforce minimal MVP policy when password-based auth is introduced.

    Raises:
        PasswordPolicyError: if the password is too weak.
    """
    if not isinstance(password, str):
        raise PasswordPolicyError("password must be a string")
    p = password
    if len(p) < _PASSWORD_MIN_LEN:
        raise PasswordPolicyError(f"password must be at least {_PASSWORD_MIN_LEN} characters")
    if len(p) > _PASSWORD_MAX_LEN:
        raise PasswordPolicyError("password is too long")
    if p.strip() != p:
        raise PasswordPolicyError("password must not have leading or trailing whitespace")
    classes = 0
    if re.search(r"[a-z]", p):
        classes += 1
    if re.search(r"[A-Z]", p):
        classes += 1
    if re.search(r"\d", p):
        classes += 1
    if re.search(r"[^\w\s]", p):
        classes += 1
    if classes < 3:
        raise PasswordPolicyError(
            "password must include at least three of: lowercase, uppercase, digit, symbol"
        )
