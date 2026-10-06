# PROMPT MAESTRO DEFINITIVO — Plataforma de estudio para el Examen Complexivo (Desarrollo de Software, ITSQMET)
### Teoría (120 preguntas) + Práctica (4 casos) + Plan de estudio con tiempos + Veredicto de aptitud
### Construcción DESDE CERO

> **Cómo usarlo:** crea una carpeta NUEVA y vacía, copia ahí el contenido del paquete (este archivo + la carpeta `data/`), ábrela en VS Code y dile a Claude Code que lea este archivo. **No pegues este texto en el chat** (se corta a los 50 000 caracteres): Claude Code debe leerlo desde el disco.

---

## 0. REGLAS DE TRABAJO PARA CLAUDE CODE

1. **Construye TODO desde cero** en la carpeta actual. Si no está vacía (aparte de este archivo y `data/`), avísame antes de tocar nada.
2. **Archivos de datos ya entregados (NO los inventes ni los modifiques):**
   - `data/preguntas.json` — banco de **120 preguntas** de opción múltiple (teoría).
   - `data/casos_practicos.json` — los **4 casos prácticos** (enunciado, rúbrica con puntajes, tareas con verificación, preguntas de defensa, ambigüedades).
   - `data/recursos/cursos_backup.sql` — backup del caso N2 (PostgreSQL).
   - `data/recursos/referencia_n2_postgres.sql` — solución de referencia del caso N2 (**verificada en PostgreSQL real**).
   - `data/recursos/referencia_n2_mongo.js` — solución de referencia MongoDB del caso N2 (lógica validada con un emulador; **no** con un `mongod` real).
3. Sigue el **orden de trabajo de la sección 15** y muéstrame cada archivo completo, avisando al terminar cada bloque.
4. Si algo no está especificado, elige lo más razonable, **anótalo en `DECISIONES.md`** y sigue. Solo pregunta si algo te bloquea por completo. Todo campo, ruta o archivo extra debe justificarse en `DECISIONES.md`.
5. Todo el texto visible de la interfaz va en **español**.
6. **La app NO ejecuta ni evalúa el código del estudiante.** La práctica se hace en su propio IDE; la app da el enunciado, la checklist de verificación, el cronómetro, la autoevaluación por rúbrica y el repaso de defensa.
7. Al final ejecuta las **pruebas de aceptación de la sección 16** y reporta el resultado de cada una.

---

## 1. QUÉ ES EL EXAMEN (contexto real)

El Complexivo tiene **dos partes**:
- **Teoría:** 120 preguntas de opción múltiple (4 núcleos × 3 niveles × 10).
- **Práctica:** **4 casos prácticos, uno por núcleo**, cada uno con rúbrica sobre 10:
  - **N1** VetCare — Spring Boot MVC + Spring Security + Thymeleaf (CRUD de mascotas).
  - **N2** EduTech Academy — restaurar backup, integridad, vistas, roles, triggers, MongoDB, **defensa oral (3 de 10 puntos)**.
  - **N3** Reserva de mesas — Angular + Firebase (Auth Google/correo, Firestore, Auth Guard).
  - **N4** App móvil de playlists — Firebase Auth + API de canciones + dos sistemas de navegación.

**Datos que NO se conocen y NO debes asumir como definitivos** (van en `config.py` como constantes editables y se piden/confirman en la UI; marca cada una como "confirmar con tu docente"):
`NOTA_MINIMA_APROBACION` (placeholder 7.0), `PESO_TEORIA` y `PESO_PRACTICA` (placeholder 0.5 / 0.5), duración del examen práctico (placeholder 120 min por caso), fecha del examen, motor de BD del caso N2 (PostgreSQL más probable), formato de la defensa oral.

---

## 2. STACK TECNOLÓGICO OBLIGATORIO

- **Python 3.11+**, **Flask** con **app factory puro** (`create_app()`); **NO** crees `app = create_app()` a nivel de módulo (provoca efectos secundarios al importar, p. ej. sembrar dos veces).
- **Flask-SQLAlchemy** + **SQLite** (`instance/simulador.db`), configurable con `DATABASE_URL`. **Flask-Migrate** (opcional), **Flask-Login**, **Flask-WTF** (CSRF), `werkzeug.security` para hashes. Nunca contraseñas en texto plano.
- **Frontend:** Jinja2 + **Bootstrap 5 (CDN)** + JavaScript vanilla + **Chart.js (CDN)**. Sin React ni frameworks JS.
- `requirements.txt` con **versiones fijadas**. **pytest** para pruebas.
- **Windows (obligatorio):** la consola usa `cp1252`. Fuerza UTF-8 en `stdout/stderr` al inicio de `app.py` y `seed.py` (`sys.stdout.reconfigure(encoding="utf-8")`), abre todo archivo con `encoding="utf-8"` y usa `logging` en vez de `print()` con caracteres no ASCII en rutas críticas.

---

## 3. ESTRUCTURA DE PROYECTO

