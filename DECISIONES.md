# DECISIONES.md — Decisiones tomadas donde la especificación no era explícita

Cada punto indica **qué** se decidió y **por qué**. Todo campo, ruta o archivo extra respecto al PROMPT MAESTRO está aquí.

## Estructura y entorno

1. **Raíz del proyecto = carpeta actual** (`complexivo-pack/`), no una subcarpeta `simulador-complexivo/`. La regla 0.1 pide construir "en la carpeta actual" y `data/` ya estaba ahí.
2. **Flask-Migrate no se usa** (la especificación lo marca como opcional). El esquema se crea con `db.create_all()` dentro de `create_app()`. Así hay una dependencia menos y nada que migrar en una BD que se entrega limpia.
3. **Python 3.14** es el intérprete instalado en esta máquina; las versiones de `requirements.txt` se verificaron instalándolas en un `venv` con él. `SQLAlchemy` se fija en la rama 2.0 (2.0.51) porque `Flask-SQLAlchemy 3.1.1` está probado con ella.
4. **`python-dotenv`** está en requirements: `config.py` carga `.env` (UTF-8) para que `SECRET_KEY` y `DATABASE_URL` funcionen tanto con `flask run` como con `python app.py`.
5. **Fechas y horas locales sin zona** (`datetime.now()`): la app es de uso local y personal, y el plan trabaja con "hoy" en la fecha del equipo del estudiante. Los temporizadores usan diferencias entre dos instantes locales, así que no les afecta la zona.
6. **PRAGMA foreign_keys=ON** en cada conexión SQLite (`extensions.py`); sin él, SQLite ignora `ON DELETE CASCADE / SET NULL`.
7. **`WTF_CSRF_TIME_LIMIT = None`**: un examen de 120 preguntas dura 2 h por defecto (hasta 20 h con 600 s/pregunta) y el token CSRF por defecto caduca a la hora, lo que rompería el guardado AJAX. El token sigue ligado a la sesión del usuario.
8. El `venv/` creado durante el desarrollo está dentro de la carpeta; puede reutilizarse o borrarse y recrearse con los pasos del README.

## Constantes extra en `config.py`

| Constante | Valor | Motivo |
|---|---|---|
| `FECHA_EXAMEN`, `MOTOR_BD_N2`, `FORMATO_DEFENSA` | placeholders | Sección 1: datos desconocidos que deben vivir en `config.py` como editables. |
| `SEGUNDOS_POR_PREGUNTA_DEFAULT/MIN/MAX` | 60 / 10 / 600 | Sección 7.1 (1 min/pregunta, editable 10–600 s). |
| `INTERVALO_RESYNC_SEGUNDOS` | 20 | Sección 7.2 (re-sincronización cada 20 s). |
| `GRACIA_SEGUNDOS` | 5 | Tolerancia de red: una respuesta que llega 1–2 s después de 00:00 por latencia no se pierde. |
| `SEGUNDOS_DEFENSA_ORAL` | 120 | Sección 9.1 (2 min por pregunta). |
| `FACTOR_NIVEL`, `FACTOR_NUCLEO` | 1.0/1.5/2.0; N2 ×1.25 | Sección 10.2, centralizados. |
| `MIN_POR_PUNTO_CRITERIO` | 30 | Duración de una sesión `practica_caso` = 30 min × puntaje del criterio, acotada a 45–90 min (sección 10.3 pide bloques de 45–90). |
| `DURACION_*` | 30 / 120 / 25 / 60 / 30 / 20 | Duraciones de sesión citadas en la especificación (simulacro de núcleo 30, defensa 25, repaso ligero ≤ 60) o necesarias para el planificador (fallidas 30, repaso de tarjetas 20 = mínimo de un bloque). |
| `NOMBRES_NUCLEO`, `NOMBRES_NIVEL` | textos | Etiquetas en español para la interfaz. |

## Modelo de datos

