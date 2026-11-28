"""Single source of truth for the account password policy.

The same rules are enforced by the Pydantic schemas (422 before any work is
done) and by the authentication endpoints (400 with a human-readable reason).
"""
from __future__ import annotations

import string

MIN_LENGTH = 8
MAX_LENGTH = 256
SPECIAL_CHARACTERS = frozenset(string.punctuation + " ")


def password_policy_errors(password: str) -> list[str]:
    """Return every unmet rule for ``password``.

    Args:
        password: Candidate plaintext password.

    Returns:
        A list of specific, user-facing messages; empty when compliant.
    """
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Password must be at least {MIN_LENGTH} characters long")
    if len(password) > MAX_LENGTH:
        problems.append(f"Password must be at most {MAX_LENGTH} characters long")
    if not any(char.isupper() for char in password):
        problems.append("Password must contain an uppercase letter")
    if not any(char.islower() for char in password):
        problems.append("Password must contain a lowercase letter")
    if not any(char.isdigit() for char in password):
        problems.append("Password must contain a digit")
    if not any(char in SPECIAL_CHARACTERS for char in password):
        problems.append("Password must contain a special character")
    return problems


def password_strength_error(password: str) -> str | None:
    """Return the first unmet rule, or ``None`` when the password is valid."""
    problems = password_policy_errors(password)
    return problems[0] if problems else None


def validate_password(password: str) -> str:
    """Pydantic-compatible validator that raises on a weak password."""
    problems = password_policy_errors(password)
    if problems:
        raise ValueError("; ".join(problems))
    return password


__all__ = [
    "MAX_LENGTH",
    "MIN_LENGTH",
    "SPECIAL_CHARACTERS",
    "password_policy_errors",
    "password_strength_error",
    "validate_password",
]
