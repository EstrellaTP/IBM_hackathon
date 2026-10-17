# HANDOFF · diario de traspasos

Entradas nuevas **arriba del todo**. Formato en `CLAUDE.md` §1.2.

---

### [APP] 23:53 17/10 · F0-COM-01 · Contratos de datos
- Hecho: `services/common/schemas.py` (Pydantic v2) con SignalBatch, Sample, EpisodeEvent, StageTimestamps, QuestionAnswer, ModuleRequest, ModuleResult, MetricEvidence, ReferenceRange y AuditEntry. Todas las fechas deben llevar zona horaria (UTC). `patient_id` = `p_` + hex, `episode_id` = `e_` + hex. `ModuleResult` admite como máximo 4 métricas, sin repetir. Añadido `AuditEntry` para el registro de auditoría.
- JSON Schema y ejemplos para el frontend en `services/common/contracts/` (regenerar con `python -m services.common.export_contracts`). 10 tests en `tests/test_schemas.py` (`python -m pytest -q`).
- Rama / PR: `app/F0-COM-01-schemas`.
- Para el otro carril: [CC] nada que hacer con esto todavía; cuando montes la VM, `pip install -r services/common/requirements.txt`. [APP] sigue con F0-ML-02 (loaders + sintéticos) y F0-BE-03 (docker compose).
- Bloqueos / dudas para el equipo: ninguno.
- Captura para el jurado: no aplica.

### [APP] 23:51 17/10 · F0-DOC-01 · Estructura del repo y coordinación
- Hecho: `CLAUDE.md` con toda la información del proyecto y el protocolo entre agentes; `docs/TASKS.md` con las tareas de las fases 0 a 5 repartidas por carril; `docs/HANDOFF.md`; `docs/DECISIONS.md`; README base; `.gitignore`; LICENSE (MIT, pendiente de confirmar); `ATTRIBUTIONS.md`.
- Rama / PR: commit inicial directo en `main` (el repo estaba vacío).
- Para el otro carril: **[CC] puede empezar ya F0-BE-01, F0-BE-02 y F0-ML-01** (verificar la VM, probar librerías en s390x, descargar datasets). [APP] sigue con F0-COM-01 (`schemas.py`) y F0-ML-02 (loaders + datos sintéticos).
- Bloqueos / dudas para el equipo: nombre definitivo del proyecto y licencia (F0-HUM-01); ¿alguien tiene wearable compatible? (F0-HUM-02).
- Captura para el jurado: ninguna aún.
