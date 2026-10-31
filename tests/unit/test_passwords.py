from __future__ import annotations

import pytest

from app.auth.passwords import hash_password, verify_password


def test_hash_and_verify_round_trip() -> None:
    hashed = hash_password("Correct#Horse1")
    assert hashed.startswith("$2b$12$")  # bcrypt, cost 12
    assert verify_password("Correct#Horse1", hashed)


def test_wrong_password_fails() -> None:
    hashed = hash_password("Correct#Horse1")
    assert not verify_password("wrong-password", hashed)


def test_password_over_72_bytes_is_rejected() -> None:
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("a" * 73)


def test_malformed_hash_does_not_crash() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")
