"""Authentication and authorisation shared by the public services (issue #14).

Health data never leaves LinuxONE, and since the frontend may be served from another
origin (Vercel), every check happens here, in the services, never in the browser:

* **Users** live in a JSON file on the VM only (``AUTH_USERS_PATH``, gitignored,
  mounted read-only). Passwords are hashed with scrypt (stdlib, RFC 7914) and
  compared in constant time. Two roles: ``patient`` (bound to one ``patient_id``) and
  ``clinician`` (sees only the patients assigned to them).
* **Session tokens** are compact JWTs signed with HMAC-SHA256 (HS256, RFC 7519),
  implemented with the standard library: claims ``sub``, ``role``, ``patient_id``,
  ``iat``, ``exp`` (12 h). The signing secret ``AUTH_TOKEN_SECRET`` is generated on
  the VM into ``infra/.env``. Assignments are looked up at request time, so a change
  in the user file takes effect without new tokens.
* **Devices** (bands, simulator) authenticate signal uploads with a shared
  ``DEVICE_KEY`` in the ``X-Device-Key`` header.

Login failures always return the same message, so usernames cannot be probed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Role = Literal["patient", "clinician"]

TOKEN_LIFETIME_SECONDS = 12 * 3600
# scrypt cost parameters (RFC 7914): N=2^14, r=8, p=1 uses 16 MiB and ~50 ms per
# check, the common interactive-login setting; stored with each hash.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_SALT_BYTES = 16
SCRYPT_KEY_BYTES = 32
DEFAULT_USERS_PATH = "/etc/holter/users.json"


class AuthError(Exception):
    """Authentication failed (HTTP 401)."""


class ForbiddenError(Exception):
    """Authenticated but not allowed (HTTP 403)."""


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    """Return ``scrypt$N$r$p$salt$hash`` for a password (random salt)."""
    salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_KEY_BYTES
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored scrypt hash in constant time."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(
        password.encode(),
        salt=_unb64(salt),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(_unb64(expected)),
    )
    return hmac.compare_digest(digest, _unb64(expected))


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class User:
    """An account of the prototype."""

    username: str
    role: Role
    password_hash: str
    display_name: str = ""
    patient_id: str | None = None  # patients: the patient they are
    assigned_patients: tuple[str, ...] = ()  # clinicians: who they may see


@dataclass
class UserDirectory:
    """Users read from a JSON file, reloaded when the file changes."""

    path: Path
    _users: dict[str, User] = field(default_factory=dict, init=False)
    _mtime: float = field(default=-1.0, init=False)

    def _reload(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._users, self._mtime = {}, -1.0
            return
        if mtime == self._mtime:
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._users = {
            item["username"]: User(
                username=item["username"],
                role=item["role"],
                password_hash=item["password_hash"],
                display_name=item.get("display_name", ""),
                patient_id=item.get("patient_id"),
                assigned_patients=tuple(item.get("assigned_patients", ())),
            )
            for item in raw.get("users", [])
        }
        self._mtime = mtime
        logger.info("loaded %d users", len(self._users))

    def get(self, username: str) -> User | None:
        """Return a user by name, or ``None``."""
        self._reload()
        return self._users.get(username)

    def authenticate(self, username: str, password: str) -> User:
        """Return the user if the password matches.

        Raises:
            AuthError: Same error for an unknown user and a wrong password.
        """
        user = self.get(username)
        # Hash even for unknown users so response time does not reveal them.
        stored = user.password_hash if user else hash_password(secrets.token_hex(8))
        if not verify_password(password, stored) or user is None:
            raise AuthError("invalid username or password")
        return user


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Claims:
    """Verified token content."""

    sub: str
    role: Role
    patient_id: str | None
    exp: int


def issue_token(user: User, secret: str, now: float | None = None) -> tuple[str, int]:
    """Sign a session token for a user; return ``(token, expiry unix time)``."""
    issued = int(now if now is not None else time.time())
    claims = {
        "sub": user.username,
        "role": user.role,
        "patient_id": user.patient_id,
        "iat": issued,
        "exp": issued + TOKEN_LIFETIME_SECONDS,
    }
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256)
    return f"{header}.{payload}.{_b64(signature.digest())}", claims["exp"]


def verify_token(token: str, secret: str, now: float | None = None) -> Claims:
    """Check signature and expiry of a session token.

    Raises:
        AuthError: If the token is malformed, tampered with or expired.
    """
    try:
        header, payload, signature = token.split(".")
        expected = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256)
        if not hmac.compare_digest(_unb64(signature), expected.digest()):
            raise AuthError("invalid token")
        if json.loads(_unb64(header)).get("alg") != "HS256":
            raise AuthError("invalid token")
        claims = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError) as error:
        raise AuthError("invalid token") from error
    if claims.get("exp", 0) < (now if now is not None else time.time()):
        raise AuthError("token expired")
    return Claims(
        sub=claims["sub"],
        role=claims["role"],
        patient_id=claims.get("patient_id"),
        exp=claims["exp"],
    )


def bearer_token(authorization: str | None) -> str:
    """Extract the token from an ``Authorization: Bearer`` header.

    Raises:
        AuthError: If the header is missing or not a bearer token.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    return authorization.split(" ", 1)[1].strip()


# --------------------------------------------------------------------------- #
# Settings and checks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AuthSettings:
    """Secrets and files used by the checks (from the environment)."""

    token_secret: str
    device_key: str
    users_path: Path
    allowed_origins: tuple[str, ...]


def load_auth_settings(environ: dict[str, str] | None = None) -> AuthSettings:
    """Read ``AUTH_TOKEN_SECRET``, ``DEVICE_KEY``, ``AUTH_USERS_PATH``, ``ALLOWED_ORIGINS``.

    Missing secrets give empty strings, which make every check fail closed.
    """
    environ = dict(os.environ) if environ is None else environ
    origins = tuple(o.strip() for o in environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip())
    return AuthSettings(
        token_secret=environ.get("AUTH_TOKEN_SECRET", ""),
        device_key=environ.get("DEVICE_KEY", ""),
        users_path=Path(environ.get("AUTH_USERS_PATH", DEFAULT_USERS_PATH)),
        allowed_origins=origins,
    )


def require_secret(secret: str) -> str:
    """Fail closed when a secret is not configured."""
    if not secret:
        raise AuthError("authentication is not configured on this server")
    return secret


def check_device_key(given: str | None, expected: str) -> None:
    """Verify the ``X-Device-Key`` of a signal upload.

    Raises:
        AuthError: If missing, wrong or not configured.
    """
    require_secret(expected)
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise AuthError("invalid device key")


def require_role(claims: Claims, role: Role) -> None:
    """Raise :class:`ForbiddenError` unless the token has the given role."""
    if claims.role != role:
        raise ForbiddenError(f"{role} access only")


def check_patient_access(claims: Claims, patient_id: str, users: UserDirectory) -> None:
    """Allow a patient to reach only themselves, a clinician only assigned patients.

    Raises:
        ForbiddenError: Otherwise.
    """
    if claims.role == "patient":
        if claims.patient_id != patient_id:
            raise ForbiddenError("patients can only access their own data")
        return
    user = users.get(claims.sub)
    if user is None or patient_id not in user.assigned_patients:
        raise ForbiddenError("patient not assigned to this clinician")


def assigned_patients(claims: Claims, users: UserDirectory) -> tuple[str, ...]:
    """Patients a clinician may see (empty for other roles)."""
    user = users.get(claims.sub)
    return user.assigned_patients if user and claims.role == "clinician" else ()
