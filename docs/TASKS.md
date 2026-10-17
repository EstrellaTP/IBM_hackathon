# TASKS · tablero compartido

Carriles: `[CC]` Claude Code en el portátil (con acceso a la VM y a internet) · `[APP]` Claude en la app (nube, sin VM ni webs de datos) · `[HUM]` personas del equipo.
Estados: ⬜ pendiente · 🟡 en curso · ⛔ bloqueada · 👀 en revisión · ✅ hecha

**Regla:** antes de empezar una tarea, cámbiala a 🟡 con tu carril y haz commit de este fichero. Una tarea 🟡 de otro carril no se toca.

---

## Fase 0 · Cimientos

| ID | Tarea | Carril | Estado | Depende de |
|---|---|---|---|---|
| F0-DOC-01 | `CLAUDE.md`, `TASKS.md`, `HANDOFF.md`, `DECISIONS.md`, README base, `.gitignore`, LICENSE, `ATTRIBUTIONS.md` | APP | ✅ | — |
| F0-COM-01 | `services/common/schemas.py` con los contratos de CLAUDE.md §9 + tests | APP | ✅ | — |
| F0-CC-LOOP | **Instalar, con aprobación de Estrella, un hook `Stop` de Claude Code** en `.claude/settings.json` + `.claude/hooks/check_done.py` que bloquee la parada (`{"decision": "block", "reason": …}`) mientras haya: issues abiertos `para-cc`, tareas de carril CC en ⬜/🟡 en este fichero, o casillas `- [ ] [CC]` en `docs/QUALITY.md`. El `reason` debe listar lo pendiente y remitir a CLAUDE.md §0. Válvulas de escape (sin límites de hora): existe `.claude/ALLOW_STOP` (gitignored), o se han hecho más de 60 bloqueos seguidos sin ningún commit nuevo entre medias (señal de que está atascado; contador en `.claude/.stop_count`, gitignored, que se reinicia con cada commit). Probarlo a mano antes de dejarlo activo | CC | ✅ | — |
| F0-BE-05 | **Comprobar qué puertos de entrada tiene abiertos la VM** (además del 22): levantar un servidor de prueba en 8443/443/8080 y probar desde el portátil y desde un móvil con datos móviles. Si no hay ninguno abierto, plan B documentado en `docs/vm-check.md`: túnel `ssh -L` desde el portátil y servir la página del móvil desde el portátil en la red local (la inferencia sigue en LinuxONE). Sin esto no hay demo con el móvil | CC | ✅ | F0-BE-01 |
| F0-BE-01 | Verificar VM: SSH, `uname -m`, `lscpu` (¿`nnpa`?), `python3 --version`, `docker version`, `docker compose version`. Guardar salida en `docs/vm-check.md` y capturas en `docs/screenshots/` | CC | ✅ | — |
| F0-BE-02 | Probar instalación en la VM (s390x) de `numpy pandas scikit-learn lightgbm shap fastapi uvicorn cryptography`. Anotar qué falla en `docs/vm-check.md` y en `DECISIONS.md` si hay que aplicar plan B | CC | ✅ | F0-BE-01 |
| F0-BE-03 | `infra/docker-compose.yml` + Dockerfiles con los 5 servicios "hola mundo" (FastAPI `/health`) e `infra/env.example` | CC (cogida de APP) | 🟡 CC | F0-COM-01 |
| F0-BE-04 | Levantar F0-BE-03 en la VM, `docker ps`, captura | CC | ⬜ | F0-BE-02, F0-BE-03 |
| F0-ML-01 | Scripts de descarga en `ml/data/download_*.py` (NHANES PAXMIN/DPQ/DEMO ciclos G y H, DEPRESJON, enfermeras, WESAD). Datos a `ml/data/raw/` (no se suben). **Descargar directamente en la VM** (los datos de salud viven en LinuxONE) tras comprobar espacio con `df -h`: `PAXMIN` minuto a minuto ocupa varios GB por ciclo y WESAD ~2 GB; si no cabe, procesar `PAXMIN` por trozos y quedarse solo con las columnas necesarias, empezando por el ciclo H | CC | ✅ | — |
| F0-ML-02 | Loaders reproducibles en `ml/data/loaders.py` con orden de bytes explícito + generador de datos sintéticos con el mismo formato (para tests y para `[APP]`) | CC (cogida de APP) | ✅ | — |
| F0-ML-03 | Ejecutar loaders con datos reales; anotar en `HANDOFF.md` formas, columnas reales y sorpresas | CC | ✅ | F0-ML-01, F0-ML-02 |
| F0-FE-01 | Esqueleto `frontend/patient` y `frontend/clinician` (HTML + JS) con datos falsos que cumplen los contratos | APP | ⬜ | F0-COM-01 |
| F0-HUM-01 | Decidir nombre definitivo (MindHolter es provisional) y licencia (MIT por defecto) → `DECISIONS.md` | HUM | ⬜ | — |
| F0-HUM-02 | Confirmar si alguien tiene wearable compatible (Polar H10, Garmin/Polar con emisión de FC) | HUM | ⬜ | — |

