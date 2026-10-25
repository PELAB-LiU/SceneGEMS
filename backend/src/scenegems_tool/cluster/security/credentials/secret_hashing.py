"""New secrets and how they are stored.

Stored secrets are salted scrypt hashes, so a leaked store does not reveal them even for
the operator-chosen master broker password. A pairing token must be found by its value,
so it is stored under its SHA-256 instead; that is safe because tokens are random 256-bit
values the master generates.
"""

import base64
import hashlib
import hmac
import secrets

_SCHEME = "scrypt"
_N, _R, _P = 2**14, 8, 1
_SALT_BYTES = 16
_KEY_BYTES = 32


def new_secret() -> str:
    """A random 256-bit secret, URL safe."""
    return secrets.token_urlsafe(32)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(secret: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES, maxmem=64 * 1024 * 1024)


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    return f"{_SCHEME}${_N}${_R}${_P}${_b64(salt)}${_b64(_scrypt(secret, salt, _N, _R, _P))}"


def verify_secret(secret: str, stored_hash: str) -> bool:
    """Constant-time check of a secret against a stored hash; malformed hashes never match."""
    try:
        scheme, n, r, p, salt, expected = stored_hash.split("$")
        if scheme != _SCHEME:
            return False
        actual = _scrypt(secret, _unb64(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def token_lookup_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
