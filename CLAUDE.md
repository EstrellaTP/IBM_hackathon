# CLAUDE.md · GigaFly · A Holter for Mental Health (IBM Z Datathon 2026)

> Este fichero lo leen automáticamente todos los agentes de Claude que trabajan en este repo. Es la fuente de verdad del proyecto: la idea, los requisitos, las normas del datathon, el plan por fases y el protocolo para que varios agentes y personas trabajen a la vez sin pisarse. **Léelo entero antes de tocar nada y vuelve a él cuando dudes.**

---

## 0. Antes de empezar cada sesión (obligatorio)

1. `git fetch origin && git status`. Trae `main` actualizado.
2. **Lee los issues abiertos dirigidos a tu carril y atiéndelos antes que cualquier tarea nueva** (sección 1.5). `[CC]`: `gh issue list --label para-cc --state open`. `[APP]`: `gh api "repos/EstrellaTP/IBM_hackathon/issues?labels=para-app&state=open"`. Si hay alguno con `bloqueante`, va primero.
3. Lee `docs/TASKS.md` (qué hay pendiente y quién lo lleva) y las últimas entradas de `docs/HANDOFF.md` (qué ha hecho el otro carril).
4. Coge **una** tarea que sea de tu carril (sección 1) y que no tenga dependencias pendientes. Márcala como `🟡 en curso` con tu etiqueta en `TASKS.md` y haz commit de ese cambio **antes** de empezar, para que el otro agente no la coja.
5. Trabaja en una rama propia (sección 1.3). Al terminar: tests o comprobación, commit, push, integración en `main`, tarea a `✅ hecha` y una entrada en `HANDOFF.md`.
6. Repite desde el paso 1 antes de cada tarea nueva: así ves los issues que el otro carril haya abierto mientras trabajabas.

### 0.1 Bucle hasta "excelente"

**No hay plazos ni márgenes de horas.** Lo que importa es avanzar de forma eficiente: priorizar lo que más sube la calidad (orden: issues `bloqueante` → corte vertical → casillas de `QUALITY.md` por impacto en la rúbrica), no ir rápido ni rellenar tiempo.

"Terminado" no es "he acabado mi tarea", sino **`docs/QUALITY.md` con todas las casillas de tu carril marcadas y verificadas**. Por eso:

- Al acabar una tarea no te paras: vuelves al paso 1. Si `TASKS.md` no tiene nada de tu carril, toma la primera casilla sin marcar de tu carril en `QUALITY.md` y conviértela en tarea.
- Antes de integrar en `main`: `scripts/smoke_test.sh` en verde. Si rompe algo que funcionaba, no se integra. Cuando el corte vertical funcione por primera vez en la VM, crea la etiqueta `git tag demo-ok-1` (y `demo-ok-2`, … en cada mejora probada): siempre tiene que existir una versión que se pueda enseñar.
- Una casilla se marca solo con la verificación indicada y un enlace a la prueba.
- Cada vez que cierres una casilla, haz una autoevaluación rápida contra la rúbrica (§2.1): ¿qué haría subir un punto en R1–R4? Si se te ocurre algo concreto y barato, ábrelo como issue para el carril que corresponda.
- Si estás bloqueado por algo que solo puede hacer una persona: issue `para-equipo` y sigue con otra cosa. **No esperes de brazos cruzados.**
- `[CC]` tiene un hook `Stop` (tarea F0-CC-LOOP) que no le deja parar mientras quede trabajo de su carril; `[APP]` hace revisiones periódicas programadas.

---

## 1. Protocolo de trabajo en equipo (agentes + personas)

### 1.1 Quién es quién

| Etiqueta | Quién | Dónde corre | Qué puede hacer |
|---|---|---|---|
| `[CC]` | **Claude Code** en el portátil del equipo | Local, con acceso SSH a la VM de LinuxONE | Todo lo que toca la VM: SSH, Docker, despliegue, benchmark real. Descarga de datasets, entrenamiento, métricas reales, capturas de la VM |
| `[APP]` | **Claude en la app** (chat del proyecto) | Nube, sin SSH a la VM y sin acceso a webs de datos (CDC, Simula, Dryad…) | Código que no necesita la VM: contratos, frontend, código de features/modelos con tests sobre datos sintéticos, simulador, README, diagramas, `ATTRIBUTIONS.md`, revisión de PRs |
| `[HUM]` | Personas del equipo GigaFly | Donde sea | Decisiones, grabar el vídeo, probar el móvil, revisar el lenguaje, cualquier tarea |

Si una tarea necesita algo que tu carril no tiene (por ejemplo, `[APP]` necesita datos reales), **no la bloquees en silencio**: déjala en `⛔ bloqueada`, abre un issue para el carril que puede desbloquearla (sección 1.5) y coge otra.

### 1.2 Ficheros de coordinación

- `docs/TASKS.md`: tablero. Cada tarea tiene ID (`F1-BE-02`), carril, estado y dependencias. Estados: `⬜ pendiente`, `🟡 en curso`, `⛔ bloqueada`, `👀 en revisión`, `✅ hecha`.
- `docs/HANDOFF.md`: diario de traspasos. Entradas **arriba del todo** (la más nueva primero), con este formato:
  ```
  ### [CC|APP|HUM] <hora Madrid> · <ID de tarea> · <título corto>
  - Hecho: …
  - Rama / PR: …
  - Para el otro carril: … (qué puede coger ya; las peticiones van en issues)
  - Issues abiertos o cerrados: #…
  - Captura para el jurado: … (si aplica)
  ```
- `docs/DECISIONS.md`: decisiones de arquitectura o de relato tomadas (y quién las tomó). Si una decisión cambia algo de este `CLAUDE.md`, actualiza también este fichero en el mismo PR.

### 1.2.1 Qué va en cada sitio
| Sitio | Para qué | Quién lo cambia |
|---|---|---|
| `CLAUDE.md` | Reglas estables: la idea, los requisitos, el protocolo. **No** es un canal de avisos | Solo cuando cambia una regla o una decisión de `DECISIONS.md`, en un commit propio y avisando con un issue `para-cc`/`para-app` |
| `docs/TASKS.md` | El plan: qué tareas hay, de quién son y en qué estado están | Cualquiera, al coger o cerrar una tarea |
| **Issues de GitHub** | Todo lo que necesita una acción de otro carril: errores encontrados al revisar, peticiones, preguntas, bloqueos | Cualquiera los abre; los cierra quien los resuelve |
| `docs/HANDOFF.md` | Diario breve de lo terminado, para quien vuelve tras un rato fuera | Cada carril al terminar una tarea |

### 1.3 Ramas, commits y PRs

- Ramas: `cc/<ID>-<slug>` para Claude Code, `app/<ID>-<slug>` para la app, `hum/<nombre>-<slug>` para personas.
- **Nunca** `push --force` a `main`. Integración por PR cuando se pueda. Si tu carril no puede abrir PRs (le pasa a `[APP]`: la API de GitHub le da 404), integra con *fast-forward*: `git fetch origin main && git rebase origin/main`, tests en verde, `git checkout main && git merge --ff-only <rama> && git push origin main`, y deja la rama en remoto para que el otro carril pueda revisarla. Si el otro agente no está para revisar, puedes hacer merge de tu propio PR cuando los tests pasen y no toque ficheros que el otro tenga `🟡 en curso`.
- Commits pequeños, en inglés, imperativo: `Add SignalBatch schema`. PRs con: qué cambia, cómo probarlo, captura si aplica.
- Antes de crear la rama: `git fetch origin main && git rebase origin/main`.
- Conflictos en `TASKS.md` o `HANDOFF.md`: conserva **las dos** versiones (son tablón y diario, no código).

