# HANDOFF · diario de traspasos

Entradas nuevas **arriba del todo**. Formato en `CLAUDE.md` §1.2.

---

### [CC] 02:14 18/10 · F1-ML-02 · Detector ajustado con WESAD real (LOSO)
- Hecho: `ml/models/detector_evaluation.py` reproduce los 15 sujetos de WESAD (muñeca) por una rejilla de 145 configuraciones + la regla fija, elige umbrales **leave-one-subject-out** (mejor F1 por evento en los otros 14) e informa de dónde caen las falsas alarmas. Comando en la VM: `cd ~/IBM_hackathon && ~/venv-holter/bin/python -m ml.models.detector_evaluation --workers 3` (~10 min con 3 vCPU). Salida: `ml/reports/detector_wesad.md` + `detector_wesad_runs.csv`.
- Hallazgo: con v1 (z ≥ 3, sin memoria) solo detectaba 4/15 estreses y la mayoría de falsas alarmas caían en `transient` (participantes que caminan entre salas: la FC sigue alta al sentarse). Una falsa alarma justo antes del TSST además activaba el antirrebote y tapaba el estrés real.
- Cambio en el detector (código de [APP], F1-ML-01): dos opciones nuevas en `DetectorConfig` con test: `movement_lookback_seconds` (el movimiento reciente sigue explicando la FC) y `eda_z_min` (la EDA debe acompañar si existe). Nuevos valores por defecto: `hr_z_threshold=2.0`, `activity_z_max=0.5`, `movement_lookback_seconds=180`, `eda_z_min=1.0`. Tests de [APP] adaptados: los escenarios de estrés suben también la EDA (`STRESS_EDA`); el comportamiento v1 queda como `V1` en los tests. Test nuevo que protege la escena de la demo (escaleras + sentarse → sin pregunta).
- Resultados (WESAD, 15 sujetos): **LOSO F1 0,59 · recall 0,53 · 0,19 FA/h**; regla fija F1 0,32 · recall 0,40 · 0,89 FA/h; v1 F1 0,21. Falsas alarmas en `transient`: 14 (regla fija) → 2. Retraso mediano desde el inicio de la etiqueta de estrés: ~8 min (la etiqueta incluye la preparación del TSST).
- Problemas: (1) el suelo de desviación de FC (`min_std_hr_bpm`) no cambia nada en WESAD; se quitó de la rejilla. (2) En la LOSO con un solo sujeto no hay datos de entrenamiento: hay que pasar ≥ 2 sujetos.
- Para la demo: **no usar S2** (no se detecta); usar p. ej. S10 o S3 (detectados sin falsas alarmas), con aviso de datos reproducidos.
- Rama: `cc/f1-ml-02-detector-thresholds`. Issue para revisión de [APP]: ver abajo.
- Captura para el jurado: tabla "Summary" y "Where the false alarms happen" de `ml/reports/detector_wesad.md`.

