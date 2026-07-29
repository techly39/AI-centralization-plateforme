"""API-key generation and hashing.

Keys are high-entropy random tokens (not human passwords), so a fast one-way
hash (SHA-256) is the right tool: it lets us store and index ``api_key_hash``
without ever keeping the plaintext, and there is nothing to brute-force. The
plaintext is shown to the operator exactly once at creation time.
"""

from __future__ import annotations

import hashlib
import secrets

API_KEY_PREFIX = "fk_"  # "fund key" — makes keys recognisable in logs/config.


def generate_api_key() -> str:
    """Return a fresh, unguessable API key (shown to the operator once)."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """Deterministic SHA-256 hex digest used for storage and lookup."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
