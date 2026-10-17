"""Environment-based configuration for the detector (12-factor).

Every parameter of :class:`~services.detector.core.DetectorConfig` can be
overridden with an environment variable prefixed ``DETECTOR_``, for example
``DETECTOR_HR_Z_THRESHOLD=2.5``. Defaults are documented in
``infra/env.example`` and in the dataclass itself.
"""

from __future__ import annotations

import os
from dataclasses import fields

from services.detector.core import DetectorConfig

ENV_PREFIX = "DETECTOR_"


def load_config(environ: dict[str, str] | None = None) -> DetectorConfig:
    """Build a :class:`DetectorConfig` from environment variables.

    Args:
        environ: Mapping to read from; defaults to ``os.environ``.

    Returns:
        The configuration, with defaults for every variable not set.

    Raises:
        ValueError: If a variable cannot be converted to the field's type.
    """
    environ = dict(os.environ) if environ is None else environ
    overrides: dict[str, float | int] = {}
    for config_field in fields(DetectorConfig):
        raw = environ.get(ENV_PREFIX + config_field.name.upper())
        if raw is None:
            continue
        cast = int if config_field.type in (int, "int") else float
        try:
            overrides[config_field.name] = cast(raw)
        except ValueError as error:
            raise ValueError(
                f"{ENV_PREFIX}{config_field.name.upper()} must be {cast.__name__}, got {raw!r}"
            ) from error
    return DetectorConfig(**overrides)