### [CC] 01:58 18/10 · F0-BE-01 + F0-BE-02 + F0-BE-05 + F0-ML-01 · VM lista, stack instalado, puertos y datos
- **VM (F0-BE-01)**: IBM **z17** (tipo 9175, Telum II), z/VM 7.3, 3 vCPU, 7,8 GiB, 50 GB (17 GB libres tras los datos), Ubuntu 24.04.5, Python 3.12.3. **`nnpa` en los flags y usable desde el invitado** (`tools/vm_check/nnpa_check.c` con zDNN 1.0.1: `nnpa_installed=yes`, `NNPA_MATMUL_OP=yes`). CPACF: AES-CBC/GCM, SHA-2/3, ECDSA, X25519 por hardware (`icainfo`). Sin tarjetas Crypto Express. **Sin Secure Execution.** **Docker no venía instalado**: `sudo apt-get install -y docker.io docker-compose-v2` (29.1.3 / 2.40.3); `python:3.12-slim` da `s390x big`. Transcripción: `ssh l1cc 'bash -s' < scripts/vm_check.sh > docs/screenshots/vm_check.txt`.
- **Stack (F0-BE-02)**: sin plan B. Todo compila desde fuente (no hay ruedas s390x en PyPI). Fallos y arreglo: scikit-learn → scipy pide Fortran (`apt install gfortran libopenblas-dev liblapack-dev pkg-config`); cryptography → `openssl-sys` no encuentra OpenSSL (`apt install libssl-dev`). Tiempos: numpy 140 s, pandas 176 s, lightgbm 607 s (incluye scipy), shap 128 s, cryptography 64 s. Venv en `~/venv-holter`. Prueba funcional `tools/vm_check/stack_check.py` → `docs/screenshots/vm_python_stack.txt`: 6/6 PASS (AUC 0,99, SHAP aditividad 4e-14, Fernet, FastAPI). Versiones en `ml/requirements.txt`. numpy quedó sin OpenBLAS (se compiló antes de instalarlo): en Docker, OpenBLAS antes que numpy.
- **Puertos (F0-BE-05)**: no hay firewall de nube; solo el iptables del invitado. Abiertos y persistentes **443 y 8443** (`/etc/iptables/rules.v4`). **Los puertos publicados por Docker se saltan INPUT** (probado: `-p 9443:80` accesible sin regla) → compose debe publicar solo 8443 (issue #1). URL de la demo: `https://148.100.99.58:8443`. Falta la prueba con datos móviles (F1-HUM-01).
- **Datos (F0-ML-01)**: `python3 -m ml.data.download_datasets depresjon wesad nhanes_h nhanes_h_minute nhanes_g` en la VM: DEPRESJON (md5 ok), WESAD (2,25 GB, ~20 MB/s), NHANES H (incl. PAXMIN_H 9,3 GB) y G (tablas horarias). Reanuda descargas y verifica tamaño/checksum. Enfermeras: Dryad bloquea descargas por script (401/403) → issue #2 `para-equipo` para descargarlo en navegador y `scp`. PAXMIN_G (7,6 GB) no descargado: con las tablas horarias de G basta por ahora.
- Otros: `scripts/sync_to_vm.sh` (el repo es privado; no hay credenciales en la VM). `PYTHON=~/venv-holter/bin/python bash scripts/smoke_test.sh` pasa en la VM.
- Issues: #1 (para-app, compose solo 8443), #2 (para-equipo, enfermeras), #3 (para-app, CC cogió F0-ML-02).
- Captura para el jurado: `docs/screenshots/vm_check.txt` (z17, nnpa, CPACF) y `docs/screenshots/vm_python_stack.txt`.

### [CC] 01:45 18/10 · F0-ML-02 + F0-ML-03 · Loaders con datos reales
- Hecho: `ml/data/loaders.py` (escritos contra los ficheros reales de la VM) + `ml/data/synthetic.py` (mismas columnas, para tests y para [APP]) + `ml/data/summarize_datasets.py` → `ml/reports/datasets_summary.md`.
  - **WESAD** `load_wesad_wrist("S2")`: flujo como lo mandaría la pulsera, ACC 32 Hz **en g** (÷64), HR 1 Hz (sale de `S*_E4_Data.zip/HR.csv`, el `.pkl` no trae HR), EDA 4 Hz en µS, índice UTC absoluto, columnas `label`/`condition`. Cada fila solo tiene los sensores que midieron en ese instante (NaN el resto) para no estropear el ENMO. `acc_hz=4` promedia si hace falta aligerar (benchmark). La ventana sincronizada del `.pkl` se localiza dentro de `ACC.csv` por coincidencia exacta (S2: muestra 49.447 = 1.545 s). El `.pkl` se abre con un unpickler que solo admite numpy.
  - **DEPRESJON**: `load_depresjon_scores()` (sexo F/M, grupo de edad, tipo afectivo, MADRS inicio/fin) y `load_depresjon_activity(person_id)` (counts por minuto, hora local noruega sin zona).
  - **NHANES H**: `load_nhanes_demographics/phq9/pax_header/pax_hourly`. PHQ-9 solo completos (7/9/NaN fuera), `depressive_symptoms = PHQ-9 >= 10`. Hora de reloj de cada fila horaria = `PAXFTIME + PAXSSNHP/80` s.
  - `stream_to_samples(df)` → `list[Sample]` del contrato (para el simulador y F1-ML-02).
- Comprobación: `PYTHON=~/venv-holter/bin/python bash scripts/smoke_test.sh` **en verde en la VM s390x** (59 tests) y en el portátil. Test de integración: el detector marca el estrés sintético y no el ejercicio sintético.
- Resultados reales (`ml/reports/datasets_summary.md`): WESAD 15 sujetos, 87–118 min cada uno, ~20 min baseline y 10–12 min de estrés por sujeto, carga 7–19 s/sujeto. DEPRESJON 23 pacientes (15 unipolar, 7 bipolar II, 1 bipolar I) y 32 controles. NHANES: 10.175 en DEMO, 5.372 PHQ-9 completos, 7.776 con acelerómetro, **4.780 adultos con PHQ-9 completo + acelerometría (9,5 % con PHQ-9 ≥ 10)**; mediana de 174 h llevadas.
- Sorpresas: (1) **pandas lee los ceros de XPORT como `5.397605e-79`** y las columnas de texto como `bytes`; `clean_xport_frame` lo corrige (sin esto el PHQ-9 suma basura). (2) En PAXHD, 1.137 personas tienen `PAXSTS=2` y campos vacíos. (3) DEPRESJON: `days` (13) < días realmente grabados (mediana 15 en pacientes, 19,6 en controles); 5 controles con huecos. (4) El PHQ-9 ≥ 10 va del 4 % (hombres 40–49) al 17 % (mujeres 50–59): importa para equidad y para estratificar. (5) El `.pkl` en s390x devuelve arrays `>f8` nativos con valores correctos: numpy respeta el orden de bytes guardado. (6) pandas instalado en la VM es 3.0.6.
- Rama: `cc/f0-ml-02-loaders`. Issues: #3 (aviso a [APP] de que CC cogió F0-ML-02).
- Para el otro carril: [APP] ya puede usar `ml.data.synthetic` para F1-BE-04 (simulador), F2-ML-01 (features: `depresjon_activity`, `nhanes_tables`) y F2-ML-03. Para el simulador: `stream_to_samples(load_wesad_wrist(s))` da las `Sample` listas.
- Captura para el jurado: `ml/reports/datasets_summary.md` (generado en s390x big-endian).

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
