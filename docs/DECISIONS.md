# DECISIONS · decisiones tomadas

Formato: `- [fecha y hora] Decisión — motivo — quién (APP/CC/HUM)`. Si cambia algo de `CLAUDE.md`, actualízalo en el mismo PR.

## Tomadas
- [17/10 23:51] Tema 1, *Real-Time AI for Critical Decisions* — es el enviado en el abstract — HUM
- [17/10 23:51] Primer y único módulo del prototipo: depresión. TDAH y psicosis solo si Simula da permiso escrito — alcance de 24 h y licencias — HUM
- [17/10 23:51] Sin texto narrativo sobre el paciente; la IA generativa queda fuera salvo que se apruebe para describir qué mide cada gráfica — compromiso del abstract — HUM
- [17/10 23:51] Código, UI y README en inglés; documentación interna en español — jurado internacional — APP (confirmar)
- [17/10 23:51] Stack: Python + FastAPI + Pydantic v2, scikit-learn/LightGBM/SHAP, HTML+JS ligero, docker compose — simple y desplegable en s390x — APP

## Pendientes
- Nombre definitivo (MindHolter es provisional) — HUM
- Licencia del repo (MIT por defecto) — HUM
- PostgreSQL frente a SQLite cifrado — depende de F0-BE-02 (qué funciona en la VM) — CC
- Umbrales del detector — depende de F1-ML-02 — CC
