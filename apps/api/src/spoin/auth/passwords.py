"""Password hashing with bcrypt.

Thin wrapper so the rest of the codebase never imports bcrypt directly —
if we ever switch to argon2 or scrypt, only this file changes.
"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """Hash a plaintext password. Returns the bcrypt hash as a string."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plaintext password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())