1. **`Pregunta.codigo` = campo `id` del JSON** (`N1-F01`…).
2. **`tema_slug = "n<núcleo>-<slug del tema>"`**. El tema "Normalización" existe en N1 y en N2; si el slug no incluyera el núcleo, se mezclarían temas de núcleos distintos y el factor de núcleo (N2 ×1.25) del planificador sería ambiguo.
3. **`IntentoPractico.fecha_fin`** se fija al **terminar** (botón o expiración), antes de autoevaluar; `completado=True` solo tras confirmar la autoevaluación. Así el cronómetro se detiene al terminar y la autoevaluación puede hacerse sin prisa.
4. **`VeredictoDiario`** lleva además `id` como clave primaria y una restricción única `(usuario_id, fecha)`: una foto por día (se actualiza si se vuelve a calcular ese día).
5. **`EvaluacionCriterio`** con restricción única `(intento_practico_id, criterio_id)`.
6. **Relaciones `Intento.sesion` / `IntentoPractico.sesion`** con `ondelete="SET NULL"`: si se borra un plan, los intentos del estudiante se conservan.
7. **`Usuario.plan_activo`** (propiedad extra) evita repetir la misma consulta en todas las vistas.
8. **`Usuario.tiempo_total_practicado`** (en segundos) suma la duración de los intentos teóricos y prácticos completados, más los `minutos_reales` de las sesiones de plan que no generan intento (`tarjetas`, `practica_caso`, `defensa`, `repaso_ligero`). Así no se cuenta dos veces una sesión que ya creó un intento.
9. **Criterio de defensa**: se identifica porque el nombre del criterio contiene "defensa" (en los datos solo lo cumple `P2-R6`). Ese criterio no genera sesiones `practica_caso`; se entrena con sesiones `defensa`.

## Seed

1. **Idempotente por `codigo`**: si una pregunta o caso ya existe, no se toca (no se "actualiza"): los JSON son la fuente y no se modifican.
2. **La validación se hace sobre lo que quedó en la BD** (120 preguntas, 30/núcleo, 40/nivel, 4 opciones y `correcta` 0–3; 4 casos P1–P4 cuya rúbrica suma 10.0). Si algo no cuadra se imprime `ADVERTENCIA:` con la lista de problemas en lugar del ✔.
3. **Salida por consola con `click.echo`** tras forzar UTF-8 en stdout/stderr (el ✔ no existe en cp1252).

## Estadísticas teóricas

1. **"Última respuesta"** = el último registro de `Respuesta` por `Intento.fecha_fin` (solo completados), **incluido un blanco**: si la última vez la dejó en blanco, deja de ser "fallada" (regla 5.4 tal cual: "incorrecta **y** no en blanco").
2. **Dominio de un tema** (planificador) = preguntas del tema cuya última respuesta es correcta / preguntas del tema.
3. **Núcleo diagnosticado** = existe un intento completado en modo `completo` o en modo `nucleo` de ese núcleo.
4. **"8 temas con menor %"**: primero los temas con respuestas (menor % primero); si hay menos de 8, se completan con temas aún sin responder, marcados como "sin responder".
5. Las respuestas se guardan también cuando solo cambia el tiempo empleado (`accion: "tiempo"`), creando la fila en blanco si hace falta: así `segundos_empleados` acumula aunque no se responda.

## Examen teórico