```
simulador-complexivo/
├── app.py  config.py  extensions.py  models.py  seed.py
├── servicios/
│   ├── estadisticas.py     # dominio, falladas, cobertura, % por tema/núcleo/nivel
│   ├── practica.py         # notas prácticas, promedios por caso, debilidad por criterio
│   ├── planificador.py     # generación y recálculo del plan
│   └── veredicto.py        # criterios de aptitud e índice de preparación
├── blueprints/  auth.py  examen.py  estudio.py  practica.py  plan.py  dashboard.py
├── data/  preguntas.json  casos_practicos.json  recursos/…      # YA ENTREGADOS
├── static/css/estilos.css   static/js/{examen,sesion,practica}.js
├── templates/  base.html 404.html 500.html
│   auth/ examen/ estudio/ practica/ plan/ dashboard/
├── logs/  requirements.txt  .env.example  README.md  DECISIONES.md
```

---

## 4. MODELO DE DATOS (`models.py`)

**`Usuario`**: `id`, `nombre_completo` (120), `email` (único, índice), `password_hash`, `fecha_registro`; relaciones 1:N con todo lo suyo (`cascade="all, delete-orphan"`); propiedades `total_intentos`, `mejor_nota`, `nota_promedio`, `ultima_nota`, `tiempo_total_practicado`.

**`Pregunta`**: `id`, `codigo` (único, ej. `N1-F01`), `nucleo` (1–4), `nivel` (`facil|medio|dificil`), `tema` (80), `tema_slug` (índice), `enunciado` (Text con saltos de línea y código), `opciones` (**`db.JSON`**, lista de 4), `correcta` (0–3).

**`Intento`** (teoría): `id`, `usuario_id` (índice), `fecha_inicio`, `fecha_fin`, `modo` (`completo|nucleo|nivel|tema|fallidas`), `filtro`, `total_preguntas`, `aciertos`, `nota` (Float /10, 2 decimales), `duracion_segundos`, `completado`, y técnicos: `tiempo_limite_segundos`, `orden_preguntas` (JSON), `mapeo_opciones` (JSON, **dict por pregunta**: `{"<pregunta_id>": [2,0,3,1]}`, posición mostrada → índice original), `sesion_id` (FK nullable).

**`Respuesta`**: `id`, `intento_id` (índice), `pregunta_id` (índice), `opcion_elegida` (Integer nullable; **índice ORIGINAL ya des-barajado**, NULL = en blanco), `es_correcta`, `segundos_empleados` (acumulativo). Único `(intento_id, pregunta_id)`.

**`CasoPractico`** (se siembra desde `casos_practicos.json`): `id`, `codigo` (`P1..P4`, único), `nucleo`, `titulo`, `tecnologia`, `tiempo_sugerido_min`, `enunciado` (Text), `rubrica` (JSON), `defensa` (JSON), `ambiguedades` (JSON), `recursos` (JSON).

**`IntentoPractico`**: `id`, `usuario_id` (índice), `caso_id` (FK), `fecha_inicio`, `fecha_fin`, `tiempo_limite_segundos`, `duracion_segundos`, `completado`, `tareas_ok` (JSON: lista de ids de tarea marcadas), `notas` (Text), `nota_autoevaluada` (Float /10), `sesion_id` (FK nullable).

**`EvaluacionCriterio`**: `id`, `intento_practico_id` (índice), `criterio_id` (ej. `P2-R4`), `puntaje_maximo`, `puntaje_sugerido` (calculado = máximo × tareas_ok/tareas_total del criterio), `puntaje_final` (lo que el estudiante confirma, 0–máximo, paso 0.25, **nunca > máximo**), `comentario`.

**`RepasoDefensa`**: `id`, `usuario_id`, `caso_id`, `indice_pregunta`, `nivel` (`no_se|parcial|dominado`), `fecha`.

**`PlanEstudio`**: `id`, `usuario_id`, `fecha_creacion`, `fecha_inicio`, `fecha_examen`, `horas_por_dia` (JSON `{"lun":2,…,"dom":0}`), `nota_minima`, `peso_teoria`, `peso_practica`, `porcentaje_tiempo_practica` (default 50), `activo` (solo uno por usuario), `advertencias` (JSON), `ultima_recalculacion`.

**`SesionEstudio`**: `id`, `plan_id` (índice), `fecha` (índice), `orden`, `fase` (`diagnostico|cobertura|refuerzo|simulacro|repaso_final`), `tipo` (`tarjetas|practica_tema|simulacro_nucleo|simulacro_completo|fallidas|repaso_ligero|practica_caso|intento_practico|defensa`), `nucleo`, `tema_slug`, `caso_codigo`, `criterio_id` (nullable: para sesiones de remedio de un criterio práctico), `titulo`, `minutos_planificados`, `minutos_reales`, `estado` (`pendiente|completada|omitida`), `completada_en`, `resultado_aciertos`, `resultado_total`.

