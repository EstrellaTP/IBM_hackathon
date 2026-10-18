import re

from services.common.schemas import PATIENT_ID_PATTERN
from tools.import_depresjon import pseudonym


def test_demo_pseudonyms_are_valid_stable_and_distinct():
    ids = [pseudonym(p) for p in ("condition_3", "condition_11", "control_5", "control_12")]
    assert all(re.fullmatch(PATIENT_ID_PATTERN, i) for i in ids)
    assert len(set(ids)) == 4 and pseudonym("condition_3") == ids[0]
