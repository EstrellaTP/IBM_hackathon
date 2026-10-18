r"""Create or update a login of the prototype (patient or clinician), on the VM.

::

    python3 -m tools.create_user --role clinician --username clinician.demo \\
        --display-name "Demo clinician" --assign p_1234abcd... --assign p_...
    python3 -m tools.create_user --role patient --username patient.demo --new-patient

Writes ``infra/users.json`` (gitignored, read by the services through a read-only
mount; changes apply without restarting). The password is generated, stored only as
an scrypt hash and printed once; it never goes into git or an issue. ``--new-patient``
creates a fresh random pseudonymous ``patient_id`` for the account.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

from services.common.auth import hash_password
from services.common.schemas import new_patient_id

USERS_PATH = Path(__file__).resolve().parents[1] / "infra" / "users.json"
PASSWORD_BYTES = 12  # 16 URL-safe characters, ~96 bits


def load(path: Path) -> dict:
    """Read the users file, or an empty directory."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"users": []}


def upsert(directory: dict, entry: dict) -> None:
    """Insert or replace the user with the same username."""
    directory["users"] = [u for u in directory["users"] if u["username"] != entry["username"]]
    directory["users"].append(entry)


def main(argv: list[str] | None = None) -> int:
    """Create the account and print its password once."""
    parser = argparse.ArgumentParser(description="Create a patient or clinician login.")
    parser.add_argument("--role", choices=["patient", "clinician"], required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", default="")
    parser.add_argument("--patient-id", help="patient accounts: existing pseudonymous id")
    parser.add_argument("--new-patient", action="store_true", help="patient accounts: new id")
    parser.add_argument("--assign", action="append", default=[], help="clinician: patient id")
    parser.add_argument("--users-file", type=Path, default=USERS_PATH)
    args = parser.parse_args(argv)

    entry: dict = {"username": args.username, "role": args.role, "display_name": args.display_name}
    if args.role == "patient":
        if not (args.patient_id or args.new_patient):
            parser.error("patient accounts need --patient-id or --new-patient")
        entry["patient_id"] = args.patient_id or new_patient_id()
    else:
        entry["assigned_patients"] = sorted(set(args.assign))
    password = secrets.token_urlsafe(PASSWORD_BYTES)
    entry["password_hash"] = hash_password(password)

    directory = load(args.users_file)
    upsert(directory, entry)
    args.users_file.write_text(json.dumps(directory, indent=1), encoding="utf-8")
    args.users_file.chmod(0o644)  # read by the unprivileged service users; hashes only
    summary = {k: v for k, v in entry.items() if k != "password_hash"}
    print(json.dumps(summary))
    print(f"password: {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