1. **Tolerancia de 5 s** (`GRACIA_SEGUNDOS`) para respuestas que llegan justo al expirar; después se rechazan con `expirado` y el cliente autoenvía.
2. **`fecha_fin` de un intento expirado** = `fecha_inicio + tiempo_limite` (no el momento en que se abrió tarde), y `duracion_segundos` nunca supera el límite.
3. **Botón "Borrar"** para dejar una pregunta en blanco otra vez (extra útil; guarda `opcion_elegida = NULL`).
4. **Descartar** un intento pendiente: `POST /examen/<id>/descartar` (ruta extra exigida por "ofrecer continuar o descartar"). Plantilla extra `examen/pendiente.html`.
5. **Revisión desde el dashboard**: `GET /dashboard/revision/<id>` reutiliza `construir_revision()` y el parcial `templates/examen/_revision.html` (archivo extra), igual que la página de resultado.
6. **Enunciado completo** en `.enunciado-pregunta` (pre-wrap + monoespaciada + fondo gris), porque los enunciados mezclan texto y código sin delimitadores.
7. **Al salir de la página** se envía el tiempo de la pregunta actual con `navigator.sendBeacon` (FormData con `csrf_token`); el endpoint acepta JSON o formulario.
8. Rutas extra `/examen/<id>/responder` (AJAX) y `/examen/<id>/tiempo` (re-sincronización), exigidas por la sección 7.2.

## Tarjetas

1. Orden: primero las que su **último** repaso fue "no la sabía", luego las nunca repasadas, al final las que sabía (las más antiguas primero).
2. `GET /estudio/` (índice de temas) y `GET /estudio/falladas` (tarjetas de falladas, usado por `repaso_ligero`) son rutas extra; `POST /estudio/tarjeta` guarda `RepasoTarjeta` por AJAX.
3. El cronómetro de sesión (`sesion.js`) guarda su inicio en `localStorage` para no reiniciarse al recargar; la especificación solo exige persistencia en servidor para los intentos (teórico y práctico).
4. `templates/_sesion_widget.html` (extra) es el recuadro del cronómetro de sesión reutilizado en tarjetas, práctica de caso y defensa.

## Práctica

1. **Tiempo del intento por defecto = `tiempo_sugerido_min` del caso** (180 en los datos); `TIEMPO_PRACTICA_DEFAULT_MIN` (120, placeholder) se ofrece como atajo "usar duración estimada del examen" y como respaldo si un caso no trae tiempo.
2. **Terminar ≠ completar**: "Terminar y autoevaluar" (o la expiración) fija `fecha_fin`/`duracion_segundos` y bloquea la checklist; `completado=True` solo al confirmar la autoevaluación. Ese intento sigue contando como "el único pendiente de práctica".
3. **Puntaje final prellenado** = sugerido redondeado **hacia abajo** a múltiplos de 0.25 (conservador; el campo exige pasos de 0.25). El servidor rechaza con 400 cualquier valor > máximo, negativo o fuera de paso; la nota nunca supera 10.
4. **Semáforo de /practica** sobre la nota del caso (promedio de los 2 últimos válidos, sin ajustar); la nota ajustada se muestra al lado.
5. **Colores de criterio**: verde ≥ 70 %, amarillo ≥ 50 %, rojo < 50 % del máximo. "Qué reforzar" = hasta 3 criterios < 70 % con menor %.
6. **Recursos**: se sirven solo los nombres que existen en `data/recursos/` (lista blanca, sin rutas: imposible `../`), como `text/plain` (el `.js` no se ejecuta en el navegador). Los recursos que son URL (API del caso P4) se muestran como enlace externo.
7. **Pestaña Referencia (solo P2)** con el contenido plegado tras un botón para no "spoilear" antes de intentar el caso.
8. **Defensa**: el simulacro oral baraja (Fisher-Yates) y luego ordena de forma estable por nivel (sin ensayar / no sé → parcial → dominado); 2 min por pregunta y al agotarse muestra la clave y pide autocalificar.
9. Rutas extra: `/practica/<codigo>/iniciar`, `/practica/intento/<id>/{guardar,tiempo,terminar,descartar}`, `/practica/<codigo>/defensa/calificar`. Plantilla extra `practica/pendiente.html`.

## Planificador (servicios/planificador.py)