**`RepasoTarjeta`**: `id`, `usuario_id`, `pregunta_id`, `sabia`, `fecha` (solo ordena el repaso; **nunca** afecta nota, dominio ni veredicto).

**`VeredictoDiario`**: `usuario_id`, `fecha`, `veredicto`, `indice`, `nota_teoria`, `nota_practica`, `nota_final_estimada`.

---

## 5. REGLAS DE NEGOCIO TRANSVERSALES (centralízalas en `servicios/`)

**Teoría**
1. **Nota del intento** = `aciertos / total_preguntas * 10` sobre el TOTAL asignado (60 aciertos de 120 respondiendo solo 60 = 5.00).
2. **En blanco** (`opcion_elegida IS NULL`): no suma, pero **no es "fallada"** ni cuenta como "respondida" en la cobertura.
3. **% por tema/núcleo/nivel** = aciertos / respondidas (excluye blancos). Nota al pie visible en el dashboard: *"Los porcentajes por tema, núcleo y nivel excluyen las preguntas dejadas en blanco; la nota del intento se calcula sobre el total."*
4. **Fallada** = su ÚLTIMA respuesta (por `Intento.fecha_fin`, solo `completado=True`, filtro dentro de la consulta) es incorrecta **y** no en blanco.
5. **Dominada** = última respuesta correcta. **Dominada estable** = últimas dos respuestas (intentos distintos) correctas.
6. **Cobertura** = preguntas con al menos una respuesta no en blanco / 120.

**Práctica**
7. **Nota de un intento práctico** = Σ `puntaje_final` de sus criterios (máx. 10). Es **autoevaluada**; por eso el veredicto aplica un descuento conservador (sección 12).
8. **Nota de un caso** = promedio de sus **últimos 2 intentos completados** (o el único si solo hay uno).
9. Un intento práctico es **válido** para el veredicto solo si está **completado, cronometrado y con todas las tareas revisadas** (cada criterio con `puntaje_final` confirmado).
10. La checklist es la fuente del `puntaje_sugerido`: la app solo sugiere; el estudiante confirma, y se le recuerda: *"Marca una tarea solo si ejecutaste su verificación."*

**Comunes**
11. **Aislamiento:** toda ruta con `intento_id`, `intento_practico_id`, `plan_id` o `sesion_id` verifica pertenencia; si no → **403**.
12. Intentos completados son **inmutables**. **Un solo intento pendiente** de teoría y **uno** de práctica por usuario (ofrecer continuar o descartar).
13. Usa `joinedload/selectinload` (sin N+1). Un intento de 120 preguntas debe finalizar sin caídas ni lentitud.

---

## 6. AUTENTICACIÓN

- **`/registro`**: nombre completo, email (válido y único), contraseña (mín. 8), confirmación. Al registrarse inicia sesión y va al dashboard.
- **`/login`**: email + contraseña + "Recordarme". Error genérico *"Correo o contraseña incorrectos"*. `next` solo si es ruta interna segura.
- **`/logout`** con **botón "Cerrar sesión" siempre visible** en la navbar junto al nombre.

---

## 7. SIMULACRO TEÓRICO

### 7.1 Configurar (`/examen/configurar`)
- Modos: `completo` (120) · `nucleo` (30) · `nivel` (40) · `tema` · `fallidas`.
- Opciones: orden aleatorio (default sí), barajar opciones (default sí), tiempo (default **1 min/pregunta**, editable 10–600 s).
- `tiempo_limite_segundos = segundos_por_pregunta × total_preguntas`.
- Modo `fallidas` sin falladas: **no crear intento**; `flash` y volver al formulario.
- Acepta `?modo=fallidas` y `?modo=tema&tema=<slug>` por GET para prellenar.

### 7.2 Rendir (`/examen/<id>`)
- Una pregunta a la vez, Anterior/Siguiente, **grilla** (sin responder / respondida / marcada; marcas en `localStorage`, **se limpian al finalizar**).
- **Temporizador `MM:SS`** regresivo: amarillo al 25%, **rojo parpadeante** <60 s, **autoenvío** a 0. **Persiste al recargar**: el servidor calcula el restante desde `fecha_inicio`, el JS se ancla a ese valor y **re-sincroniza cada 20 s** (`/examen/<id>/tiempo`).
- Cada selección se guarda por **fetch/AJAX** con CSRF: recibe la posición visual, la traduce con `mapeo_opciones` y guarda el índice original; acumula `segundos_empleados`.
- Enunciado con `white-space: pre-wrap` (hay código SQL/JS/JSON), monoespaciada en bloques de código.
- Si el tiempo ya se agotó al abrir → **auto-finaliza**. Las no respondidas quedan en blanco (gris); nunca se descarta el intento.
- **Finalizar** con modal que avisa cuántas quedan sin responder.

