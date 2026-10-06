"""Simulador Complexivo — app factory PURO.

No existe `app = create_app()` a nivel de módulo (evita efectos secundarios al importar,
como sembrar dos veces). `flask run` encuentra `create_app` automáticamente.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        try:
            _flujo.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

from datetime import date, datetime  # noqa: E402

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for  # noqa: E402
from flask_login import current_user  # noqa: E402
from flask_wtf.csrf import CSRFError  # noqa: E402

import config  # noqa: E402
from extensions import csrf, db, login_manager  # noqa: E402

log = logging.getLogger(__name__)

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
DIAS_CORTOS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def create_app(config_objeto=None):
    app = Flask(__name__, instance_path=str(config.INSTANCE_DIR))
    app.config.from_object(config_objeto or config.Config)
    config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _configurar_logging(app)
    if app.config["SECRET_KEY"] == config.SECRET_KEY_POR_DEFECTO and not app.config.get("TESTING"):
        log.warning("SECRET_KEY por defecto: define SECRET_KEY en .env antes de usar la app en red.")

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    import models  # noqa: F401  (registra los modelos antes de create_all)
    from blueprints import auth, dashboard, estudio, examen, plan, practica
    for modulo in (auth, examen, estudio, practica, plan, dashboard):
        app.register_blueprint(modulo.bp)

    from seed import comando_seed
    app.cli.add_command(comando_seed)

    _registrar_filtros(app)
    _registrar_contexto(app)
    _registrar_errores(app)

    @app.route("/")
    def inicio():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    with app.app_context():
        db.create_all()
        _auto_seed(app)
    return app


def _auto_seed(app):
    """Siembra automáticamente una sola vez: solo si la tabla de preguntas está vacía."""
    from models import Pregunta
    from seed import mensaje_resultado, sembrar

    if not app.config.get("AUTO_SEED") or Pregunta.query.first() is not None:
        return
    try:
        resumen = sembrar()
        log.info("Auto-seed: %s", mensaje_resultado(resumen))
    except Exception:
        log.exception("Falló el auto-seed; ejecuta 'flask seed' manualmente.")


def _configurar_logging(app):
    raiz = logging.getLogger()
    if getattr(raiz, "_simulador_configurado", False):
        return
    formato = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    errores = RotatingFileHandler(config.LOGS_DIR / "errores.log", maxBytes=1_000_000, backupCount=5,
                                  encoding="utf-8")
    errores.setLevel(logging.ERROR)
    errores.setFormatter(formato)
    general = RotatingFileHandler(config.LOGS_DIR / "app.log", maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    general.setLevel(logging.INFO)
    general.setFormatter(formato)
    consola = logging.StreamHandler(sys.stderr)
    consola.setLevel(logging.WARNING)
    consola.setFormatter(formato)
    for manejador in (errores, general, consola):
        raiz.addHandler(manejador)
    raiz.setLevel(logging.INFO)
    raiz._simulador_configurado = True


# ---------------------------------------------------------------------------
# Filtros y contexto de plantillas
# ---------------------------------------------------------------------------
def mmss(segundos):
    if segundos is None:
        return "—"
    segundos = max(0, int(segundos))
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{seg:02d}"
    return f"{minutos:02d}:{seg:02d}"


def horas_legibles(segundos):
    minutos = int(segundos or 0) // 60
    horas, resto = divmod(minutos, 60)
    return f"{horas} h {resto:02d} min" if horas else f"{resto} min"


def fecha_hora(valor):
    return valor.strftime("%d/%m/%Y %H:%M") if valor else "—"


def fecha_corta(valor):
    return valor.strftime("%d/%m/%Y") if valor else "—"


def fecha_larga(valor):
    if not valor:
        return "—"
    if isinstance(valor, datetime):
        valor = valor.date()
    return f"{DIAS[valor.weekday()]} {valor.day} de {MESES[valor.month - 1]} de {valor.year}"


def dia_semana_corto(valor):
    return DIAS_CORTOS[valor.weekday()]


def _registrar_filtros(app):
    app.jinja_env.filters.update(
        mmss=mmss,
        horas_legibles=horas_legibles,
        fecha_hora=fecha_hora,
        fecha_corta=fecha_corta,
        fecha_larga=fecha_larga,
        dia_semana_corto=dia_semana_corto,
        nivel_legible=lambda n: config.NOMBRES_NIVEL.get(n, n),
    )


def _registrar_contexto(app):
    from blueprints.plan import ETIQUETAS_FASE, ETIQUETAS_TIPO

    @app.context_processor
    def contexto_global():
        return {
            "cfg": config,
            "etiquetas_fase": ETIQUETAS_FASE,
            "etiquetas_tipo": ETIQUETAS_TIPO,
            "anio_actual": date.today().year,
        }


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
def _quiere_json():
    return request.is_json or (
        request.accept_mimetypes.best == "application/json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def _registrar_errores(app):
    @app.errorhandler(403)
    def prohibido(error):
        if _quiere_json():
            return jsonify(ok=False, error="No tienes permiso para acceder a este recurso."), 403
        return render_template("403.html"), 403

    @app.errorhandler(404)
    def no_encontrado(error):
        if _quiere_json():
            return jsonify(ok=False, error="Recurso no encontrado."), 404
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def metodo_no_permitido(error):
        if _quiere_json():
            return jsonify(ok=False, error="Método no permitido."), 405
        flash("Esa acción no está disponible de esa forma.", "warning")
        return redirect(url_for("inicio"))

    @app.errorhandler(500)
    def error_interno(error):
        db.session.rollback()
        original = getattr(error, "original_exception", None)
        if original is not None:
            log.error("Error 500 en %s", request.path, exc_info=original)
        if _quiere_json():
            return jsonify(ok=False, error="Error interno. Inténtalo de nuevo."), 500
        try:
            return render_template("500.html"), 500
        except Exception:
            return "Error interno del servidor. Revisa logs/errores.log.", 500

    @app.errorhandler(CSRFError)
    def csrf_invalido(error):
        if _quiere_json():
            return jsonify(ok=False, error="Token de seguridad inválido: recarga la página."), 400
        flash("El formulario caducó o no es válido. Vuelve a intentarlo.", "warning")
        destino = request.referrer if request.referrer and request.referrer.startswith(request.host_url) else "/"
        return redirect(destino)


if __name__ == "__main__":
    create_app().run(debug=False)
