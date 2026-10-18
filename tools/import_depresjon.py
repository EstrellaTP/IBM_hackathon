"""Load the demo patients (DEPRESJON people held out of training) into the store.

Runs on the VM, where DEPRESJON lives, against the store's loopback port::

    python3 -m tools.import_depresjon --store-url http://127.0.0.1:8001

For each person in ``ml.models.train.DEMO_HOLDOUT`` (never seen by the deployed
model), it stores encrypted hourly activity and a minimal profile (sex, age group,
device) under a new pseudonymous ``patient_id``. Dates are shifted so the recording
ends today: the real recording dates (2003) are never stored. The mapping between
the DEPRESJON id and the new pseudonym is printed and written to
``~/demo_patients.json`` on the VM (outside git).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

from ml.data import loaders
from ml.features import hourly
from ml.models.train import DEMO_HOLDOUT

logger = logging.getLogger("import_depresjon")

DEMO_MAPPING_PATH = Path.home() / "demo_patients.json"


def pseudonym(person_id: str) -> str:
    """Stable pseudonymous id for a demo person (hex, matches PATIENT_ID_PATTERN)."""
    return "p_demo" + hashlib.sha256(person_id.encode()).hexdigest()[:8]


def import_person(client: httpx.Client, person_id: str, scores) -> dict:
    """Store one person's profile and hourly activity; return the mapping entry."""
    row = scores.set_index("person_id").loc[person_id]
    frame = hourly.depresjon_hourly(loaders.load_depresjon_activity(person_id), person_id)
    days = int(frame["day"].max())
    start = date.today() - timedelta(days=days - 1)
    patient_id = pseudonym(person_id)
    profile = {
        "sex": row["sex"],
        "age_group": row["age_group"],
        "device": "actiwatch",
        "recording_start": start.isoformat(),
    }
    client.put(f"/api/v1/patients/{patient_id}/profile", json=profile).raise_for_status()
    hours = frame[["day", "hour", "activity", "valid"]].to_dict("records")
    client.post(f"/api/v1/patients/{patient_id}/activity-hours", json=hours).raise_for_status()
    logger.info("%s -> %s: %d days, %d hours", person_id, patient_id, days, len(hours))
    return {
        "dataset_id": person_id,
        "patient_id": patient_id,
        "group": row["group"],
        "days": days,
        "recording_start": start.isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    """Import every demo person."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description="Import DEPRESJON demo patients into the store.")
    parser.add_argument("--store-url", default="http://127.0.0.1:8001")
    args = parser.parse_args(argv)
    scores = loaders.load_depresjon_scores()
    with httpx.Client(base_url=args.store_url, timeout=60) as client:
        mapping = [import_person(client, person, scores) for person in DEMO_HOLDOUT]
    DEMO_MAPPING_PATH.write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    for entry in mapping:
        print(f"{entry['patient_id']}  ({entry['group']}, {entry['days']} days)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