**Hecho cuando:** `docker compose up` levanta 5 contenedores en la VM; los cuatro datasets cargan; las dos páginas se ven con datos falsos; capturas de `lscpu` y `docker ps`.

---

## Fase 1 · Corte vertical en tiempo real (mínimo demostrable)

| ID | Tarea | Carril | Estado | Depende de |
|---|---|---|---|---|
| F1-BE-01 | `ingest-api`: recibe y valida `SignalBatch`, estampa `ingested_at`, reenvía al detector | APP | ⬜ | F0-COM-01, F0-BE-03 |
| F1-BE-02 | `store`: tablas de señal, episodios, respuestas y auditoría (append-only); cifrado de campos sensibles con Fernet; clave en `.env` | APP | ⬜ | F0-COM-01 |
| F1-BE-03 | WebSocket de preguntas (episodio → `/patient`) y endpoint de respuestas (`QuestionAnswer` → store) | APP | ⬜ | F1-BE-01, F1-BE-02 |
| F1-ML-01 | Detector v1: ventana deslizante, z-score móvil frente a línea base personal, regla de movimiento, antirrebote, severidad `extreme`; regla fija `HR > 100` como comparación. Tests con datos sintéticos | APP | ✅ | F0-COM-01, F0-ML-02 |
| F1-ML-02 | Ajustar umbrales del detector con WESAD real (tramo base frente a estrés) y anotar valores en `DECISIONS.md` | CC | 🟡 CC | F1-ML-01, F0-ML-03 |
| F1-BE-04 | `tools/simulator`: un paciente de WESAD (o sintético) a velocidad real enviando `SignalBatch` | APP | ⬜ | F0-COM-01, F0-ML-02 |
| F1-FE-01 | `/patient`: recibe pregunta por WebSocket, envía respuesta (actividad + ánimo 1–5); aviso "replayed WESAD data" | APP | ⬜ | F0-FE-01, F1-BE-03 |
| F1-FE-02 | `/clinician`: línea de tiempo de episodios con la respuesta de cada uno y timestamps por etapa | APP | ⬜ | F0-FE-01, F1-BE-03 |
| F1-BE-05 | TLS en la VM (certificado autofirmado vale) y despliegue de la Fase 1 en LinuxONE; prueba con el móvil real | CC | ⬜ | F1-BE-01…03, F1-FE-01 |
| F1-DOC-01 | `docs/architecture.md` con diagrama definitivo | APP | ⬜ | — |
| F1-HUM-01 | Probar el flujo en un móvil real y grabar un clip de prueba | HUM | ⬜ | F1-BE-05 |

**Hecho cuando:** simulador → ingesta → detector → pregunta en el móvil → respuesta guardada → visible en el panel, todo en LinuxONE, con timestamps por etapa.

---

## Fase 2 · Módulo de la sospecha y panel de evidencias