### 7.3 Finalizar (`POST /examen/<id>/finalizar`)
- **Solo POST** con CSRF; un GET redirige al intento (sin "Method Not Allowed" crudo).
- **Idempotente**: si ya está completado, redirige al resultado sin recalcular. Pendiente con respuestas guardadas → se puede finalizar en cualquier momento.
- `try/except` con `db.session.rollback()` y `logging` del traceback en `logs/errores.log`; un fallo da 500 legible, **nunca tumba el servidor**.
- Calcula nota y duración; si tiene `sesion_id` completa la sesión; luego dispara el **recálculo automático** del plan.

### 7.4 Resultado y revisión
- Nota /10, aciertos, fallos, blancos, %, tiempo, desglose por núcleo y nivel, mensaje motivacional (≥9 excelente · 7–8.9 bien · 5–6.9 reforzar · <5 estudio intensivo).
- Revisión en el **orden y con las opciones tal como el estudiante las vio** (`mapeo_opciones`): correcta **siempre en verde ✓**, elegida errónea en **rojo ✗**, sin responder en **gris**. Clases `.text-success/.border-success/.bg-success-subtle` y `.text-danger/.border-danger/.bg-danger-subtle`. Función única `construir_revision(intento)` reutilizada por resultado y dashboard.

---

## 8. MODO TARJETAS DE ESTUDIO (`/estudio/tema/<slug>`)

Frente = enunciado; reverso = opción correcta + las otras marcadas como incorrectas. Botones **"La sabía / No la sabía"** (guardan `RepasoTarjeta`; las "no sabía" salen primero). **Temporizador de sesión** regresivo con `minutos_planificados` si viene de una sesión (`?sesion=<id>`); "Terminar sesión" guarda `minutos_reales` y marca `completada`.

---

## 9. MÓDULO DE PRÁCTICA (los 4 casos) — `blueprints/practica.py` + `servicios/practica.py`

### 9.1 Vistas
- **`/practica`**: 4 tarjetas (P1–P4) con núcleo, tecnología, nº de intentos, **última nota**, mejor nota, semáforo (verde ≥ nota mínima+margen, amarillo ≥ mínima, rojo <), y el botón "Ver caso".
- **`/practica/<codigo>`**: enunciado completo, **rúbrica** con puntajes, lista de **ambigüedades** (recuadro amarillo *"Confírmalo con tu docente"*), recursos descargables (`/practica/recurso/...` sirviendo solo los archivos de `data/recursos/`, sin path traversal), botón **"Iniciar intento cronometrado"**, y enlaces a **Defensa** e historial de intentos del caso.
- **Solo P2** muestra además la pestaña **"Referencia"** con `referencia_n2_postgres.sql` y `referencia_n2_mongo.js` (bloques de código con botón copiar) y la nota: *"Referencia para estudiar y comparar tras tu intento. La de PostgreSQL fue probada en un servidor real; la de MongoDB se validó solo con un emulador. Si tu examen usa otro motor, adáptala."*
- **`/practica/intento/<id>`** (en curso): cronómetro regresivo (tiempo = `tiempo_sugerido_min` del caso, editable al iniciar; **persistente en servidor**, mismo mecanismo que el examen teórico, con resincronización), **checklist agrupada por criterio** de la rúbrica (cada tarea muestra su texto y, plegada, su "Cómo verificarlo"), bloc de notas, guardado AJAX de `tareas_ok` y `notas`. Botón **"Terminar y autoevaluar"** (o autoterminar al expirar el tiempo).
- **`/practica/intento/<id>/autoevaluar`**: por cada criterio muestra el `puntaje_sugerido`, un campo `puntaje_final` (0 a máximo, paso 0.25, validado en servidor) y comentario. Aviso de honestidad visible. Al confirmar: calcula `nota_autoevaluada`, marca `completado`, guarda `EvaluacionCriterio`.
- **`/practica/intento/<id>/resultado`**: nota /10, desglose por criterio con barra verde/amarilla/roja (según % del máximo), tiempo usado, y **"Qué reforzar"** (criterios con menor %).
- **`/practica/<codigo>/defensa`**: tarjetas de defensa. Cada tarjeta = pregunta → botón "Ver respuesta clave" → autocalificar `No sé / Parcial / Dominado` (guarda `RepasoDefensa`). **Modo simulacro oral:** temporizador de 2 min por pregunta, orden aleatorio, prioriza las no dominadas.

### 9.2 Cálculos (en `servicios/practica.py`)
- `nota_caso(usuario, caso)` (regla 5.8), `nota_practica_promedio(usuario)` = promedio simple de los 4 casos con intentos válidos.
- `debilidad_por_criterio(usuario, caso)`: % del máximo obtenido en el último intento por criterio → alimenta el planificador.
- `dominio_defensa(usuario, caso)` = % de preguntas cuyo **último** registro es `dominado` (parcial cuenta 0.5).

---

## 10. PLAN DE ESTUDIO PERSONALIZADO (teoría + práctica) — `servicios/planificador.py` + `blueprints/plan.py`

