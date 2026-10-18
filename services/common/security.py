"""FastAPI glue for :mod:`services.common.auth`: dependencies and HTTP errors.

Every public route declares what it needs (``ClaimsDep``, ``DeviceKeyDep``…), so an
unprotected route stands out in review. Errors follow RFC 6750: 401 with
``WWW-Authenticate: Bearer`` when credentials are missing or invalid, 403 when they
are valid but not allowed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from services.common.auth import (
    AuthError,
    AuthSettings,
    Claims,
    ForbiddenError,
    UserDirectory,
    bearer_token,
    check_device_key,
    check_patient_access,
    load_auth_settings,
    require_role,
    require_secret,
    verify_token,
)


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Process-wide auth settings (secrets from the environment)."""
    return load_auth_settings()


@lru_cache(maxsize=1)
def get_users() -> UserDirectory:
    """Process-wide user directory (reloads when the file changes)."""
    return UserDirectory(get_auth_settings().users_path)


def unauthorized(detail: str) -> HTTPException:
    """401 with the bearer challenge."""
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def forbidden(detail: str) -> HTTPException:
    """403 for authenticated callers without permission."""
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)


def claims_from_token(token: str) -> Claims:
    """Verify a raw token (also used by the WebSocket, which cannot send headers)."""
    try:
        return verify_token(token, require_secret(get_auth_settings().token_secret))
    except AuthError as error:
        raise unauthorized(str(error)) from error


def current_claims(authorization: Annotated[str | None, Header()] = None) -> Claims:
    """Dependency: verified claims from ``Authorization: Bearer``."""
    try:
        return claims_from_token(bearer_token(authorization))
    except AuthError as error:
        raise unauthorized(str(error)) from error


ClaimsDep = Annotated[Claims, Depends(current_claims)]
UsersDep = Annotated[UserDirectory, Depends(get_users)]


def patient_claims(claims: ClaimsDep) -> Claims:
    """Dependency: a patient token."""
    try:
        require_role(claims, "patient")
    except ForbiddenError as error:
        raise forbidden(str(error)) from error
    return claims


def clinician_claims(claims: ClaimsDep) -> Claims:
    """Dependency: a clinician token."""
    try:
        require_role(claims, "clinician")
    except ForbiddenError as error:
        raise forbidden(str(error)) from error
    return claims


PatientDep = Annotated[Claims, Depends(patient_claims)]
ClinicianDep = Annotated[Claims, Depends(clinician_claims)]


def ensure_access(claims: Claims, patient_id: str, users: UserDirectory) -> None:
    """Raise 403 unless the caller may access ``patient_id``."""
    try:
        check_patient_access(claims, patient_id, users)
    except ForbiddenError as error:
        raise forbidden(str(error)) from error


def device_key(x_device_key: Annotated[str | None, Header()] = None) -> None:
    """Dependency: a valid ``X-Device-Key`` for signal uploads."""
    try:
        check_device_key(x_device_key, get_auth_settings().device_key)
    except AuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error


DeviceKeyDep = Annotated[None, Depends(device_key)]
