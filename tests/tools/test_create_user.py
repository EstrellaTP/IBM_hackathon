import json

from services.common import auth
from tools import create_user


def test_create_user_stores_only_a_hash_and_prints_the_password_once(tmp_path, capsys):
    path = tmp_path / "users.json"
    create_user.main(
        ["--role", "patient", "--username", "pat", "--new-patient", "--users-file", str(path)]
    )
    output = capsys.readouterr().out
    password = output.strip().splitlines()[-1].removeprefix("password: ")
    stored = json.loads(path.read_text())["users"][0]
    assert password not in path.read_text()
    assert auth.verify_password(password, stored["password_hash"])
    assert stored["patient_id"].startswith("p_")


def test_create_user_replaces_an_existing_account(tmp_path):
    path = tmp_path / "users.json"
    args = ["--role", "clinician", "--username", "doc", "--users-file", str(path)]
    create_user.main([*args, "--assign", "p_aaaa1111"])
    create_user.main([*args, "--assign", "p_bbbb2222"])
    users = json.loads(path.read_text())["users"]
    assert len(users) == 1 and users[0]["assigned_patients"] == ["p_bbbb2222"]
