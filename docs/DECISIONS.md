# DECISIONS · decisiones tomadas

Formato: `- [fecha y hora] Decisión — motivo — quién (APP/CC/HUM)`. Si cambia algo de `CLAUDE.md`, actualízalo en el mismo PR.

## Tomadas
- [17/10 23:51] Tema 1, *Real-Time AI for Critical Decisions* — es el enviado en el abstract — HUM
- [17/10 23:51] Primer y único módulo del prototipo: depresión. TDAH y psicosis solo si Simula da permiso escrito — alcance de 24 h y licencias — HUM
- [17/10 23:51] Sin texto narrativo sobre el paciente; la IA generativa queda fuera salvo que se apruebe para describir qué mide cada gráfica — compromiso del abstract — HUM
- [17/10 23:51] Código, UI y README en inglés; documentación interna en español — jurado internacional — APP (confirmar)
- [17/10 23:51] Stack: Python + FastAPI + Pydantic v2, scikit-learn/LightGBM/SHAP, HTML+JS ligero, docker compose — simple y desplegable en s390x — APP
- [18/10 01:20] Docker en la VM: `docker.io` 29.1.3 + `docker-compose-v2` 2.40.3 de los repos de Ubuntu (no venía preinstalado, contra lo que decía CLAUDE.md §6) — paquetes oficiales s390x, sin repos de terceros — CC
- [18/10 01:25] Red: **solo se publica el punto de entrada HTTPS `8443`** en `docker compose`; los servicios internos no llevan `ports:` (o van a `127.0.0.1:`). Los puertos publicados por Docker se saltan el `INPUT` de iptables y quedarían abiertos a internet. Abiertos 443 y 8443 en `/etc/iptables/rules.v4` — ver `docs/vm-check.md` §5 — CC
- [18/10 01:25] El código llega a la VM con `scripts/sync_to_vm.sh` (tar por SSH de los ficheros de git): el repo es privado y la VM no debe tener credenciales de GitHub — CC
- [18/10 01:25] El NNPA del z17 es usable desde el invitado (zDNN 1.0.1): F3-BE-02 hará la comparación real con y sin acelerador, no `[~]` — CC
- [18/10 01:55] Stack ML completo en s390x **sin plan B**: numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, scikit-learn 1.9.1, LightGBM 4.7.0, SHAP 0.54.1, cryptography 50.0.2 compilan desde fuente (requiere `gfortran libopenblas-dev cmake libssl-dev`). Versiones fijadas en `ml/requirements.txt`. Imágenes Docker: multi-stage con `pip wheel` en el builder para no recompilar ~20 min en cada build — ver `docs/vm-check.md` §4 — CC
- [18/10 02:12] **Detector: memoria de movimiento (180 s) + exigir EDA (z ≥ 1) y umbrales ajustados con WESAD real** por leave-one-subject-out: `hr_z_threshold=2.0`, `activity_z_max=0.5`, `movement_lookback_seconds=180`, `eda_z_min=1.0`, `baseline_alpha=0.02` (la misma configuración gana en 12 de 15 folds). Resultado LOSO: F1 por evento 0,59 frente a 0,32 de `HR > 100`; 0,19 frente a 0,89 falsas alarmas/h. Motivo de la memoria de movimiento: la FC sigue alta al sentarse tras caminar; sin ella la escena de escaleras de la demo lanzaría la pregunta. Sin EDA (pulsera solo de FC) la condición de EDA no se aplica. Cambia el código de F1-ML-01 (APP): issue para revisión — `ml/reports/detector_wesad.md` — CC
- [18/10 02:12] Demo del corte vertical: reproducir un sujeto de WESAD que el detector detecta sin falsas alarmas (S10, S3, S4, S6, S7, S8, S11, S13 o S16; **no S2**), avisando en pantalla de que son datos reproducidos; las métricas globales se presentan tal cual (0,59 F1 LOSO) — CC

## Pendientes
- Nombre definitivo (MindHolter es provisional) — HUM
- Licencia del repo (MIT por defecto) — HUM
- PostgreSQL frente a SQLite cifrado — F0-BE-02 confirma que ambos son viables (`postgres:16` multi-arch, `cryptography` funciona); decide quien haga F1-BE-02 — APP/CC