1. **Función pura** `generar_plan(EntradaPlan) -> ResultadoPlan` (probada con pytest) + capa de BD (`crear_plan`, `recalcular_plan`, `estadisticas_plan`).
2. **Fases por fechas fijas** calculadas sobre todo el rango del plan (inicio → examen−1): último día de estudio = solo `repaso_ligero` (≤ 60 min); penúltimo = `simulacro_completo` si caben 120 min (si no, de núcleo) + `defensa` de P2 si caben 25 min (si no, la defensa queda en el repaso ligero, que por definición incluye defensa). "Último tercio" = último tercio de los días de contenido.
3. **Diagnóstico**: `simulacro_nucleo` (30 min) por núcleo no diagnosticado + `intento_practico` por caso sin intento válido, intercalados y colocados "primer día que quepa". Los intentos prácticos son **indivisibles** (cronometrados): si ningún día tiene los minutos sugeridos (180), se agendan con la capacidad del día más largo y se avisa en `advertencias` (el tiempo se puede ajustar al iniciar).
4. **Simulacros**: `simulacro_completo` cada 3 días de estudio (4 si el último tercio tiene más de 9 días), mínimo 2 si hay días; si ningún día cercano tiene 120 min se sustituye por un simulacro del núcleo más débil (con aviso). Un `intento_practico` completo por caso en el último tercio.
5. **Reparto del tiempo flexible** (lo que queda tras diagnóstico, simulacros y repaso final): objetivo global teoría/práctica = `porcentaje_tiempo_practica` sobre la capacidad total; dentro de cada componente, **2/3 cobertura y 1/3 refuerzo** (proporción 50:25 de la sección 10.3). Si la cobertura no cabe, se corta **por orden de prioridad** (lo de menor prioridad queda fuera; del tema en el que se corta se conserva al menos su parte de tarjetas).
6. **Teoría**: por tema `minutos = max(20, múltiplo de 5 de 8 × peso)`, 35 % tarjetas (mín. 10) y 65 % `practica_tema` (mín. 10); `peso` = Σ factor_nivel × factor_núcleo de sus preguntas. Solo cuentan como "faltantes" los temas con dominio < 70 % (coherente con la suficiencia de tiempo del veredicto).
7. **Práctica**: cobertura por rondas (criterio más débil de cada caso, empezando por los casos de mayor prioridad; luego el 2.º más débil…), criterios con % < 70 o sin datos; sesión `practica_caso` de 30 min × puntaje acotada a 45–90 min. `defensa` (25 min) del caso con criterio de defensa (P2) **al principio** de la cobertura práctica (prioridad alta: vale 3 de 10) y de los demás casos tras la 1.ª ronda (media), solo si su dominio de defensa < 70 %. Al rellenar huecos solo se adelantan sesiones de la misma fase (no se programa refuerzo antes de terminar la cobertura).
8. **Refuerzo**: teoría = `fallidas` (30 min) cada 3 repasos de tarjetas (20 min) de temas cubiertos con dominio < 70 %; práctica = nueva ronda de `practica_caso` sobre criterios < 70 % + defensa de P2. Se genera cíclicamente hasta llenar su parte.
9. **Empaquetado**: días en orden; en cada hueco se coloca primero el componente más atrasado respecto a su objetivo; si una sesión no cabe y es divisible (tarjetas) se parte en bloques de 20–50 min (práctica hasta 90) con "(parte N)"; si no, se busca la siguiente que quepa. Sesiones > 50 min muestran "pausa de 10 min cada 50".
10. **Modo intensivo** (< 3 días de estudio): diagnóstico rápido (núcleos sin diagnosticar, N2 primero), falladas, criterio más débil de cada caso, defensa de P2 y tarjetas; el último día solo repaso ligero. Con **un único día**, el repaso ligero se reserva al final de ese mismo día (no hay otro día donde ponerlo).
11. **Recálculo**: conserva `completada`/`omitida` y las sesiones con un intento en curso; borra las pendientes desde hoy y las regenera con los datos actuales. Las **atrasadas** se recolocan primero (misma fila, nueva fecha) en los próximos días con capacidad; si no caben se borran y pasan a `advertencias`. El contenido de cobertura ya completado (tema, criterio, defensa, intentos de simulacro/diagnóstico) no se vuelve a programar; los minutos ya usados hoy cuentan como ocupados.
12. **Cumplimiento** = completadas / (sesiones con fecha < hoy + completadas con fecha ≥ hoy). Sin sesiones vencidas → "sin datos" (C1 no aplica todavía). **Racha** = días consecutivos (hasta hoy o ayer) con al menos una sesión completada.
13. `advertencias` guarda objetos `{"nivel": "danger|warning|info", "texto": ...}`; los `danger` (tiempo insuficiente, modo intensivo) se muestran en rojo.
14. Rutas extra: `/plan/<id>` (ver un plan anterior, con control de pertenencia), `/plan/recalcular`, `/plan/sesion/<id>/{iniciar,omitir,terminar}`. Plantilla extra `plan/_sesion.html` (macro de fila de sesión).
15. **Validación del formulario**: examen > hoy y > inicio, horas 0–12 en pasos de 0.5 con al menos un día > 0, pesos que suman 100.
16. **Consecuencia de las constantes de la especificación**: cubrir toda la teoría a 8 min/punto de peso requiere ~27 h, y la práctica otro tanto; con pocas horas el plan lo indica como "Tiempo insuficiente" (estimación inicial conservadora que baja tras el diagnóstico, porque los temas ≥ 70 % dejan de contar como faltantes).

