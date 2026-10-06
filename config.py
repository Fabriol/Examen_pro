"""Configuración y constantes editables del Simulador Complexivo.

Las constantes marcadas como PLACEHOLDER no están confirmadas por el
instituto: se muestran en la interfaz con el aviso "confirmar con tu docente"
y el plan de estudio permite sobrescribir las más importantes por usuario.
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DATA_DIR = BASE_DIR / "data"
RECURSOS_DIR = DATA_DIR / "recursos"
LOGS_DIR = BASE_DIR / "logs"

load_dotenv(BASE_DIR / ".env", encoding="utf-8")

# ---------------------------------------------------------------------------
# Sección 11 — Constantes (todas editables)
# ---------------------------------------------------------------------------
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
UMBRAL_CUMPLIMIENTO_PLAN = 80
MIN_POR_PUNTO_PESO      = 8

# ---------------------------------------------------------------------------
# Sección 1 — Datos del examen que NO se conocen (PLACEHOLDER - confirmar)
# ---------------------------------------------------------------------------
FECHA_EXAMEN = None                   # PLACEHOLDER - confirmar ("AAAA-MM-DD"); el plan la pide
MOTOR_BD_N2 = "PostgreSQL (el más probable: el backup usa SERIAL)"  # PLACEHOLDER - confirmar
FORMATO_DEFENSA = "Oral, sobre tu solución del caso N2 (vale 3 de 10 puntos)"  # PLACEHOLDER - confirmar

# ---------------------------------------------------------------------------
# Constantes auxiliares (justificadas en DECISIONES.md)
# ---------------------------------------------------------------------------
TOTAL_PREGUNTAS_BANCO = 120
SEGUNDOS_POR_PREGUNTA_DEFAULT = 60    # 1 min/pregunta (sección 7.1)
SEGUNDOS_POR_PREGUNTA_MIN = 10
SEGUNDOS_POR_PREGUNTA_MAX = 600
INTERVALO_RESYNC_SEGUNDOS = 20        # re-sincronización del temporizador
GRACIA_SEGUNDOS = 5                   # tolerancia de red al guardar al borde del tiempo
SEGUNDOS_DEFENSA_ORAL = 120           # 2 min por pregunta en el simulacro oral

FACTOR_NIVEL = {"facil": 1.0, "medio": 1.5, "dificil": 2.0}
FACTOR_NUCLEO = {1: 1.0, 2: 1.25, 3: 1.0, 4: 1.0}
MIN_POR_PUNTO_CRITERIO = 30           # minutos de práctica por punto de rúbrica (45–90 por sesión)
DURACION_SIMULACRO_NUCLEO_MIN = 30
DURACION_SIMULACRO_COMPLETO_MIN = 120
DURACION_DEFENSA_MIN = 25
DURACION_REPASO_LIGERO_MAX_MIN = 60
DURACION_FALLIDAS_MIN = 30
DURACION_REPASO_TARJETAS_MIN = 20

NOMBRES_NUCLEO = {
    1: "Spring Boot / MVC / JPA",
    2: "Bases de Datos",
    3: "Angular / Firebase",
    4: "Móvil / APIs / Firebase",
}
NOMBRES_NIVEL = {"facil": "Fácil", "medio": "Medio", "dificil": "Difícil"}


SECRET_KEY_POR_DEFECTO = "dev-inseguro-cambia-esta-clave"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or SECRET_KEY_POR_DEFECTO
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + (INSTANCE_DIR / "simulador.db").as_posix()
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Un examen puede durar horas: el token CSRF no caduca por tiempo (sigue ligado a la sesión).
    WTF_CSRF_TIME_LIMIT = None
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    AUTO_SEED = True
    TESTING = False


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "clave-de-pruebas"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
