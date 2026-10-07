from __future__ import annotations

MIN_DATABASE_PASSWORD_LENGTH = 12


def validate_new_database_password(password: str) -> None:
    if len(password) < MIN_DATABASE_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_DATABASE_PASSWORD_LENGTH} characters."
        )