### 10.1 Crear plan (`/plan/crear`)
Campos: **fecha del examen** (> hoy), **fecha de inicio** (default hoy), **horas por día de la semana** (7 campos 0–12, paso 0.5; 0 = descanso), **nota mínima** (default de config, ayuda *"Confírmala con tu instituto"*), **peso teoría / peso práctica** (default 50/50, suman 100, ayuda *"Confírmalos con tu docente"*), **% del tiempo para práctica** (default 50). Un solo plan activo por usuario (el anterior queda inactivo, se conserva su historial). Validaciones: fecha del examen > inicio; al menos un día con horas > 0.

### 10.2 Insumos
- **Días de estudio** = fechas entre inicio y examen−1 con horas > 0.
- **Teoría:** dominio por tema, factor de nivel (fácil 1.0, medio 1.5, difícil 2.0), factor de núcleo (N2 ×1.25), peso del tema, **prioridad** = peso × (1 − dominio); minutos por tema = `MIN_POR_PUNTO_PESO` (8) × peso, múltiplos de 5, mín. 20; reparto 35% tarjetas / 65% práctica del tema.
- **Práctica:** por caso, `tiempo_sugerido_min`; **prioridad del caso** = (10 − nota_caso)/10 (sin intentos = 1.0, prioridad máxima); **prioridad del criterio** = puntaje_máximo × (1 − % obtenido).
- El tiempo total se reparte entre teoría y práctica según `porcentaje_tiempo_practica`.

### 10.3 Fases
1. **Diagnóstico** (si el usuario no tiene diagnóstico previo): 4 `simulacro_nucleo` de 30 min (teoría) + **1 `intento_practico` por caso** como línea base (cronometrado; se distribuyen en los primeros días según la capacidad diaria).
2. **Cobertura (~50%)**: teoría por tema (tarjetas + práctica) por prioridad descendente; práctica con sesiones `practica_caso` (bloques de 45–90 min) que atacan el **criterio más débil** de cada caso, empezando por los casos de mayor prioridad; sesiones `defensa` (25 min) para P2 con prioridad alta y para los demás casos con prioridad media.
3. **Refuerzo (~25%)**: `fallidas` (se resuelven dinámicamente el día en que tocan) y repaso de tarjetas de temas con dominio < 70%; nuevos `practica_caso` sobre criterios aún < 70%.
4. **Simulacros (~15%)**: `simulacro_completo` de teoría espaciados cada 3–4 días de estudio en el último tercio (mínimo 2 si alcanza) y **un `intento_practico` completo por caso** en el último tercio (mínimo 1 más por caso si alcanza).
5. **Repaso final (~10%)**: penúltimo día `simulacro_completo` (o por núcleo si hay poco tiempo) y `defensa` de P2; **último día antes del examen**: solo `repaso_ligero` (≤ 60 min; tarjetas de falladas y defensa), sin simulacros ni contenido nuevo, y recomendación de descanso.

### 10.4 Empaquetado en días
- Llena cada día hasta sus minutos. Una sesión que no cabe se **divide en bloques de 20–50 min** (pausa de 10 min sugerida cada 50); los bloques de práctica pueden ser de hasta 90 min.
- **Modo intensivo** si hay < 3 días de estudio (plan de emergencia: diagnóstico rápido, falladas, criterios prácticos más débiles, repaso final) con advertencia.
- **Tiempo insuficiente:** escala hacia abajo dejando fuera temas/criterios de MENOR prioridad; guarda en `advertencias` qué quedó sin cubrir y **cuántas horas faltan**; muéstralo en rojo. Si el examen es hoy o ya pasó: mensaje claro y sin plan.

### 10.5 Ejecutar sesiones
Botón **Iniciar** por sesión según `tipo`:
- `tarjetas` → `/estudio/tema/<slug>?sesion=<id>` · `practica_tema | simulacro_nucleo | simulacro_completo | fallidas` → crea `Intento` con `sesion_id` (flujo 7.1) y se completa sola al finalizar guardando aciertos/total.
- `practica_caso` → abre `/practica/<codigo>` con el criterio objetivo destacado y un **cronómetro de sesión** (`sesion.js`); al terminar guarda `minutos_reales`.
- `intento_practico` → crea `IntentoPractico` con `sesion_id`; se completa al confirmar la autoevaluación.
- `defensa` → `/practica/<codigo>/defensa?sesion=<id>` · `repaso_ligero` → tarjetas de falladas.
- **Omitir** marca `omitida` y dispara reprogramación.

### 10.6 Recálculo dinámico
Automático tras finalizar cualquier intento (teórico o práctico) y manual con **"Recalcular plan"**. Conserva las sesiones `completada/omitida`; regenera solo las **pendientes futuras desde hoy** con dominio/notas/criterios actualizados. Las **atrasadas** se reprograman en los próximos días con capacidad (antes que las nuevas) o pasan a `advertencias`. Actualiza `ultima_recalculacion`.

