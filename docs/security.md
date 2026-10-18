# Security and privacy on LinuxONE: what is implemented, what the platform adds

This page separates what the prototype **does today** (verified, with links) from what
an IBM Z deployment in a public health system **would add**. The datathon VM is a
demo environment in the US (LinuxONE Community Cloud), not the real deployment.

## Implemented and verified in the prototype

| Control | How | Evidence |
|---|---|---|
| Encryption in transit | TLS 1.2/1.3 at the gateway, the only published port (8443); internal services have no public ports | `infra/gateway/nginx.conf`, `docs/screenshots/docker_ps.txt` |
| Encryption at rest of every health field | Fernet (AES-128-CBC + HMAC-SHA256) on signal, episodes, answers, activity and profiles; only pseudonymous ids and timestamps in clear | `services/store/core.py`, `tests/store/test_core.py` (no health value in clear in the database files) |
| Hardware crypto | AES, SHA-2/3 and ECDH run on CPACF, the on-chip crypto instructions of IBM Z (used by OpenSSL, hence by TLS and Fernet) | `docs/screenshots/vm_check.txt` (`icainfo`) |
| Keys outside code and images | Fernet key generated on the VM into `infra/.env` (mode 600, gitignored), never in git or in an image | `scripts/deploy_vm.sh` |
| Access control (issue #14) | Login for patients and clinicians (scrypt-hashed passwords, HS256 session tokens, 12 h); a patient reaches only their own data, a clinician only assigned patients; devices need `X-Device-Key`; CORS limited to `ALLOWED_ORIGINS`; WebSocket checks token and origin | `services/common/auth.py`, `tests/ingest_api/test_vertical_slice.py` (401/403 matrix), `tests/e2e/run_e2e.py` |
| Pseudonymisation | Random `p_…` ids; no identity table; demo data with shifted dates | `services/common/schemas.py`, `tools/import_depresjon.py` |
| Tamper-evident audit | Append-only audit log (triggers reject UPDATE/DELETE) with a SHA-256 hash chain; every inference, answer, timeline view and module run is logged | `GET /api/v1/audit-entries/verification`, `tests/store/test_core.py` |
| No health data in logs | Services log ids, events and timings only | `docs/screenshots/logs_no_health_data.txt` |
| Least privilege in containers | Non-root users, read-only root filesystems, `no-new-privileges` | `infra/docker-compose.yml`, service `Dockerfile`s |
| Data minimisation | Only the module the clinician selects runs; the profile holds sex and age group only | `services/suspicion_module/core.py` |

## What IBM Z / LinuxONE adds in a real deployment (not used in the datathon VM)

- **IBM Secure Execution for Linux.** Runs the whole VM as a hardware-protected
  "trusted execution environment": memory is encrypted and isolated by the firmware,
  and not even the hypervisor or the infrastructure administrators can read it. The
  VM image is encrypted for one specific machine (`genprotimg`) and only that machine
  can boot it. For health data this means the hospital's cloud operator cannot see
  patient data. **Checked: the datathon guest is not a Secure Execution guest**
  (`/sys/firmware/uv` is absent, `docs/vm-check.md`), so this is documented, not
  demonstrated.
- **Crypto Express HSMs and protected keys.** On machines with Crypto Express cards,
  the Fernet/TLS keys can be held as secure keys that never appear in clear in memory
  (`pkey`/`paes`). The datathon VM has no cards (`lszcrypt`: none).
- **Pervasive encryption.** Data set and volume encryption with keys managed outside
  the Linux guest.
- **Inference next to the data.** The models run on the same machine as the encrypted
  store, so health data never leaves it for scoring; the Telum on-chip accelerator
  (NNPA) is available to the guest (`docs/vm-check.md`) and measured in
  `ml/reports/nnpa_comparison.md`.

## Next steps (not in the prototype)

- OIDC login for clinicians through the health system's identity provider (no local
  passwords), with per-patient authorisation from the care relationship (a clinician
  only sees their own patients) instead of a static assignment list.
- Refresh tokens and revocation; rate limiting of `/api/v1/sessions`.
- Audit entries for logins: the current `AuditEntry` contract requires a
  `patient_id`, so logins are logged (ids only) but not yet in the audit chain.

## Regulation (design alignment, not certification)

Decision-support software in mental health is **high-risk AI** under the AI Act;
health data is a **special category** under the GDPR; the design follows the
European Health Data Space principles (patient control, secondary use only with
safeguards). The prototype implements human oversight (the clinician decides, the
system never acts on its own and never calls emergency services), transparency
(confidence, evidence, model version and data quality on every result), traceability
(audit log) and bias examination (`ml/reports/metrics.md`, fairness by sex and age).
