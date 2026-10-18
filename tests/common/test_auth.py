import json
import os
import time

import pytest

from services.common import auth

SECRET = "test-secret-not-used-anywhere"


def _users_file(tmp_path, users):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": users}), encoding="utf-8")
    return path


def _user(username, role, password="pw", **extra):
    return {
        "username": username,
        "role": role,
        "password_hash": auth.hash_password(password),
        **extra,
    }


def test_password_hash_verifies_only_the_right_password():
    stored = auth.hash_password("correct horse")
    assert stored.startswith("scrypt$")
    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("wrong", stored)
    assert auth.hash_password("correct horse") != stored  # random salt


def test_token_round_trip_and_tamper_detection():
    user = auth.User("pat", "patient", "x", patient_id="p_abcd1234")
    token, expires = auth.issue_token(user, SECRET, now=1000)
    claims = auth.verify_token(token, SECRET, now=1001)
    assert (claims.sub, claims.role, claims.patient_id) == ("pat", "patient", "p_abcd1234")
    assert expires == 1000 + auth.TOKEN_LIFETIME_SECONDS
    header, payload, signature = token.split(".")
    forged = auth._b64(json.dumps({"sub": "pat", "role": "clinician", "exp": 9e9}).encode())
    with pytest.raises(auth.AuthError):
        auth.verify_token(f"{header}.{forged}.{signature}", SECRET)
    with pytest.raises(auth.AuthError):
        auth.verify_token(token, "another-secret", now=1001)


def test_expired_token_is_rejected():
    token, _ = auth.issue_token(auth.User("c", "clinician", "x"), SECRET, now=1000)
    with pytest.raises(auth.AuthError, match="expired"):
        auth.verify_token(token, SECRET, now=1000 + auth.TOKEN_LIFETIME_SECONDS + 1)


def test_unknown_user_and_wrong_password_give_the_same_error(tmp_path):
    directory = auth.UserDirectory(_users_file(tmp_path, [_user("ana", "clinician")]))
    with pytest.raises(auth.AuthError) as unknown:
        directory.authenticate("nobody", "pw")
    with pytest.raises(auth.AuthError) as wrong:
        directory.authenticate("ana", "nope")
    assert str(unknown.value) == str(wrong.value)
    assert directory.authenticate("ana", "pw").username == "ana"


def test_user_directory_reloads_when_the_file_changes(tmp_path):
    path = _users_file(tmp_path, [_user("ana", "clinician")])
    directory = auth.UserDirectory(path)
    assert directory.get("bob") is None
    time.sleep(0.01)
    path.write_text(json.dumps({"users": [_user("bob", "clinician")]}), encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert directory.get("bob") is not None


def test_patient_reaches_only_themselves_and_clinician_only_assigned(tmp_path):
    directory = auth.UserDirectory(
        _users_file(tmp_path, [_user("doc", "clinician", assigned_patients=["p_aaaa1111"])])
    )
    patient = auth.Claims("pat", "patient", "p_aaaa1111", exp=0)
    clinician = auth.Claims("doc", "clinician", None, exp=0)
    auth.check_patient_access(patient, "p_aaaa1111", directory)
    auth.check_patient_access(clinician, "p_aaaa1111", directory)
    with pytest.raises(auth.ForbiddenError):
        auth.check_patient_access(patient, "p_bbbb2222", directory)
    with pytest.raises(auth.ForbiddenError):
        auth.check_patient_access(clinician, "p_bbbb2222", directory)


def test_device_key_fails_closed_when_not_configured():
    with pytest.raises(auth.AuthError):
        auth.check_device_key("anything", "")
    with pytest.raises(auth.AuthError):
        auth.check_device_key("wrong", "right")
    auth.check_device_key("right", "right")