### 10.7 Vistas del plan
- **`/plan`**: **cuenta regresiva** ("Faltan N días"), cumplimiento (completadas / vencidas), horas planificadas vs reales, **racha** de días consecutivos con sesión completada, tarjeta **"Hoy toca"**, advertencias, resumen del veredicto con enlace.
- **`/plan/semana`**: calendario semanal/mensual coloreado (verde completada, amarillo hoy pendiente, rojo atrasada, gris omitida), con icono distinto para teoría y práctica.
- **`/plan/pendientes-docente`**: lista "Puntos por confirmar con tu docente" (nota mínima, ponderación teoría/práctica, duración del práctico, motor de BD del caso N2, formato de la defensa, requisitos 19–22 y 24 ausentes en el PDF del caso N3, formato de la duración en la API del caso N4, interpretación de "dos sistemas de navegación" en N4), con casillas guardadas en `localStorage`. Enlázala desde el plan y el veredicto.

---

## 11. CONSTANTES (`config.py`, todas editables)

```
NOTA_MINIMA_APROBACION = 7.0          # PLACEHOLDER - confirmar
PESO_TEORIA            = 0.5          # PLACEHOLDER - confirmar
PESO_PRACTICA          = 0.5          # PLACEHOLDER - confirmar
MARGEN_SEGURIDAD       = 1.0
DESCUENTO_AUTOEVALUACION = 0.5        # se resta a la nota práctica autoevaluada
TIEMPO_PRACTICA_DEFAULT_MIN = 120     # PLACEHOLDER - confirmar
MIN_PREGUNTAS_SIMULACRO_VALIDO = 60
N_SIMULACROS_REFERENCIA = 3
MIN_SIMULACROS_VALIDOS  = 2
MIN_INTENTOS_PRACTICA_POR_CASO = 1    # recomendado 2 (se muestra como aviso)
UMBRAL_NUCLEO_MIN       = 70
UMBRAL_DOMINIO_ESTABLE  = 70
UMBRAL_COBERTURA        = 95
UMBRAL_DEFENSA          = 70
UMBRAL_CUMPLIMIENTO_PLAN= 80
MIN_POR_PUNTO_PESO      = 8
```

---

## 12. VEREDICTO DE APTITUD (`servicios/veredicto.py`, `/plan/veredicto`)

> **Orientativo y conservador.** Se basa en el banco de 120 preguntas y en tu autoevaluación práctica; el examen real puede diferir. Muestra este aviso siempre. Preferible un "EN RIESGO" justificado que un "APTO" por un intento afortunado o una autoevaluación generosa.

### 12.1 Criterios de TEORÍA (checklist ✓/✗ con "valor actual vs meta")
- **T1** Nota de referencia (promedio de los últimos `N_SIMULACROS_REFERENCIA` simulacros **válidos**, ≥ 60 preguntas) ≥ `nota_minima + MARGEN_SEGURIDAD`.
- **T2** Ningún núcleo < `UMBRAL_NUCLEO_MIN`%. **T3** Dominio estable ≥ `UMBRAL_DOMINIO_ESTABLE`%. **T4** Cobertura ≥ `UMBRAL_COBERTURA`%.
- **T5** ≥ `MIN_SIMULACROS_VALIDOS` simulacros válidos. **T6** Tendencia (regresión de las últimas 3–5 notas) ≥ 0.

### 12.2 Criterios de PRÁCTICA
- **nota práctica ajustada** = `max(0, nota_practica_promedio − DESCUENTO_AUTOEVALUACION)`; también por caso.
- **P1** nota práctica ajustada promedio ≥ `nota_minima + MARGEN_SEGURIDAD`.
- **P2** **Ningún caso** con nota ajustada < `nota_minima` (regla del eslabón débil: un caso débil arrastra el examen).
- **P3** Cada caso con ≥ `MIN_INTENTOS_PRACTICA_POR_CASO` intento válido (si solo tiene 1, aviso: "recomendado 2").
- **P4** Dominio de defensa del caso P2 ≥ `UMBRAL_DEFENSA`% (la defensa vale 3 de 10 en ese caso).

### 12.3 Criterio COMÚN
- **C1** Cumplimiento del plan ≥ `UMBRAL_CUMPLIMIENTO_PLAN`% (solo con plan activo; si no hay, se indica).

### 12.4 Veredicto global
- **nota final estimada** = `peso_teoria × nota_ref_teoria + peso_practica × nota_practica_ajustada`.
- **SIN DATOS** (gris): falta teoría (0 simulacros válidos) **o** falta práctica (algún caso sin intento válido) → lista exactamente qué falta y con botones para hacerlo. Aun así muestra el veredicto parcial de la parte que sí tiene datos.
- **APTO** (verde): teoría cumple T1–T6, práctica cumple P1–P4 y C1 (si aplica).
- **EN RIESGO** (amarillo): `nota final estimada ≥ nota_minima` pero falla algún criterio → lista cuáles y qué hacer.
- **NO APTO AÚN** (rojo): `nota final estimada < nota_minima`.
- **Regla del eslabón débil global:** si la nota de teoría o la de práctica está por debajo de `nota_minima`, el veredicto **no puede ser APTO** aunque el promedio ponderado alcance.

