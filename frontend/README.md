# Frontend

Two static pages with no build step, served by the HTTPS gateway on the LinuxONE VM
(port 8443, see issue #1). They only use the API below and the contracts in
`services/common/schemas.py`.

| Page | URL | Who | Phase |
|---|---|---|---|
| Patient | `/patient/?patient=p_<hex>` | Patient's phone | 1: in-the-moment question and safety protocol |
| Clinician | `/clinician/?patient=p_<hex>` | Clinician's browser | 1: episodes timeline. 2: evidence charts (F2-FE-01) |

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

## API the pages expect

All paths are relative to the page origin (`https://<vm>:8443`).

| Method | Path | Body / response | Used by |
|---|---|---|---|
| `WS` | `/ws/patients/{patient_id}` | Server pushes one `EpisodeEvent` JSON per message | Patient |
| `POST` | `/api/v1/answers` | Body: `QuestionAnswer`. Response: `201` | Patient |
| `GET` | `/api/v1/episodes?patient_id={id}` | `[{"episode": EpisodeEvent, "answer": QuestionAnswer \| null}]` | Clinician |

The clinician page refreshes the timeline every 5 seconds.

## Design rules

- No narrative text about the patient: only signals, timings and the patient's own
  answers (CLAUDE.md section 5.5). `scripts/smoke_test.sh` rejects diagnostic wording.
- The safety buttons never call or message anyone in the prototype; they record the
  patient's choice and say so on screen (CLAUDE.md section 5.4).
- WCAG 2.1 AA: semantic HTML, labelled controls, 48 px touch targets, visible focus,
  light and dark themes, colour never the only signal.