| ID | Tarea | Carril | Estado | Depende de |
|---|---|---|---|---|
| F2-ML-01 | `ml/features`: IS, IV, RA, L5, M10, sueño (inicio, duración, fragmentación), % sin movimiento, actividad diurna; normalización por persona; tests con sintéticos | APP | ⬜ | F0-ML-02 |
| F2-ML-02 | Rangos de referencia p10/p50/p90 por sexo y grupo de edad en NHANES → `ml/reports/reference_ranges.json` | CC | ⬜ | F2-ML-01, F0-ML-03 |
| F2-ML-03 | `ml/models/train.py`: logística, RF, LightGBM; `GroupKFold` por persona; calibración; métricas MCC/F1/sens/espec/AUC; diagrama de fiabilidad. Código y tests | APP | ⬜ | F2-ML-01 |
| F2-ML-04 | Entrenar con NHANES real, probar en DEPRESJON (LOSO), guardar modelo portable y `ml/reports/metrics.md` | CC | ⬜ | F2-ML-02, F2-ML-03 |
| F2-ML-05 | SHAP por paciente → `is_evidence` (top 3–4); plan B si SHAP no instala | APP | ⬜ | F2-ML-03 |
| F2-BE-01 | `suspicion-module` (recibe `ModuleRequest`, devuelve `ModuleResult`; modelo dummy hasta F2-ML-04) y `evidence-api`; auditoría por inferencia | APP | ⬜ | F0-COM-01 |
| F2-FE-01 | Panel de evidencias: selector de sospecha, resultado + confianza, 4 gráficas con banda de referencia y evidencia marcada, calidad del registro, aviso "not compatible ≠ ruled out" | APP | ⬜ | F0-FE-01 |
| F2-BE-02 | Desplegar Fase 2 en la VM con el modelo real; comparar una predicción portátil frente a VM (big-endian) | CC | ⬜ | F2-ML-04, F2-BE-01 |
| F2-DOC-01 | Guion del vídeo (≤ 3 min) con problema, cifra, demo y LinuxONE | APP | ⬜ | — |

---

## Fase 3 · Escala, equidad, seguimiento y seguridad

| ID | Tarea | Carril | Estado | Depende de |
|---|---|---|---|---|
| F3-BE-01 | Simulador multi-paciente (1/10/100/1.000) + `tools/benchmark` que calcula p50/p99 por etapa y dibuja la gráfica | APP | ⬜ | F1-BE-04 |
| F3-BE-02 | Ejecutar el benchmark en la VM; con y sin `nnpa` si existe; `ml/reports/benchmark.csv` + gráfica + capturas | CC | ⬜ | F3-BE-01, F1-BE-05 |
| F3-ML-01 | Equidad: sensibilidad y especificidad por sexo y edad (código) | APP | ⬜ | F2-ML-03 |
| F3-ML-02 | Ejecutar equidad con datos reales + gráfica | CC | ⬜ | F3-ML-01, F2-ML-04 |
| F3-ML-03 | Detector v2 con Isolation Forest y comparación con z-score y regla fija (falsas alarmas/hora) en WESAD y enfermeras | APP (código) + CC (ejecución) | ⬜ | F1-ML-01 |
| F3-FE-01 | Vista "before and now" (DEPRESJON inicio frente a final) | APP | ⬜ | F2-FE-01 |
| F3-FE-02 | Protocolo de seguridad en `/patient` ("Are you OK?", botones simulados) y episodio destacado en `/clinician` | APP | ⬜ | F1-FE-01 |
| F3-FE-03 | Controles del paciente: ver sus datos, pausar registro, retirar consentimiento | APP | ⬜ | F1-FE-01, F1-BE-02 |

---

## Fase 4 · Pulido y entregables

| ID | Tarea | Carril | Estado |
|---|---|---|---|
| F4-BE-01 | Despliegue desde cero con un comando en la VM y logs sin datos sensibles | CC | ⬜ |
| F4-ML-01 | Script final que regenera todas las métricas y figuras | APP + CC | ⬜ |
| F4-FE-01 | Revisión de lenguaje (CLAUDE.md §5.5) y legibilidad de gráficas con alguien de fuera | HUM | ⬜ |
| F4-DOC-01 | README final (problema, solución, arquitectura, LinuxONE, métricas, limitaciones, ética, cómo reproducir) y `ATTRIBUTIONS.md` completo | APP | ⬜ |
| F4-HUM-01 | Grabar y montar el vídeo ≤ 3 min con la VM en pantalla | HUM | ⬜ |
| F4-HUM-02 | Envío en Hack2Skill con el título `GigaFly_IBM Z Datathon 2026 Project` | HUM | ⬜ |

## Fase 5 · Opcional

| ID | Tarea | Carril | Estado |
|---|---|---|---|
| F5-01 | Wearable real con `bleak` (escaleras frente a cálculo mental) | CC + HUM | ⬜ |
| F5-02 | Descripción de qué mide cada gráfica con GenAI (solo si se aprueba) | APP | ⬜ |
| F5-03 | Secure Execution / cifrado por hardware documentado | CC | ⬜ |