### 12.5 Extras del veredicto
- **Índice de preparación 0–100** = 35% teoría (nota_ref/10) + 15% dominio estable + 30% práctica ajustada (/10) + 10% núcleo más débil + 5% defensa P2 + 5% cumplimiento (si no hay plan, se reparte proporcionalmente). Barra con color.
- **Proyección** de la nota final al día del examen por regresión lineal (mín. 3 puntos por componente; limitada a 0–10; etiquetada *estimación*); con menos puntos: *"Datos insuficientes para proyectar."*
- **Suficiencia de tiempo:** minutos aún necesarios (temas con dominio < 70% + criterios prácticos < 70% + intentos que faltan) vs minutos disponibles → Suficiente / Justo / Insuficiente.
- **Recomendaciones** (máx. 5) por reglas: caso o criterio más débil (con enlace), tema más débil, simulacros o intentos que faltan, si conviene subir horas, tendencia negativa, defensa sin ensayar.
- **Foto diaria** en `VeredictoDiario` y gráfica de evolución del índice.
- **Aviso fijo:** *"Este veredicto es una estimación basada en el banco de práctica y en tu autoevaluación; no garantiza el resultado del examen real."*

---

## 13. DASHBOARD (`/dashboard`)

- Tarjetas: intentos teóricos, mejor nota, promedio, última nota, tiempo practicado, **días para el examen**, **veredicto actual**, **nota final estimada**.
- **Línea:** evolución de la nota teórica por intento + indicador de mejora (primero vs último, flecha ↑ verde / ↓ roja, %). **Barras:** % de acierto por núcleo y por nivel.
- **Panel práctica:** nota por caso (última y mejor) en barras con semáforo, y evolución de las notas prácticas.
- **"Qué debes estudiar":** 8 temas con menor % (barra roja/amarilla/verde) con botones "Estudiar tarjetas" y "Practicar tema"; y **criterios prácticos más débiles** (caso, criterio, % obtenido) con botón "Practicar este criterio".
- **"Preguntas que has fallado":** ranking por fallos acumulados y botón **"Practicar solo estas"**.
- **Cobertura del banco:** respondidas / 120 y dominadas. Widget **"Hoy toca"**.
- **Historial** (`/dashboard/historial`): teóricos y prácticos (fecha, tipo, filtro/caso, nota, duración; fila verde ≥7, amarilla 5–6.9, roja <5) con enlace a la revisión. **Debilidades** (`/dashboard/debilidades`): ranking completo de temas y criterios.

---

## 14. INTERFAZ Y SEED

- Bootstrap 5 responsive (móvil), modo claro. Navbar: "Simulador Complexivo", **Dashboard · Nuevo examen · Práctica · Plan de estudio · Estudiar · Historial**, y a la derecha usuario + **Cerrar sesión**. Páginas 404/500 personalizadas. CSRF en todos los formularios y fetch. Clases `.enunciado-pregunta` (pre-wrap, monoespaciada, fondo gris claro) y `.parpadeo`.
- **Seed** (`seed.py`, `flask seed`, auto-seed si `Pregunta` está vacía, una sola vez): carga `preguntas.json` (idempotente por `codigo`, precarga existentes en un dict, `commit` con `try/except` + `rollback()` y relanza) y `casos_practicos.json` (idempotente por `codigo`). **Valida**: 120 preguntas (30 por núcleo, 40 por nivel) y 4 casos cuyo Σ de puntajes de rúbrica sea 10.0 cada uno. Si no cuadra, imprime advertencia clara en vez del ✔; si cuadra: `✔ 120 preguntas y 4 casos prácticos cargados (30 por núcleo, 40 por nivel)`.

---

## 15. ORDEN DE TRABAJO (avísame al terminar cada bloque)

1. `requirements.txt`, `config.py` (constantes de la sección 11), `extensions.py`, `.env.example`
2. `models.py` completo + `DECISIONES.md`
3. `seed.py` (verifica que `data/` está completo: 120 preguntas y 4 casos)
4. `servicios/estadisticas.py` y `servicios/practica.py`
5. `blueprints/auth.py` + plantillas
6. `blueprints/examen.py` + plantillas + `static/js/examen.js`
7. `blueprints/estudio.py` + plantilla de tarjetas + `static/js/sesion.js`
8. `blueprints/practica.py` + `templates/practica/*` + `static/js/practica.js`
9. `servicios/planificador.py` + `servicios/veredicto.py` **con pruebas pytest** de ambos algoritmos
10. `blueprints/plan.py` + `templates/plan/*`
11. `blueprints/dashboard.py` + `templates/dashboard/*`
12. `app.py` (factory, blueprints, CLI `flask seed`, logging rotativo, handlers 404/500), `base.html`, `estilos.css`
13. `README.md` (`python -m venv venv` · `venv\Scripts\activate` · `pip install -r requirements.txt` · `flask seed` · `flask run`)

