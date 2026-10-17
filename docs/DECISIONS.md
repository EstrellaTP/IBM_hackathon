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

## Pendientes
- Nombre definitivo (MindHolter es provisional) — HUM
- Licencia del repo (MIT por defecto) — HUM
- PostgreSQL frente a SQLite cifrado — depende de F0-BE-02 (qué funciona en la VM) — CC
- Umbrales del detector — depende de F1-ML-02 — CC
