# HTTP and WebSocket API (phase 1)

Everything is served under one origin, the TLS gateway: `https://<vm>:8443`
(demo: `https://148.100.99.58:8443`). Bodies are the Pydantic contracts of
`services/common/schemas.py` (JSON Schemas and examples in `services/common/contracts/`).
Times are ISO 8601 with a timezone (UTC). Field names are `snake_case`.

The patient is identified by a pseudonymous `patient_id` (`p_` + hex). In the demo the
phone opens `/patient/?patient_id=p_...` and the simulator sends that patient's signal.

## Patient side (`ingest-api`)

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/api/v1/signal-batches` | `SignalBatch` | `202` `{"patient_id", "accepted_samples", "episodes": [EpisodeEvent], "timings"}` |
| `WS` | `/api/v1/patients/{patient_id}/questions` | — | server pushes one message per episode (below) |
| `POST` | `/api/v1/answers` | `QuestionAnswer` | `201` `{"episode_id", "stored_at"}` · `404` unknown episode |

`ingest-api` stamps `timestamps.ingested_at` when the batch arrives, the detector
stamps `inferred_at`, and `pushed_at` is set just before the question is written to the
WebSocket. All three are stored, so the clinician panel and the benchmark can show the
server latency separately from the network.

`timings` (for the latency benchmark): `ingested_at`, `detected_at` (detector answered),
`responded_at` (UTC) and `detector_inference_ms` (pure detection compute in the
detector, without HTTP or JSON).

WebSocket message (server → phone), one per detected episode:

```json
{"type": "question", "episode": { "...": "EpisodeEvent, timestamps.pushed_at set" }}
```

`episode.severity == "extreme"` means the phone must show the safety protocol
("Are you OK?") instead of the normal question. The phone answers with
`POST /api/v1/answers` (not over the socket), so an answer is stored even if the socket
dropped. The server also sends `{"type": "ping"}` every 25 s to keep proxies from
closing an idle connection; the phone can ignore it.

## Clinician side (`evidence-api`)

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/v1/clinician/patients` | `[{"patient_id", "episodes", "answered", "last_episode_at"}]` |
| `GET` | `/api/v1/clinician/patients/{patient_id}/timeline` | `{"patient_id", "items": [{"episode": EpisodeEvent, "answer": QuestionAnswer \| null}]}`, newest first |

## Suspicion module (`suspicion-module`, phase 2)

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/api/v1/module-runs` | `ModuleRequest` | `ModuleResult` |

`ModuleResult.metrics` always has four entries: `sleep`, `circadian_rhythm`,
`daytime_activity` (daily values in `patient_series`, NHANES band in `reference` for the
patient's sex and age group, `is_evidence` on at most two, `shap` = summed log-odds
contribution) and `heart_rate` with `available: false` (no HR in actigraphy/NHANES).
`confidence` is the calibrated probability of the stated outcome; the decision threshold
is the training prevalence (0.42), so a borderline "compatible" can have a confidence
below 0.5. Errors: `404` no recording for the patient, `422` fewer than 4 valid days,
`503` model not trained on this machine.

## Internal only (compose network, not routed by the gateway)

- `detector`: `POST /api/v1/detections` (`SignalBatch` → `[EpisodeEvent]`).
- `store`: `POST /api/v1/signal-batches`, `POST /api/v1/episodes`, `POST /api/v1/answers`,
  `POST /api/v1/audit-entries`, `GET /api/v1/episodes?patient_id=`,
  `GET /api/v1/audit-entries?patient_id=`, `PUT|GET /api/v1/patients/{id}/profile`,
  `POST|GET /api/v1/patients/{id}/activity-hours`. Also on `127.0.0.1:8001` of the VM
  for host tools (`tools/import_depresjon.py`).

Every service also answers `GET /health` and serves OpenAPI at `/docs` (internal).
