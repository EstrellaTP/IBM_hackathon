# QUALITY · el listón de "excelente"

Esta lista define cuándo el producto está terminado. **Mientras quede una casilla de tu carril sin marcar, hay trabajo.** El hook `Stop` de Claude Code (tarea F0-CC-LOOP) la lee y no deja parar a `[CC]` mientras queden casillas `[CC]` abiertas.

Reglas:
- Solo se marca `[x]` cuando se ha **comprobado** con la verificación indicada, no cuando "debería funcionar". Junto a la casilla, enlaza la prueba (commit, captura, fichero de métricas).
- Cada casilla está ligada a un criterio de la rúbrica (R1–R4 en CLAUDE.md §2.1; AI = AI Innovation Awards).
- Si una casilla es imposible (por ejemplo, la VM no tiene `nnpa`), se marca `[~]` con el motivo y un enlace a `DECISIONS.md`.

## A. Funciona (sin esto no hay demo)
- [ ] [CC] **Corte vertical en la VM**: simulador → ingesta → detector → pregunta en el móvil → respuesta → panel, todo en LinuxONE. Verificación: `scripts/smoke_test.sh --e2e` en verde contra la VM + captura. (R3, R4)
- [ ] [APP] **Tests en verde**: `scripts/smoke_test.sh` sin fallos en `main`. (R3)
- [x] [CC] **Despliegue con un comando**: `docker compose up -d` desde un clon limpio levanta los 5 servicios en la VM. Verificación: `docker ps` + captura. (R3) → `scripts/deploy_vm.sh` desde un directorio vacío de la VM, 2 min 11 s, 6/6 *healthy*: [`docs/screenshots/deploy_one_command.txt`](screenshots/deploy_one_command.txt), [`docs/screenshots/docker_ps.txt`](screenshots/docker_ps.txt)
- [x] [CC] **Big-endian comprobado**: la misma entrada da la misma predicción en el portátil y en la VM (diferencia < 1e-6). Verificación: `ml/reports/endianness_check.md`. (R3) → diferencia **0,0** (bit a bit) en 50 filas, modelo desplegado y LightGBM en texto: [`ml/reports/endianness_check.md`](../ml/reports/endianness_check.md)

## B. Rigor de datos y modelos (es un datathon)
- [ ] [CC] **Módulo de depresión validado por persona**: MCC, F1, sensibilidad, especificidad y AUC con `GroupKFold` (NHANES) y LOSO (DEPRESJON) en `ml/reports/metrics.md`. (R3, AI)
- [ ] [CC] **Comparación de modelos**: logística frente a RF frente a LightGBM, en una tabla. (R3)
- [ ] [CC] **Calibración**: diagrama de fiabilidad en `ml/reports/`. (R3)
- [ ] [CC] **Equidad**: sensibilidad y especificidad por sexo y grupo de edad + gráfica. (R1, AI)
- [ ] [CC] **Detector frente a regla fija**: falsas alarmas por hora y recall por evento en WESAD y enfermeras, z-score frente a Isolation Forest frente a `HR > 100`. (R2, AI)
- [ ] [APP] **Sin leakage por construcción**: test que falla si un mismo `patient_id` aparece en train y test. (R3)
- [ ] [APP] **Features documentadas**: cada feature (IS, IV, RA, L5, M10, sueño…) con fórmula y referencia en `ml/features/README.md`. (R3)

## C. LinuxONE de verdad (criterio 3)
- [ ] [CC] **Benchmark de latencia**: p50/p99 en servidor frente a 1/10/100/1.000 pacientes en `ml/reports/benchmark.csv` + gráfica. (R3, AI)
- [ ] [CC] **`nnpa`**: comparación con y sin acelerador, o `[~]` si no existe. (R3)
- [ ] [CC] **Capturas** en `docs/screenshots/`: VM, `uname -m`, `lscpu`, `docker ps`, logs de inferencia. (R3)
- [ ] [APP] **Cifrado y auditoría**: campos sensibles cifrados en reposo, TLS, registro de auditoría append-only con test. (R3)

## D. Producto que se entiende (criterios 1 y 4)
- [ ] [APP] **Panel del médico**: resultado + confianza, máximo 4 gráficas con banda de referencia, evidencia marcada, calidad del registro, aviso "not compatible ≠ ruled out", línea de tiempo con respuestas. (R1, R4)
- [ ] [APP] **Vista del paciente** en móvil: pregunta, respuesta en < 10 s, protocolo "Are you OK?" con botones simulados, ver datos/pausar/retirar consentimiento. (R1, R4)
- [ ] [APP] **"Before and now"** con DEPRESJON. (R1)
- [ ] [APP] **Lenguaje**: ninguna aparición de "diagnosis", "has depression", "suffers", "wellbeing" en la UI. Verificación: `scripts/smoke_test.sh` incluye un grep. (R1)
- [ ] [HUM] **Prueba con alguien de fuera**: entiende el panel sin explicación en < 30 s. (R4)

## E. Entregables
- [ ] [APP] **README completo**: problema con cifras, solución, arquitectura con diagrama, por qué LinuxONE, métricas reales, limitaciones honestas, ética y regulación, cómo reproducir. (R1–R4)
- [ ] [APP] **`ATTRIBUTIONS.md`** con todas las librerías y datasets. (Requisito)
- [ ] [HUM] **Vídeo ≤ 3:00** con la VM en pantalla y la pregunta llegando al móvil. (R4)
- [ ] [HUM] **Envío** en Hack2Skill con el título `GigaFly_IBM Z Datathon 2026 Project`. (Requisito)
