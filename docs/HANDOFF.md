# HANDOFF · diario de traspasos

Entradas nuevas **arriba del todo**. Formato en `CLAUDE.md` §1.2.

---

### [CC] 01:12 18/10 · F0-CC-LOOP · Hook Stop del carril CC
- Hecho: `.claude/hooks/check_done.py` + `.claude/settings.json` (hook `Stop`, comando `python "$CLAUDE_PROJECT_DIR/.claude/hooks/check_done.py"`). Bloquea la parada mientras haya issues `para-cc` abiertos, filas de `TASKS.md` con carril que contenga `CC` en ⬜/🟡 (⛔ no cuenta) o casillas `- [ ] [CC]` en `QUALITY.md`; el `reason` lista todo y remite a CLAUDE.md §0. Válvulas: `.claude/ALLOW_STOP` o >60 bloqueos seguidos sin commit nuevo (`.claude/.stop_count`, se reinicia al cambiar `HEAD`). Ambos ficheros en `.gitignore`. `TASKS.md` se lee por columnas (la descripción de F0-CC-LOOP contiene "⬜/🟡" y un `sed` ingenuo se equivoca).
- Pruebas a mano con Estrella delante: (a) repo real → `decision=block` con 19 tareas y 11 casillas; (b) con `ALLOW_STOP` → stdout vacío; (c) clon con todo cerrado y 0 issues reales → stdout vacío. 9 tests en `tests/hooks/test_check_done.py`.
- Además: `scripts/smoke_test.sh` ahora elige `python3` o `python` y usa `-m ruff`/`-m pytest` (en Git Bash de Windows `ruff` no está en el PATH). `.gitattributes` fuerza LF: con `core.autocrlf=true` los `.sh` llegarían con CRLF y romperían bash en la VM.
- Rama: `cc/f0-cc-loop-stop-hook`, integrada en `main` por fast-forward.
- Para el otro carril: [APP] si añadís ficheros desde Windows, el `.gitattributes` ya normaliza. Para soltar al agente CC: `touch .claude/ALLOW_STOP`.
- Issues: ninguno.
- Captura para el jurado: no aplica.

### [APP] 01:09 18/10 · F1-ML-01 · Detector de episodios v1
- Hecho: `services/detector/core.py` con `PatientDetector` (una instancia por paciente) y `FixedRuleDetector` (regla `HR > 100` para comparar). Cada `step_seconds` resume los últimos `window_seconds` en pulso medio, actividad media (ENMO = max(0, |acc| − 1 g), van Hees 2013) y EDA media; calcula z-scores frente a una línea base personal (media y varianza con ponderación exponencial, West 1979) que **solo se actualiza con ventanas tranquilas**, para que un episodio no contamine la línea base. Episodio = `hr_z ≥ 3` **y** `activity_z ≤ 1` (regla de movimiento); severidad `extreme` con `hr_z ≥ 6`; antirrebote de 600 s; calibración de 30 ventanas (5 min); ventanas con menos de 10 lecturas de pulso se descartan. Python puro (sin NumPy), igual en x86 y en s390x.
- Configuración: `services/detector/settings.py` lee `DETECTOR_<CAMPO>` del entorno (p. ej. `DETECTOR_HR_Z_THRESHOLD=2.5`). Quien haga F0-BE-03, por favor, añada estas variables con sus valores por defecto a `infra/env.example`.
- Tests: 14 en `tests/detector/test_core.py` (calma sin episodios, subida sin movimiento, escaleras ignoradas, la regla fija salta con ejercicio y no ve 70→95 bpm, antirrebote, severidad extrema, línea base no contaminada, hueco de señal, sin acelerómetro, config por entorno). Gate completo en verde (24 tests).
- Unidades que el detector espera: acelerómetro en **g** y EDA en µS. **Para F0-ML-02 / F1-BE-04:** el acelerómetro de muñeca de WESAD viene en unidades de 1/64 g; hay que convertirlo a g en el loader.
- Rama: `app/f1-ml-01-episode-detector`, integrada en `main` por fast-forward.
- Para el otro carril: [CC] puede hacer F1-ML-02 (ajustar umbrales con WESAD real) cuando haya datos. [APP] seguirá con F0-FE-01 (frontend) o lo que quede libre.
- Issues: ninguno.
- Captura para el jurado: más adelante, la comparación escaleras frente a cálculo mental (detector personal frente a regla fija).

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