### 1.4 Propiedad de ficheros (para no pisarse)

| Ruta | Dueño principal | Notas |
|---|---|---|
| `services/common/schemas.py` | Compartido | Cambios **solo** por PR y avisando en `HANDOFF.md`: todo depende de esto |
| `services/*`, `infra/*` | `[CC]` (despliegue) / `[APP]` (código) | `[APP]` escribe el código, `[CC]` lo levanta y prueba en la VM |
| `ml/features`, `ml/models` | `[APP]` escribe y testea con sintéticos; `[CC]` ejecuta con datos reales | |
| `ml/data` | `[CC]` | Los datos **no** se suben (ver `.gitignore`); solo loaders y scripts de descarga |
| `ml/reports`, `docs/screenshots` | `[CC]` | Resultados y capturas reales de la VM |
| `frontend/*` | `[APP]` | |
| `README.md`, `ATTRIBUTIONS.md`, `docs/*` | `[APP]` + `[HUM]` | |

### 1.5 Issues: el canal entre carriles

- **Etiquetas:** `para-cc` (Claude Code), `para-app` (Claude en la app), `para-equipo` (decisión o acción de una persona) y `bloqueante` (frena el corte vertical o una fase). Un issue lleva siempre una etiqueta de destino.
- **Título:** `[ID de tarea] qué pasa`, por ejemplo `[F1-ML-01] El detector lanza pregunta al subir escaleras`.
- **Cuerpo:** qué has visto, dónde (fichero y línea, commit o captura), qué esperabas, y cómo propones arreglarlo. Si es una petición, qué necesitas y para qué tarea.
- **Al resolverlo:** el commit lleva `Fixes #<n>` en el mensaje y se deja un comentario breve con qué se hizo. Si no estás de acuerdo con el issue, contéstalo en un comentario en vez de cerrarlo.
- **Revisión periódica de `[APP]`:** cuando `[APP]` revisa el trabajo de `[CC]` y encuentra algo, abre un issue `para-cc`; no edita el código de `[CC]` salvo que sea trivial (una errata) o que el issue lo pida.
- Comandos: `[CC]` usa `gh` en el portátil (requiere `gh auth login` una vez). `[APP]` usa la API REST con `gh api` (la de GraphQL no está disponible en su entorno).

### 1.6 Reglas que no se negocian

1. **Primero el corte vertical de punta a punta** (Fase 1), luego profundidad. Una arquitectura simple que funciona vale más que una compleja sin terminar.
2. **Los contratos de datos (sección 9) antes que los servicios.** Mientras falte una pieza, usa datos falsos que cumplan el contrato.
3. **Todo el código se escribe durante el evento.** Nada de proyectos previos del equipo ni código comercial como núcleo. Librerías open-source, APIs públicas y herramientas de IBM sí, cada una apuntada en `ATTRIBUTIONS.md` con enlace.
4. **Nunca subas datos de salud, datasets, claves ni `.env`.** Ni siquiera muestras "pequeñas" de datasets con licencia restringida.
5. **Autonomía de `[CC]`:** tiene permiso del equipo para hacer lo que haga falta dentro de este repo y de la VM (instalar, configurar, crear y borrar ficheros del proyecto, reiniciar contenedores, reorganizar código) **sin pedir confirmación a una persona**. Si una decisión afecta a la arquitectura o al relato del pitch, la toma con su mejor criterio, la apunta en `DECISIONS.md` y abre un issue `para-app` para que `[APP]` la revise. Los únicos límites son las demás reglas de esta lista y los compromisos del abstract (§3 y §5.5).
6. **Dudas e investigación → `[APP]`.** Cualquier duda (técnica, de datos, de un paquete que no instala en s390x, de cómo interpretar un requisito) o cualquier cosa que haya que investigar se pregunta con un issue `para-app`, con el contexto necesario: qué intentabas, qué ha pasado (error completo), qué has probado. `[APP]` lo resuelve o lo investiga en su siguiente revisión y contesta en el issue. **Mientras tanto, `[CC]` no espera:** sigue con otra tarea.
7. **Commits frecuentes y documentación detallada.** Un commit por cada paso que funcione, no uno gordo al final. Cuerpo del commit con qué cambia y por qué. Al terminar cada tarea, entrada en `HANDOFF.md` con detalle suficiente para que otro agente continúe sin preguntar: qué se hizo, comandos exactos usados, resultados (números reales), problemas encontrados y cómo se resolvieron. Lo que se descubra de la VM (versiones, paquetes que fallan y su solución) va además a `docs/vm-check.md`.
8. Al terminar cada tarea, indica qué captura o log guardar como prueba para el jurado (sección 13).
9. Idioma: **todo el código y todo lo que lo rodea va en inglés** (sección 1.7): identificadores, comentarios, docstrings, logs, mensajes de error, tests, commits, ramas, UI, README y documentación técnica. `CLAUDE.md`, `TASKS.md`, `HANDOFF.md` y `DECISIONS.md` (coordinación interna del equipo) siguen en español.
10. **Los estándares de código de la sección 1.7 son obligatorios.** Código que no los cumple no se integra.

### 1.7 Estándares de código (obligatorio)

Todo debe poder leerlo y mantenerlo cualquier ingeniero del mundo sin conocer al equipo: convenciones estándar, estructura clara, en inglés y comentado. `scripts/smoke_test.sh` pasa `ruff` (formato + lint) y los tests: si falla, no se integra.

**Idioma.** Inglés en: nombres de ficheros, carpetas, variables, funciones, clases, comentarios, docstrings, mensajes de log y de error, textos de la UI, tests, mensajes de commit, nombres de rama, títulos y cuerpo de issues y PRs, README y docs técnicas. Nada de spanglish (`calcular_sleep`, `datosPaciente`).