---

## 16. PRUEBAS DE ACEPTACIÓN (ejecútalas y reporta cada una)

1. Arranca sin errores en Windows; `flask routes` lista todo; BD con 120 preguntas (30/núcleo, 40/nivel) y 4 casos; `seed` no duplica al ejecutarse dos veces.
2. Registro, login, logout y botón de cerrar sesión visible.
3. **Examen de 120 preguntas respondidas por AJAX → `Finalizar` calcula la nota y muestra el resultado sin caídas.** Un GET a `/finalizar` no rompe; finalizar dos veces no recalcula.
4. Recargar a mitad del examen: el temporizador **no se reinicia**. Al expirar: auto-finaliza y deja en blanco las no respondidas.
5. Con barajado: verde en la correcta real y rojo en la elegida, en resultado y en revisión.
6. Notas: 1 acierto de 30 → 0.33; 60 aciertos respondiendo solo 60 de 120 → 5.00.
7. Modo `fallidas`: sin falladas → mensaje y sin intento; una en blanco NO aparece como fallada; una fallada luego acertada deja de aparecer.
8. Aislamiento: 403 al abrir intento/plan/sesión/intento práctico de otro usuario.
9. **Práctica:** (a) `/practica` muestra los 4 casos; (b) iniciar un intento, marcar tareas, terminar y autoevaluar guarda `EvaluacionCriterio` y una nota que **no puede exceder el máximo por criterio ni 10**; (c) el cronómetro práctico persiste al recargar y autotermina al expirar; (d) solo P2 muestra la pestaña Referencia; (e) el recurso servido no permite path traversal (`../`); (f) la defensa guarda `RepasoDefensa` y el modo oral respeta 2 min por pregunta.
10. **Plan:** (a) examen en 30 días con 2 h/día genera diagnóstico (teoría + 4 intentos prácticos), cobertura, refuerzo, simulacros, repaso final; (b) examen en 2 días → modo intensivo; (c) tiempo insuficiente → advertencia con horas faltantes y qué quedó sin cubrir; (d) examen hoy/pasado → mensaje sin plan; (e) 0 horas todos los días → error de validación; (f) el último día solo tiene repaso ligero; (g) `porcentaje_tiempo_practica` cambia el reparto teoría/práctica.
11. **Recálculo:** tras un intento teórico con muchos fallos en un tema, ese tema sube de prioridad; tras un intento práctico con un criterio bajo, se agenda una sesión `practica_caso` sobre ese criterio; atrasadas se reprograman; las completadas no cambian.
12. **Veredicto:** sin datos → SIN DATOS con la lista de lo que falta; un simulacro afortunado de 10/10 con < 2 válidos NO da APTO; teoría alta con **un caso práctico < nota mínima → nunca APTO** (eslabón débil); nota práctica autoevaluada 10 se ajusta a 9.5; núcleo < 70% → EN RIESGO marcando ese criterio ✗; nota final estimada < mínima → NO APTO AÚN; todos los criterios ✓ → APTO. Cada criterio muestra valor actual vs meta.
13. Tarjetas: "no sabía" salen primero y no alteran nota, dominio ni veredicto.
14. **pytest** de `planificador.py`, `veredicto.py` y `practica.py` en verde.
15. La página "Puntos por confirmar con tu docente" existe y enlaza desde el plan y el veredicto.
16. Base de datos entregada **limpia**: 120 preguntas, 4 casos, 0 usuarios/intentos/planes de prueba.

---

## 17. NOTAS SOBRE LOS DATOS

- **Banco teórico:** dos preguntas del export original de Moodle traían errores ya corregidos en el JSON: `N4-D01` (opción correcta partida en dos filas por el `==`) y `N2-M04` (dos opciones marcadas correctas; queda solo la del nombre del empleado). **Usa el JSON tal cual.** Estructura: `id`, `nucleo` (1 Spring Boot/MVC/JPA · 2 Bases de Datos · 3 Angular/Firebase · 4 Móvil/APIs/Firebase), `nivel`, `tema`, `enunciado`, `opciones` (4), `correcta` (0–3).
- **Casos prácticos:** provienen de los PDFs oficiales; las tareas y las verificaciones son una descomposición de cada rúbrica hecha para estudiar, no texto oficial. Los wireframes del caso N4 se describen en su enunciado. Las ambigüedades detectadas en los PDFs están en el campo `ambiguedades` de cada caso y deben mostrarse en la UI.
- **Referencia N2:** la solución de PostgreSQL se ejecutó contra un servidor real (triggers, CHECK, UNIQUE, vistas y privilegios verificados; se confirmó que un trigger `AFTER DELETE` falla por la FK). La de MongoDB se validó con un emulador. Todo es material de estudio para comparar **después** de intentar el caso por cuenta propia.
