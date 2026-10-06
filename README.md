# Simulador Complexivo — Desarrollo de Software (ITSQMET)

Plataforma de estudio para el Examen Complexivo:

- **Teoría:** simulacros con las 120 preguntas del banco (4 núcleos × 3 niveles × 10), por núcleo, nivel, tema o solo tus falladas, con temporizador persistente y revisión.
- **Práctica:** los 4 casos prácticos (P1 VetCare, P2 EduTech, P3 Reserva de mesas, P4 Playlists), cada uno con enunciado, rúbrica, checklist de verificación, cronómetro, autoevaluación por criterio y repaso de la defensa.
- **Plan de estudio** con tiempos (diagnóstico, cobertura, refuerzo, simulacros y repaso final) que se recalcula tras cada intento.
- **Veredicto de aptitud** orientativo y conservador, con índice de preparación.

> La app **no ejecuta ni evalúa tu código**: la práctica se hace en tu propio IDE.

## Requisitos

- Windows 10/11 (también funciona en Linux/macOS)
- Python 3.11 o superior (probado con 3.14)

## Instalación y arranque (Windows)

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
flask seed
flask run
```

Abre <http://127.0.0.1:5000>, crea una cuenta y empieza por **Plan de estudio → Crear mi plan**.

- `flask seed` carga las 120 preguntas y los 4 casos desde `data/` y valida los conteos. Es idempotente: ejecutarlo varias veces no duplica nada. Si la BD está vacía, la app también siembra sola al arrancar; por eso `flask seed` puede mostrar "Nuevas preguntas: 0" junto al ✔ de validación.
- La base de datos entregada (`instance/simulador.db`) viene limpia: solo las 120 preguntas y los 4 casos, sin usuarios, intentos ni planes.
- Opcional: copia `.env.example` como `.env` y define una `SECRET_KEY` propia.
- La base de datos es SQLite en `instance/simulador.db`. Puedes usar otra con la variable `DATABASE_URL`.

## Pruebas

```bat
venv\Scripts\activate
python -m pytest
```

Incluye pruebas del planificador, del veredicto y de los cálculos de práctica, además de pruebas de aceptación de extremo a extremo.

## Datos por confirmar con tu docente

Estos valores son **provisionales** y se editan en `config.py` o, por usuario, al crear el plan:

| Dato | Valor provisional |
|---|---|
| Nota mínima de aprobación | 7.0 |
| Peso teoría / práctica | 50 % / 50 % |
| Duración del examen práctico | 120 min por caso |
| Fecha del examen | la defines en tu plan |
| Motor de BD del caso N2 | PostgreSQL (lo más probable) |
| Formato de la defensa oral | oral sobre el caso N2 (3 de 10 puntos) |

La página **Plan de estudio → Puntos por confirmar con tu docente** reúne todos los datos pendientes, incluidas las ambigüedades de los PDF.

## Estructura

```
app.py  config.py  extensions.py  models.py  seed.py
servicios/   estadisticas · practica · planificador · veredicto
blueprints/  auth · examen · estudio · practica · plan · dashboard
templates/   base, 403/404/500 y una carpeta por módulo
static/      css/estilos.css · js/{examen,sesion,practica}.js
data/        preguntas.json · casos_practicos.json · recursos/  (entregados, no se modifican)
tests/       pytest
logs/        errores.log · app.log (rotativos)
```

Las decisiones tomadas donde la especificación no era explícita están en `DECISIONES.md`.
