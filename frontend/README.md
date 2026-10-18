# Frontend

Two static pages with no build step, served by the HTTPS gateway on the LinuxONE VM
(port 8443, see issue #1). They only use the API below and the contracts in
`services/common/schemas.py`.

| Page | URL | Who | Phase |
|---|---|---|---|
| Patient | `/patient/?patient_id=p_<hex>` | Patient's phone | 1: in-the-moment question and safety protocol |
| Clinician | `/clinician/?patient_id=p_<hex>` | Clinician's browser | 1: episodes timeline. 2: evidence charts (F2-FE-01) |

## Run without a backend

Add `?mock=1` to any page. The pages then generate contract-compliant fake data,
so they can be developed and reviewed before the services exist:

```bash
python3 -m http.server 8765 --directory frontend
# http://localhost:8765/patient/index.html?mock=1
# http://localhost:8765/clinician/index.html?mock=1
```

The patient page shows a notice that the data is replayed WESAD; hide it with `?replay=0`
when a real band is connected.

## API the pages use

The pages follow [`docs/api.md`](../docs/api.md), the contract the gateway routes:

| Method | Path | Used by |
|---|---|---|
| `WS` | `/api/v1/patients/{patient_id}/questions` (messages `{"type": "question", "episode": EpisodeEvent}`; `ping` ignored) | Patient |
| `POST` | `/api/v1/answers` with a `QuestionAnswer` body | Patient |
| `GET` | `/api/v1/clinician/patients/{patient_id}/timeline` → `{"patient_id", "items": [...]}` | Clinician |

The clinician page refreshes the timeline every 5 seconds.

## Design rules

- No narrative text about the patient: only signals, timings and the patient's own
  answers (CLAUDE.md section 5.5). `scripts/smoke_test.sh` rejects diagnostic wording.
- The safety buttons never call or message anyone in the prototype; they record the
  patient's choice and say so on screen (CLAUDE.md section 5.4).
- WCAG 2.1 AA: semantic HTML, labelled controls, 48 px touch targets, visible focus,
  light and dark themes, colour never the only signal.