**Python** (versión 3.10+):
- Estilo [PEP 8](https://peps.python.org/pep-0008/), aplicado con `ruff format` y `ruff check` según `pyproject.toml` (líneas de 100).
- Nombres: `snake_case` para módulos, paquetes, funciones y variables; `PascalCase` para clases; `UPPER_SNAKE_CASE` para constantes; `_leading_underscore` para lo privado. Nombres descriptivos y completos (`resting_heart_rate`, no `rhr2`), salvo convenciones del dominio documentadas (`IS`, `IV`, `L5`, `M10`).
- **Type hints** en todas las funciones públicas ([PEP 484](https://peps.python.org/pep-0484/)) y `from __future__ import annotations`.
- **Docstrings** ([PEP 257](https://peps.python.org/pep-0257/), estilo Google) en cada módulo, clase y función pública: qué hace, `Args:`, `Returns:`, `Raises:`. El docstring del módulo explica su papel en la arquitectura.
- **Comentarios que explican el porqué**, no el qué: decisiones, umbrales, referencias científicas (cada fórmula de features con su cita), limitaciones conocidas y trucos de s390x/big-endian.
- Sin `print`: módulo `logging` con logger por módulo (`logger = logging.getLogger(__name__)`). **Nunca** datos de salud en los logs: solo `patient_id` seudónimo, ids de episodio y tiempos.
- Configuración por variables de entorno ([12-factor](https://12factor.net/config)), con valores por defecto seguros y documentados en `infra/env.example`. Sin rutas, IPs ni claves en el código.
- Sin números mágicos: constantes con nombre y comentario de dónde salen.
- Funciones cortas y con una responsabilidad; nada de lógica en notebooks (los notebooks solo exploran e importan de los módulos).
- Errores explícitos: excepciones concretas, nunca `except:` desnudo.
- Dependencias fijadas en `requirements.txt` de cada servicio, y añadidas a `ATTRIBUTIONS.md`.

**Estructura de un servicio** (igual en todos):
```
services/<service_name>/
    __init__.py
    main.py          # FastAPI app factory and startup only
    api.py           # HTTP / WebSocket routes, thin
    core.py          # domain logic, no web framework imports
    settings.py      # environment-based configuration
    requirements.txt
    Dockerfile
tests/<service_name>/test_*.py   # pytest, mirrors the source tree
```

**APIs:** REST con FastAPI (OpenAPI automático en `/docs`), rutas versionadas `/api/v1/...` en `kebab-case` y plural (`/api/v1/episodes`), campos JSON en `snake_case`, fechas ISO 8601 en UTC, códigos HTTP correctos (201 al crear, 422 al validar, 404…), `GET /health` en cada servicio.

**Frontend (HTML/CSS/JS):** HTML semántico y accesible (WCAG 2.1 AA: contraste, `label` en formularios, `alt` en imágenes, navegable con teclado); JavaScript moderno con módulos ES, `const`/`let`, `camelCase` para variables y funciones, `PascalCase` para clases, JSDoc en funciones públicas; clases CSS en `kebab-case`; ficheros en `kebab-case` (`evidence-chart.js`). Sin frameworks pesados ni paso de build.

**Tests:** `pytest`, ficheros `test_*.py`, un comportamiento por test con nombre que lo describe (`test_detector_ignores_heart_rate_explained_by_movement`). Datos sintéticos, nunca datos reales en los tests.

**Git:** commits en inglés con [Conventional Commits](https://www.conventionalcommits.org/) (`feat: add rolling z-score detector`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), con `Fixes #n` si cierran un issue. Ramas `cc/<task-id>-<short-slug>` o `app/<task-id>-<short-slug>` en minúsculas y `kebab-case`.

**Docker:** un `Dockerfile` por servicio, imagen base oficial multi-arch con `linux/s390x`, usuario no root, sin secretos en la imagen; servicios de `docker compose` en `kebab-case`.

---

## 2. El reto (contexto del datathon)

- **Evento:** IBM Z Datathon 2026 (Hack2Skill, organiza Shooting Stars Foundation con IBM). Formato de 24 h. Equipo **GigaFly** (UC3M), track virtual, región **EMEA**.
- **Tema elegido:** Tema 1, *Real-Time AI for Critical Decisions* ("Detect. Decide. Respond."): IA y datos en tiempo real para decidir en el momento en que ocurren los eventos. Pieza IBM que encaja: inferencia dentro de la transacción, junto al dato.
- **Paraguas:** "AI for Good". La solución tiene que **usar de verdad IBM Z / LinuxONE** y justificar por qué esa plataforma.
- **Infraestructura:** VM gratuita en la **LinuxONE Community Cloud (L1CC)** de Marist College (EE. UU.). Cada miembro con su portátil.
- **Soporte:** Discord del evento, canal `#ibm-z-sme-helpdesk`, con expertos de IBM durante el datathon.

### 2.1 Rúbrica oficial (40 puntos)

| # | Criterio | Pts | Qué hace falta para 9–10 |
|---|---|---|---|
| 1 | Valor para la comunidad y alineación con el tema | 10 | Impacto sobre una necesidad crítica, *Tech for Good*, tema integrado de forma natural, **quién se beneficia** claro |
| 2 | Novedad y originalidad | 10 | Idea muy innovadora, **componentes end-to-end**, código hecho desde cero en el evento |
| 3 | Diseño técnico y uso de LinuxONE + AI/ML open-source | 10 | Arquitectura que **saque partido de L1CC** (seguridad, cómputo, contenedores, escalabilidad) con buen uso de AI/ML sobre LinuxONE. **Capturas como prueba** |
| 4 | Ejecución y pitch | 10 | Vídeo profesional, **demo convincente**, comunicación clara, **sin pasarse del tiempo** |

**AI Innovation Excellence Awards** (20 puntos aparte): originalidad del uso de la IA (10) e impacto y excelencia técnica end-to-end y escalable (10).

Los 2 labs oficiales de AI/ML (*multi-model* y *Predictive + Generative AI*) **no son entregables ni trabajo pendiente**: no dediques tiempo a ellos. Solo sirven de referencia de lo que valora IBM, por eso el sistema es multi-modelo.

### 2.2 Entregables obligatorios

- **Vídeo de 3 minutos como máximo**: problema, datos que lo respaldan, solución y **cómo usa IBM Z** (stack, **la instancia de LinuxONE en pantalla y el modelo funcionando**).
- **Repositorio público** (este), con enlaces a todas las librerías y recursos open-source usados.
- **Título del proyecto:** `GigaFly_IBM Z Datathon 2026 Project`.
- Recomendado: diagrama de arquitectura y prototipo.

### 2.3 Normas del evento

- No se admiten *continuation hacks*: el código se escribe durante el evento.
- No reutilizar proyectos propios anteriores ni código comercial como núcleo.
- Nada con carga política ni que ataque a ningún colectivo.

### 2.4 Qué han hecho los ganadores de ediciones anteriores (para orientar decisiones)

1. **AI for Good con beneficiario claro**, entendible en 10 segundos.
2. **Cifras** en el problema y en el resultado (coste, personas afectadas, métricas del modelo, impacto estimado).
3. **Pipelines multi-modelo o híbridos**, casi nunca un solo modelo.
4. **Salida accionable** (triaje, semáforo, alerta), no solo un número.
5. **Producto que se puede enseñar**: dashboard, API o app con demo.
6. **Rigor de datos**: varios datasets, feature engineering, splits sin *leakage*, comparación de modelos. Es un *datathon* y se nota.
7. **Entregables completos**: GitHub público, vídeo y deck.

Aviso: un ganador de 2025 reconoció que no usó funcionalidades de IBM Z; en 2026 eso penaliza porque la rúbrica exige LinuxONE de forma explícita.

---

## 3. Abstract oficial enviado (fuente de verdad)

Todo lo que se construya tiene que ser coherente con este texto:

> **A Holter for Mental Health.** Real-time anomaly detection on a wearable, momentary questions to the patient, and objective evidence for the clinician, running on IBM LinuxONE.
>
> One in seven people worldwide lives with a mental disorder, yet psychiatric diagnosis still relies almost entirely on clinical interviews and subjective scales. The result is long delays: in bipolar disorder, 5 to 8 years pass on average before adequate treatment, and a Madrid cohort reports 9.3 years. Meanwhile, patients receive treatments that do not fit their condition.
>
> We propose a Holter for mental health that supports the patient from the first suspicion through to the end of treatment. The patient wears an activity and heart-rate band. A model compares the live signal with the patient's own baseline and, when it detects an anomaly that movement does not explain, immediately sends a short question to their phone: what were you doing, and how do you feel? Asking in the moment avoids the recall bias of retrospective questionnaires, and each answer is linked to its episode as evidence for the clinician.
>
> The system works in two phases. First, the clinician selects the suspicion to test (for example, depression) and only that module is activated. At the end of the recording period, the module classifies the data and shows an evidence dashboard: one chart per metric (sleep, circadian rhythm, daytime activity and heart rate) against age- and sex-specific reference ranges, highlighting the metrics that drove the result. Second, a before-and-now view tracks how the metrics evolve during therapy. The system does not diagnose or prescribe, generates no narrative about the patient and never calls emergency services on its own: the professional always decides.
>
> Technically, we combine three models: an episode detector against each patient's personal baseline (rolling z-score or Isolation Forest); a calibrated classifier (logistic regression, Random Forest and LightGBM) trained on NHANES, which covers thousands of adults with accelerometry and PHQ-9 scores, and tested on diagnosed patients from DEPRESJON; and an explainability layer based on SHAP. We validate per person, never per day, to avoid inflated results, and we report performance by sex and age group.
>
> Everything that touches health data runs encrypted on IBM LinuxONE, in Docker containers. IBM Z lets a public health system keep data on its own infrastructure, and keeps latency stable with thousands of concurrent patients, which is what allows the question to arrive while the episode is still happening. The design follows the European framework (GDPR, AI Act and European Health Data Space): privacy by design, human oversight, transparency and patient control over their own data.
>
> *Keywords: mental health · wearables · ecological momentary assessment · anomaly detection · explainable AI · IBM LinuxONE · data sovereignty*

Nombre provisional del producto: **MindHolter** (pendiente de confirmar por el equipo; ver `docs/DECISIONS.md`).

---

## 4. El problema (cifras para el README y el pitch)

| Ámbito | Cifra | Fuente |
|---|---|---|
| Mundo | 1.200 millones de personas con un trastorno mental en 2023, casi 1 de cada 7 | [OMS](https://www.who.int/news-room/fact-sheets/detail/mental-disorders) |
| Mundo | 322 millones con depresión, 36 millones con trastorno bipolar, ~27 millones con esquizofrenia | OMS |
| Mundo | Solo un tercio de las personas con depresión y el 40 % de las personas con psicosis reciben atención formal | OMS |
| UE | 84 millones de personas (17,3 %) con un problema de salud mental en 2016 | [OCDE y Comisión Europea](https://search.oecd.org/els/health-systems/OECD-Factsheet-Mental-Health-Health-at-a-Glance-Europe-2018.pdf) |
| UE | Más de 600.000 millones de euros de coste en 2015, más del 4 % del PIB | OCDE y CE |
| Bipolar | 5 a 8 años entre el inicio y el tratamiento adecuado (metaanálisis de 27 estudios, 9.415 pacientes) | [European Psychiatry](https://www.cambridge.org/core/journals/european-psychiatry/article/how-long-is-the-interval-between-the-onset-and-the-initial-management-of-bipolar-disorder-a-metaanalysis/EAC6FEA46F868E4547456A3535AA18F3) |
| Madrid | 9,3 años de retraso diagnóstico en una cohorte ambulatoria | [Rev. Psiquiatría y Salud Mental](https://www.elsevier.es/en-revista-revista-psiquiatria-salud-mental-486-articulo-diagnostic-delay-differences-by-sex-S2173505010700145) |

- El diagnóstico se basa casi solo en la entrevista y escalas: lento y subjetivo. Un antidepresivo mal indicado en un bipolar puede empeorar el cuadro.
- La actigrafía ya se considera un método objetivo para observar la depresión, pero apenas se usa en clínica (autores de DEPRESJON). Una pulsera cuesta mucho menos que horas de especialista: escala a sistemas con pocos recursos.
- **Por qué desde Europa:** los datos de salud mental son de los más sensibles; Europa tiene el marco más exigente (RGPD, AI Act, Espacio Europeo de Datos de Salud). Una solución diseñada para cumplirlo puede llevarse a cualquier país.
- **Quién se beneficia:** pacientes con sospecha de depresión, bipolaridad, TDAH o psicosis; psiquiatras y médicos de familia (también donde no hay especialistas cerca); sistemas públicos de salud.

---

## 5. La solución, en detalle

**En una frase:** un Holter de salud mental que acompaña al paciente desde la primera sospecha hasta el fin del tratamiento. El paciente lleva una pulsera; cuando un modelo detecta algo fuera de lo normal para esa persona, le pregunta en ese mismo momento qué está pasando, y su respuesta se suma a las evidencias que ve el médico.

**Usuarios:** psiquiatras, psicólogos clínicos y médicos de familia (usan el panel), y sus pacientes (llevan la pulsera y responden).

### 5.1 La pregunta en el momento (pieza central)
- Un modelo compara la señal con la **línea base del propio paciente**.
- Si detecta una anomalía que **el movimiento no explica**, envía al móvil una pregunta corta: *what were you doing?* (opciones + texto libre) y *how do you feel, 1 to 5?*
- La respuesta queda **enlazada al episodio** y aparece en el panel del médico.
- Base científica: la evaluación ecológica momentánea evita el sesgo de memoria de los cuestionarios retrospectivos ([Shiffman, Stone y Hufford](https://doi.org/10.1146/annurev.clinpsy.3.022806.091415)).

### 5.2 Fase clínica 1: contrastar una sospecha
1. **Sospecha:** el médico elige qué contrastar (en el prototipo, **depresión**). Solo se activa ese módulo.
2. **Registro:** el paciente lleva la pulsera; los datos llegan cifrados a LinuxONE.
3. **Preguntas:** cada episodio detectado genera su pregunta en el momento.
4. **Clasificación:** al cerrar el periodo, el módulo clasifica el registro completo.
5. **Panel de evidencias:** resultado ("pattern compatible / not compatible" + confianza calibrada) y **una gráfica por métrica** (sueño, ritmo circadiano, actividad diurna, pulso) frente al rango de referencia de su edad y sexo. Se marcan como evidencia las que más han pesado (SHAP). Línea de tiempo con los episodios y la respuesta del paciente.
6. **Decisión:** decide el médico. El sistema no diagnostica ni prescribe.

Ejemplo ilustrativo de lo que ve el médico: arriba, "Pattern compatible with depression · confidence 78 %". Debajo, cuatro gráficas; dos marcadas como evidencia: *daytime activity* (por debajo del rango en 10 de 12 días) y *sleep* (despertares nocturnos en 9 de 12 noches). Ningún texto redactado sobre el paciente.

### 5.3 Fase clínica 2: acompañar el tratamiento
- El paciente puede seguir con la pulsera durante la terapia.
- Vista **"before and now"**: mismas gráficas, periodo inicial frente al actual.
- Las preguntas siguen aportando contexto entre sesiones.
- El sistema muestra la evolución de las métricas; **no** dice si la persona está mejor.

### 5.4 Protocolo de seguridad
- Valores extremos que el movimiento no explica → la pregunta pasa a ser **"Are you OK?"** con un botón para llamar al 112 y otro para avisar a un contacto de confianza elegido por el paciente.
- El episodio aparece destacado en el panel.
- **El sistema nunca llama solo.** En el prototipo los botones solo registran la acción y muestran una confirmación simulada: **ninguna llamada ni mensaje real**. (Las llamadas automáticas generan falsas alarmas: caso de la detección de accidentes de Apple en pistas de esquí, 2022–2023.)

### 5.5 Lo que el sistema NO hace (requisito, no sugerencia)
- No genera texto narrativo sobre el paciente: solo métricas, gráficas, confianza y respuestas del propio paciente.
- No diagnostica, no prescribe, no toma decisiones automáticas.
- No hace cribado de población general ni está pensado para empleadores o aseguradoras.
- Lenguaje en toda la UI: "signals compatible with", "symptoms", "how the metrics evolve". **Nunca** "has", "suffers from" ni "wellbeing/better".
- "Not compatible" **no significa "ruled out"**: el panel lo dice explícitamente, junto con la calidad del registro (horas sin datos, días válidos).

### 5.6 Diferenciación frente a lo que existe

| Quién | Qué hace | Qué le falta frente a nosotros |
|---|---|---|
| [m-Path](https://m-path.io/clinical/) | Plataforma para terapeutas; lanza cuestionarios cuando cambian datos del móvil o wearable | Disparadores = reglas fijas; sin ML ni apoyo al diagnóstico |
| [movisens SensorTrigger](https://www.movisens.com/en/products/sensor-trigger/) | Cuestionarios a partir de pulso, HRV o actividad | Pensado para investigación, no para consulta |
| [Monsenso](https://us.fitgap.com/products/045825/monsenso-mhealth) | Autoevaluaciones y datos pasivos del móvil | Cuestionarios programados, no disparados por anomalía |
| [mindLAMP](https://www.digitalpsych.org/mindlamp) | Open-source, encuestas, sensores del móvil y panel clínico | No indica disparo por datos |
| [Investigación con Fitbit](https://arxiv.org/pdf/2505.03039) | Detecta empeoramientos frente a la línea base, con SHAP | No pregunta en el momento; es un artículo |

Lo nuestro: (1) **cuándo preguntar lo decide un modelo personal** que descarta el ejercicio, no una regla fija; (2) **un modelo entrenado con datos clínicos marca qué métricas son evidencia**; (3) entramos **desde la sospecha**; (4) cada respuesta se ve **sobre su episodio** junto a las gráficas. En el pitch, m-Path se nombra como producto maduro y nuestro motor como una capa que podría funcionar sobre plataformas así. **La demo debe enseñar el modelo personal frente a una regla fija.**

---

## 6. Restricciones técnicas de la plataforma

- **LinuxONE es obligatorio y de verdad.** Ingesta, detección, almacenamiento, módulo de la sospecha y evidencias corren en la VM de L1CC. Fuera solo quedan la pulsera, el móvil y el navegador del médico. No basta con mencionarlo en el pitch.
- **LinuxONE no es una distro:** ejecuta Ubuntu, RHEL o SUSE sobre **s390x (big-endian)**. Algunos paquetes hay que compilarlos o buscar su versión s390x.
- **Estado real de la VM** (ver `docs/vm-check.md`, F0-BE-01/02): IBM z17, Ubuntu, Python 3.12, **NNPA usable** (zDNN), stack de ML completo compilado desde fuente, solo los puertos 22, 443 y 8443 abiertos. Ojo: los puertos que publica Docker se saltan iptables, así que en `docker compose` solo se publica `8443`.
- Comprobaciones al llegar a la VM: `uname -m` (debe decir `s390x`), `lscpu` (buscar el flag `nnpa`), `python3 --version`, `docker version`, y que instalen `numpy pandas scikit-learn lightgbm shap fastapi uvicorn`.
- **Big-endian:** al leer binarios (`.pkl` de WESAD, `.npy`, modelos) fija el orden de bytes y **compara una predicción en el portátil y en la VM** con la misma entrada. Formatos portables: CSV, Parquet, JSON, modelos LightGBM en texto, `joblib` generado en la misma arquitectura. (Lección del Team Oasis: PyTorch daba resultados raros por big-endian hasta usar versiones compatibles.)
- **Docker** no venía preinstalado en nuestra VM: está instalado desde los repos de Ubuntu (`docker.io` + `docker-compose-v2`, ver `docs/vm-check.md`). Todos los servicios en contenedores, orquestados con `docker compose`. Imágenes base con variante `linux/s390x` (p. ej. `python:3.11-slim`, `postgres:16` oficiales son multi-arch; verificar).
- Consejo oficial de IBM: **empezar simple** (app Python funcionando en la VM) e ir añadiendo datos, BD, API e IA.
- Punto fuerte de IBM Z: **inferencia junto al dato** (Telum II con acelerador de IA integrado). Se puede entrenar fuera y desplegar en Z para inferencia.
- **Multi-modelo:** al menos tres modelos (detector, clasificador, explicación).

---

## 7. Datos

| Dataset | Personas | Contenido | Papel | Licencia y acceso |
|---|---|---|---|---|
| **NHANES** (CDC, EE. UU.), ciclos 2011–2012 (`_G`) y 2013–2014 (`_H`) | ~7.776 con acelerómetro en 2013–2014, más 2011–2012 | Acelerómetro de muñeca minuto a minuto ([`PAXMIN_H`](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2013/DataFiles/PAXMIN_H.htm), unidades MIMS, sueño/vigilia, luz), PHQ-9 (`DPQ_G`/`DPQ_H`) y demografía (`DEMO_G`/`DEMO_H`) | Rangos de referencia por edad y sexo; entrenamiento del módulo de depresión | Público, sin registro |
| **DEPRESJON** ([Simula](https://datasets.simula.no/depresjon/), Noruega; también en [Zenodo](https://zenodo.org/record/1219550)) | 23 pacientes y 32 controles | Actividad minuto a minuto (*counts*), MADRS al inicio y al final, tipo de trastorno | Prueba con pacientes diagnosticados; prueba de concepto de "before and now" | Citar el artículo; investigación y educación |
| **Estrés de enfermeras** ([artículo](https://pmc.ncbi.nlm.nih.gov/articles/PMC9159985), [Dryad](https://datadryad.org/dataset/doi:10.5061/dryad.5hqbzkh6f)) | 15, ~1.250 h | Empatica E4: HR/BVP, EDA, temperatura, acelerómetro; episodios de estrés confirmados | Detector de episodios en vida real | Artículo CC BY 4.0; revisar términos de Dryad |
| **WESAD** ([Univ. de Siegen](https://ubi29.informatik.uni-siegen.de/usi/data_wesad.html)) | 15 sanas, laboratorio | Señal en bruto de muñeca y pecho; neutro, estrés y diversión etiquetados | Etiquetas limpias; flujo simulado para demo y benchmark | Uso científico no comercial, citando |
| HYPERAKTIV y PSYKOSE (Simula) | 103 en HYPERAKTIV | Actividad (y pulso en HYPERAKTIV) | Módulos opcionales TDAH y psicosis | **Solo con permiso escrito previo de Simula. No usar sin él** |

**Lo que aporta cada uno:** NHANES, la escala; DEPRESJON, el contraste clínico; enfermeras, la vida real; WESAD, la señal en bruto. El estudio de enfermeras valida el enfoque: los episodios se confirmaban en una encuesta al final del turno y los autores reconocen el sesgo de memoria; la pregunta en el momento resuelve justo eso.

**Matices obligatorios:**
- El PHQ-9 mide síntomas, no diagnostica. Etiqueta: `PHQ-9 ≥ 10` = "depressive symptoms". Excluir cuestionarios incompletos.
- NHANES no tiene pulso y usa otro dispositivo y otras unidades (MIMS frente a *counts*). Por eso las features son **relativas y normalizadas por persona**.
- Muestras clínicas pequeñas (habitual en wearables y salud mental): se compensa con muchas horas por persona y validación por persona. Las métricas modestas se presentan como rigor.
- Descartados: GLOBEM (credenciales y curso de ética), UK Biobank (semanas de espera). LifeSnaps requiere solicitud.
- **Los datos no se suben al repo.** Solo scripts de descarga y loaders en `ml/data/`. Datos crudos en `ml/data/raw/` (ignorado por git).

---

## 8. Arquitectura

```
Pulsera (actividad + pulso) ──► Móvil del paciente (página web, WebSocket)
                                   │  envía datos cada minuto / responde preguntas
                                   ▼
┌──────────────────── LinuxONE (L1CC) · todo cifrado · docker compose ────────────────────┐
│ 1. ingest-api       API de ingesta cifrada (TLS), recibe lotes de señal                  │
│ 2. detector         Detección en tiempo real: línea base personal → episodio → pregunta  │
│ 3. store            Almacén cifrado, datos seudonimizados (PostgreSQL o SQLite cifrado)  │
│ 4. suspicion-module Módulo de la sospecha: features, modelo calibrado, SHAP              │
│ 5. evidence-api     Evidencias por métrica frente al rango de referencia + panel web     │
│    + audit log: cada inferencia queda registrada                                         │
│    + tools/simulator y tools/benchmark (reproducen WESAD/enfermeras a velocidad real)    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                   ▲
Panel del médico (navegador): elige la sospecha, activa el módulo, ve gráficas y episodios
```

**Stack** (cámbialo solo con motivo, avisando en `DECISIONS.md`):
- Python 3.10+, FastAPI + Uvicorn, WebSockets nativos de FastAPI, Pydantic v2.
- `pandas`, `numpy`, `scikit-learn`, `lightgbm`, `shap`.
- Almacén: PostgreSQL (imagen s390x) con volumen cifrado, o SQLite con cifrado de campos sensibles a nivel de aplicación (`cryptography`/Fernet). Claves en `.env` (no versionado; plantilla en `infra/env.example`).
- Frontend: HTML + JS ligero servido desde la VM, sin build complejo; gráficas con Plotly.js, Chart.js o Vega-Lite (CDN o vendorizado). Vistas: `/patient` (móvil) y `/clinician` (panel).
- Seudonimización: solo `patient_id` aleatorios; la tabla con identidades reales no existe en el prototipo.

**Estructura del repo:**
```
/services/common/schemas.py   ← contratos compartidos
/services/ingest_api  /services/detector  /services/suspicion_module  /services/evidence_api   ← paquetes Python en snake_case
                                 (en docker compose los servicios se llaman ingest-api, detector, suspicion-module, evidence-api)
/frontend/patient     /frontend/clinician
/ml/data (loaders; raw/ ignorado)  /ml/features  /ml/models  /ml/notebooks  /ml/reports
/tools/simulator      /tools/benchmark
/infra/docker-compose.yml  /infra/env.example
/docs/architecture.md  /docs/screenshots/  /docs/TASKS.md  /docs/HANDOFF.md  /docs/DECISIONS.md
README.md  ATTRIBUTIONS.md  LICENSE  CLAUDE.md
```

---

## 9. Contratos de datos (definir primero)

Implementados como modelos Pydantic en `services/common/schemas.py`. Backend, ML y frontend trabajan contra estos contratos con datos falsos hasta que llegue la pieza real.

```jsonc
// SignalBatch: móvil/simulador → ingest-api
{ "patient_id": "p_7f3a", "device": "e4|wesad|polar|sim", "sent_at": "ISO8601",
  "samples": [ { "t": "ISO8601", "hr": 92.0, "acc_x": 0.1, "acc_y": 0.0, "acc_z": 0.98, "eda": 0.42 } ] }

// EpisodeEvent: detector → store + móvil (WebSocket)
{ "episode_id": "e_…", "patient_id": "p_7f3a", "start": "ISO8601", "detected_at": "ISO8601",
  "severity": "normal|extreme", "score": 3.4, "method": "zscore|iforest|fixed_rule",
  "features": { "hr_z": 3.4, "acc_mag_z": 0.2, "eda_z": 2.1 },
  "timestamps": { "sample_t": "…", "ingested_at": "…", "inferred_at": "…", "pushed_at": "…" } }

// QuestionAnswer: móvil → store
{ "episode_id": "e_…", "activity": "work|rest|social|commute|other", "activity_text": "…",
  "mood_1_5": 2, "safety_action": null | "call_112_simulated" | "notify_contact_simulated",
  "answered_at": "ISO8601" }

// ModuleRequest: panel → suspicion-module
{ "patient_id": "p_7f3a", "suspicion": "depression", "period": { "from": "…", "to": "…" } }

// ModuleResult: suspicion-module → evidence-api
{ "patient_id": "p_7f3a", "suspicion": "depression", "result": "compatible|not_compatible",
  "confidence": 0.78, "model_version": "…",
  "data_quality": { "valid_days": 12, "missing_hours": 6.5 },
  "metrics": [ { "name": "daytime_activity", "patient_series": [...],
                 "reference": { "p10": 0, "p50": 0, "p90": 0, "group": "F_30-39" },
                 "is_evidence": true, "shap": -0.21 } ],
  "episodes": [ "e_…" ] }
```

Cambiar un contrato = PR específico + aviso en `HANDOFF.md`.

---

## 10. Modelos y metodología

### 10.1 Detector de episodios (tiempo real)
- **Datos:** WESAD y enfermeras, señal en bruto.
- Ventana deslizante (p. ej. 60 s, paso 10 s; parametrizable) con pulso, EDA (si existe) y magnitud del acelerómetro.
- Línea base personal: media y desviación móviles de las últimas horas o de un periodo de calibración inicial.
- Método A: **z-score móvil**. Método B: **Isolation Forest** por paciente. Comparar.
- **Regla de movimiento:** un pulso alto solo cuenta si el acelerómetro no lo explica (umbral sobre la magnitud, o modelo HR ~ actividad y residuo).
- Severidad `extreme` para el protocolo de seguridad (umbral alto y conservador, configurable).
- Antirrebote: no repetir pregunta en N minutos tras un episodio.
- **Línea de comparación obligatoria:** regla fija (p. ej. `HR > 100`) para demostrar que el modelo personal da menos falsas alarmas con ejercicio.
- Métricas: precisión/recall por evento frente a etiquetas de estrés (WESAD) y eventos confirmados (enfermeras), falsas alarmas por hora.

### 10.2 Módulo de la sospecha: depresión
- **Entrenamiento:** NHANES (`PHQ-9 ≥ 10`). **Prueba externa:** DEPRESJON (pacientes frente a controles).
- **Features por día**, comparables entre dispositivos:
  - Ritmo circadiano no paramétrico: **IS** (estabilidad entre días), **IV** (variabilidad intradía), **RA** (amplitud relativa), **L5** (5 h menos activas) y **M10** (10 h más activas), con hora de inicio.
  - Sueño estimado: inicio, duración, fragmentación (despertares).
  - Proporción de minutos sin movimiento; actividad diurna media.
  - **Normalización por persona** (z-score o percentiles intra-persona) para trasladar de MIMS a *counts*.
  - Agregación por persona (media, desviación, tendencia) para clasificar el registro completo.
- **Modelos:** regresión logística (base), Random Forest y LightGBM. **Calibración** Platt o isotónica (`CalibratedClassifierCV`), con diagrama de fiabilidad.
- **Validación por persona, nunca por días:** `GroupKFold` por persona en NHANES y leave-one-subject-out en DEPRESJON. Referencia publicada en DEPRESJON con validación por persona: **F1 0,73 y MCC 0,44**. Varios trabajos posteriores publican >95 % de *accuracy* con los mismos datos; suelen mezclar días de una misma persona entre train y test. Lo contamos en el pitch.
- **Métricas:** MCC, F1, sensibilidad, especificidad y AUC por persona.
- **Equidad:** sensibilidad y especificidad por sexo y grupo de edad en NHANES (el AI Act pide examinar sesgos en sistemas de alto riesgo; pocos equipos enseñarán esta gráfica).
- **Rangos de referencia** del panel: p10/p50/p90 de cada métrica en NHANES por sexo y grupo de edad.

### 10.3 Explicabilidad
- **SHAP** (TreeExplainer para RF/LightGBM, LinearExplainer para logística) por paciente.
- Las 3–4 features con más peso marcan qué gráficas son "evidence".
- Máximo **cuatro** gráficas: sleep, circadian rhythm, daytime activity, heart rate (si no hay pulso: "no heart-rate data").

### 10.4 IA generativa
- **Fuera por defecto.** Como mucho, una descripción de *qué mide cada gráfica* (nunca sobre el paciente), solo si `[HUM]` lo aprueba en `DECISIONS.md`.

---

## 11. Seguridad, privacidad y regulación (en el código)

| Principio | Implementación mínima |
|---|---|
| Privacidad desde el diseño | Solo se activa el módulo de la sospecha; datos seudonimizados; TLS en tránsito y cifrado en reposo |
| Supervisión humana | Ninguna acción automática sobre el paciente; el médico decide qué módulo se ejecuta; el protocolo de seguridad lo dispara el paciente |
| Transparencia | Cada resultado muestra confianza, evidencias, versión del modelo y calidad del registro |
| Control del paciente | La vista del paciente permite ver sus datos, pausar el registro y retirar el consentimiento |
| Trazabilidad | Registro de auditoría append-only de cada inferencia: quién, qué módulo, versión, timestamp |
| No discriminación | Métricas por sexo y edad |
| Soberanía | Todo desplegable con `docker compose up` en infraestructura propia; ningún servicio externo con datos de salud |

Para el README: software de apoyo al diagnóstico = IA de **alto riesgo** según el AI Act; datos de salud = **categoría especial** del RGPD (consentimiento explícito y minimización); diseño alineado con el Espacio Europeo de Datos de Salud ([RGPD](https://eur-lex.europa.eu/eli/reg/2016/679/oj), [AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/oj), [EHDS](https://eur-lex.europa.eu/eli/reg/2025/327/oj)). El uso médico no choca con la prohibición de inferir emociones en el trabajo o la educación. Si la VM tiene Secure Execution o cifrado por hardware, documentarlo; si no, dejar claro que **la VM del datathon (en EE. UU.) es el entorno de demo, no el despliegue real**.

**Fuera de alcance:** cribado de la población general, uso por empleadores o aseguradoras, llamadas automáticas a emergencias, cualquier decisión automática sobre el paciente.

---

## 12. Por qué IBM Z (sin exagerar) y benchmark de latencia

IBM Z no es imprescindible con diez pacientes: la carga es pequeña y otras nubes ofrecen computación confidencial. Lo que aporta es hacerlo con todo un sistema público de salud:
1. **Soberanía de los datos:** ejecutable en la infraestructura del sistema sanitario, con cifrado por hardware y aislamiento incluso frente a sus administradores (Secure Execution).
2. **Latencia estable a escala:** la pregunta solo vale si llega mientras el episodio sigue ocurriendo. Importa el **p99** con miles de pacientes enviando señal a la vez, no la media.
3. **Inferencia junto al dato:** si la VM tiene `nnpa` ([zDNN](https://github.com/IBM/zDNN)), el modelo corre donde están los datos con aceleración.

**Benchmark (la prueba del argumento):**
- `tools/simulator` reproduce señal de WESAD y enfermeras **a velocidad real** para **1, 10, 100 y 1.000 pacientes simultáneos** (asyncio o procesos), enviando `SignalBatch` a `ingest-api`.
- Cada etapa estampa su timestamp (`sample_t`, `ingested_at`, `inferred_at`, `pushed_at`) para **separar la red del servidor**.
- Resultado: gráfica **p50 y p99 en el servidor** frente al número de pacientes (debe mantenerse plana), en `ml/reports/benchmark.csv` y `docs/`.

| Etapa | ¿Depende de IBM Z? |
|---|---|
| Ventana de detección | No: decisión de diseño entre rapidez y falsas alarmas |
| Red del móvil a la VM y vuelta | No; en el datathon incluye el salto a EE. UU. (~100 ms) |
| Inferencia en LinuxONE | Sí |
| Envío de la pregunta al móvil | No |

- Si hay `nnpa`, comparar inferencia con y sin acelerador.

**Frase para el pitch:** "Every minute the question takes, the patient remembers less of what was happening. Our system asks while the episode is still happening, even with thousands of patients connected, and without their data ever leaving the health system's infrastructure."

---

## 13. Demo y pruebas para el jurado

**Base (debe funcionar sí o sí): datos reproducidos**
1. El simulador en la VM reproduce a velocidad real un tramo tranquilo y otro de estrés de un participante de WESAD.
2. El móvil abre `/patient`, servida desde la VM, por WebSocket (sin app nativa).
3. Al detectar el episodio, aparece la pregunta; la respuesta vuelve a la VM y aparece en `/clinician` sobre el episodio.
4. Marcas de tiempo superpuestas ("episode detected 12:03:15 · question received 12:03:16") y aviso visible de que son datos reproducidos de WESAD.
5. Vídeo en pantalla dividida: señal en el panel, terminal de LinuxONE con logs de inferencia y móvil (scrcpy en Android o QuickTime con iPhone).

**Mejora opcional: wearable real**
- Pulso por Bluetooth estándar (Polar H10, Garmin/Polar en modo "broadcast HR") leído desde el portátil con [`bleak`](https://github.com/hbldh/bleak) y reenviado a la VM; acelerómetro del móvil. Apple Watch y Fitbit no valen.
- Escena (~30 s): subir escaleras → pulso alto explicado por el movimiento → **no** hay pregunta. Sentado, restar de 7 en 7 desde 1.000 → pulso alto sin movimiento → **sí** llega la pregunta. Comparar con la regla fija.

**Capturas obligatorias** en `docs/screenshots/`: VM de L1CC, `uname -m` y `lscpu`, `docker ps`, logs de inferencia, gráfica del benchmark, panel del médico, pregunta en el móvil, métricas de validación y gráfica de equidad.

---

## 14. Riesgos y planes B

| Riesgo | Plan |
|---|---|
| Abarcar demasiado | Prioridad absoluta: módulo de depresión + pregunta en el momento + panel. Lo demás es opcional. Un módulo completo puntúa más que tres a medias |
| LightGBM o SHAP no instalan en s390x | Compilar desde fuente si es rápido; si no, solo scikit-learn (logística + RF) y explicación por importancia por permutación o contribuciones lineales |
| Resultados raros por big-endian | Versiones compatibles, formatos portables, comparar predicción portátil frente a VM |
| Features no se trasladan de NHANES a DEPRESJON | Plan B: entrenar y validar solo con DEPRESJON (por persona) y usar NHANES solo para rangos de referencia |
| Sin permiso de Simula para HYPERAKTIV/PSYKOSE | No se usan; el núcleo no depende de ellos |
| Métricas modestas | Presentarlas como rigor: validación por persona frente a resultados inflados |
| La red a EE. UU. añade latencia | Medir y graficar la latencia en el servidor por separado |
| Sin `nnpa` | El argumento se apoya en soberanía y latencia estable a escala |
| Gráficas difíciles de entender | Máximo cuatro, con rango de referencia y evidencia marcada; probarlas con alguien de fuera |

---

## 15. Plan por fases y paralelización

Cuatro flujos que avanzan a la vez: **[ML]** Datos y ML · **[BE]** LinuxONE y backend · **[FE]** Frontend · **[DOC]** Pitch y documentación. Cada fase acaba en un **punto de integración** con criterio de "hecho". El desglose operativo, con IDs y carril (`[CC]`/`[APP]`/`[HUM]`), está en `docs/TASKS.md`.

### Fase 0 · Cimientos (todo en paralelo)
- [BE]+[ML] `schemas.py` con los contratos (primero de todo; ya hecho).
- [BE] Verificar VM (SSH, `uname -m`, `lscpu`, Docker, instalar librerías en s390x); `docker compose` con los 5 servicios "hola mundo".
- [ML] Descargar y cargar NHANES (PAXMIN, DPQ, DEMO), DEPRESJON, enfermeras y WESAD; loaders reproducibles con orden de bytes explícito.
- [FE] Esqueleto de `/patient` y `/clinician` con datos falsos que cumplan los contratos.
- [DOC] README base, LICENSE, `ATTRIBUTIONS.md`, plantilla del diagrama, guion del vídeo.

**Hecho:** `docker compose up` levanta 5 contenedores en la VM; los cuatro datasets cargan; las dos páginas se ven con datos falsos; capturas de `lscpu` y `docker ps`.

### Fase 1 · Corte vertical en tiempo real
- [BE] `ingest-api` (TLS, valida `SignalBatch`), `store` (señal, episodios, respuestas, auditoría; cifrado de campos), WebSocket de preguntas; simulador mínimo (un paciente de WESAD a velocidad real).
- [ML] Detector v1: z-score móvil + regla de movimiento + antirrebote, como servicio `detector`.
- [FE] `/patient` recibe pregunta y envía `QuestionAnswer`; `/clinician` con línea de tiempo de episodios y respuestas.
- [DOC] Diagrama de arquitectura definitivo; capturas del flujo.

**Hecho:** simulador → ingesta → detector → pregunta en el móvil → respuesta guardada → visible en el panel, todo en LinuxONE, con timestamps por etapa. **Mínimo demostrable: protégelo.**

### Fase 2 · Módulo de la sospecha y panel de evidencias
- [ML] Features circadianas y de sueño con normalización por persona; rangos de referencia NHANES; logística/RF/LightGBM con `GroupKFold`, calibración, prueba en DEPRESJON (LOSO); SHAP → `is_evidence`.
- [BE] `suspicion-module` y `evidence-api` (modelo *dummy* mientras [ML] entrena); auditoría por inferencia.
- [FE] Panel: selector de sospecha, resultado + confianza, 4 gráficas con banda de referencia y evidencia marcada, calidad del registro, aviso "not compatible ≠ ruled out".
- [DOC] Guion del vídeo con problema, cifra y escena de la demo.

**Hecho:** el médico elige "depression" sobre un paciente de DEPRESJON y ve resultado calibrado, gráficas y evidencias; métricas por persona publicadas.

### Fase 3 · Escala, equidad, seguimiento y seguridad
- [BE] Simulador multi-paciente + `tools/benchmark`; gráfica p50/p99; comparación con/sin `nnpa`.
- [ML] Equidad por sexo y edad; detector v2 (Isolation Forest) frente a z-score y regla fija; métricas en enfermeras.
- [FE] "Before and now" (DEPRESJON inicio/final); protocolo de seguridad (botones simulados) y episodio destacado; controles del paciente.
- [DOC] Capturas de benchmark y equidad; sección de regulación del README.

**Hecho:** gráficas de latencia y equidad generadas; las tres vistas extra funcionan.

### Fase 4 · Pulido y entregables
- [BE] Despliegue reproducible con un comando; `env.example`; logs sin datos sensibles.
- [ML] Script o notebook final que regenera todas las métricas y figuras.
- [FE] Revisión de lenguaje (sección 5.5) y legibilidad con alguien de fuera.
- [DOC] README final, `ATTRIBUTIONS.md` completo, vídeo ≤ 3 min con la VM en pantalla.

### Fase 5 · Opcional (solo con todo lo anterior cerrado)
- Wearable real con `bleak`. Módulos TDAH/psicosis solo con permiso de Simula. Descripción de gráficas con GenAI si se aprueba. Secure Execution documentado.

---

## 16. Criterios de aceptación globales

- [ ] Toda inferencia sobre datos de salud ocurre en la VM de LinuxONE, dentro de Docker, y queda en el registro de auditoría.
- [ ] La pregunta llega al móvil durante el episodio simulado, con timestamps visibles.
- [ ] El módulo de depresión está validado por persona, calibrado y con métricas por sexo y edad.
- [ ] El panel muestra como máximo cuatro gráficas con rango de referencia y evidencia marcada, sin texto narrativo sobre el paciente.
- [ ] El sistema nunca ejecuta una acción automática sobre el paciente ni llama a emergencias.
- [ ] Benchmark de latencia p50/p99 en servidor frente a número de pacientes.
- [ ] Repo público, README, diagrama, atribuciones, capturas y vídeo de ≤ 3 minutos.

---

## 17. Recursos útiles

- LinuxONE Community Cloud: [registro](https://linuxone.cloud.marist.edu/#/register?flag=VM), [login](https://linuxone.cloud.marist.edu/#/login), [Fast Start Guides](https://community.ibm.com/zsystems/l1cc/faststart/), [VM con Jupyter Lab ML](https://github.com/linuxone-community-cloud/jupyter-lab-ml), [vídeo "Get Your LinuxONE Ready"](https://www.youtube.com/watch?v=y9rZwSq8pw8).
- IBM: [AI on IBM Z](https://www.ibm.com/products/z/artificial-intelligence), [IBM Z Security](https://www.ibm.com/products/z/security), [zDNN](https://github.com/IBM/zDNN).
- Grabación "How to Win Datathon": https://www.youtube.com/watch?v=3FNVIPPYuJ8 · Tutorial de envío: https://youtu.be/3_L3T__zEco
- Galería de proyectos 2025: https://hack2skill.com/event/datathon-2025/project-gallery
- Experiencia del Team Oasis en L1CC (Docker + Flask, big-endian): https://community.ibm.com/community/user/blogs/akshata-pandit/2025/04/24/our-experience-using-ibm-linuxone-from-datathon-pa
