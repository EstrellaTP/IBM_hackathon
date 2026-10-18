"""Environment-based configuration of the store service (12-factor).

Variables (documented in ``infra/env.example``):

* ``STORE_DB_PATH``: SQLite database file, on the encrypted-at-rest named volume.
* ``STORE_ENCRYPTION_KEY``: Fernet key (required, generated on the VM, never committed).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = "/data/holter.sqlite3"


class MissingSettingError(RuntimeError):
    """A required environment variable is not set."""


@dataclass(frozen=True)
class StoreSettings:
    """Configuration of the store.

    Attributes:
        db_path: SQLite database file.
        encryption_key: Fernet key used to encrypt sensitive fields.
    """

    db_path: Path
    encryption_key: bytes


def load_settings(environ: dict[str, str] | None = None) -> StoreSettings:
    """Read the store configuration from the environment.

    Args:
        environ: Mapping to read from; defaults to ``os.environ``.

    Returns:
        The settings.

    Raises:
        MissingSettingError: If ``STORE_ENCRYPTION_KEY`` is missing: the store refuses
            to run unencrypted.
    """
    environ = dict(os.environ) if environ is None else environ
    key = environ.get("STORE_ENCRYPTION_KEY", "").strip()
    if not key:
        raise MissingSettingError("STORE_ENCRYPTION_KEY is required (see infra/env.example)")
    return StoreSettings(
        db_path=Path(environ.get("STORE_DB_PATH", DEFAULT_DB_PATH)),
        encryption_key=key.encode("ascii"),
    )