## Veredicto (servicios/veredicto.py)

1. **Función pura** `evaluar(DatosVeredicto) -> Veredicto` (probada con pytest).
2. **T6** exige al menos 3 simulacros válidos ("regresión de las últimas 3–5 notas"); con menos, no se cumple. Por eso un único 10/10 nunca da APTO.
3. **C1** sin plan activo o sin sesiones vencidas = "no aplica" (no bloquea el APTO); el índice redistribuye su 5 % proporcionalmente.
4. **P4** usa el caso que tiene criterio de defensa (P2).
5. **Nota práctica** = promedio simple de la nota de los casos con intento válido; ajustada = máx(0, nota − 0.5), también por caso.
6. **Orden de decisión**: SIN DATOS (falta teoría o algún caso) → NO APTO AÚN (nota final < mínima) → APTO (todo ✓ y sin eslabón débil) → EN RIESGO.
7. **Proyección**: regresión lineal por fechas de cada componente (≥ 3 puntos cada uno) evaluada en la fecha del examen, práctica ajustada, limitada a 0–10. Sin fecha de examen se pide crear el plan.
8. **Suficiencia**: Suficiente si disponible ≥ 1.2 × necesario; Justo si ≥ necesario; si no, Insuficiente. "Necesario" = temas con dominio < 70 % + criterios < 70 % + intentos y simulacros válidos que faltan + 2 sesiones de defensa de P2 si su dominio < 70 %.
9. **Foto diaria**: se guarda/actualiza al abrir el veredicto, el plan o el dashboard (una fila por usuario y día).

## Interfaz y aplicación

1. **Bootstrap Icons** (CDN jsDelivr) además de Bootstrap 5 y Chart.js, para los iconos de teoría/práctica pedidos en el calendario.
2. **403 personalizado** (`templates/403.html`, extra) además de 404/500; 405 redirige con un mensaje. Las peticiones AJAX reciben los errores en JSON.
3. **Logout** acepta POST (botón con CSRF en la navbar) y GET (un enlace directo también cierra sesión).
4. En las plantillas, el módulo `config.py` se expone como `cfg` (Flask ya usa el nombre `config` para `app.config`).
5. **Logging**: `logs/errores.log` (ERROR, rotativo 1 MB × 5) y `logs/app.log` (INFO, 1 MB × 3); consola solo WARNING+.
6. **Archivos extra**: `pytest.ini` y la carpeta `tests/` (pruebas pedidas en las secciones 15.9 y 16), `templates/_macros.html` (macros de formularios y barras).
