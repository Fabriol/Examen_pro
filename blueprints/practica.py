"""Módulo de práctica: los 4 casos, intentos cronometrados, autoevaluación y defensa (sección 9).

La app NO ejecuta ni evalúa el código del estudiante: da el enunciado, la checklist de
verificación, el cronómetro, la autoevaluación por rúbrica y el repaso de defensa.
"""
import logging
import math
from datetime import timedelta
from urllib.parse import urlparse

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

import config
from blueprints import obtener_propio, obtener_sesion_propia
from extensions import db
from models import (NIVELES_DEFENSA, CasoPractico, EvaluacionCriterio, IntentoPractico,
                    RepasoDefensa, ahora)
from servicios import estadisticas
from servicios import practica as srv

bp = Blueprint("practica", __name__, url_prefix="/practica")
log = logging.getLogger(__name__)

# Solo estos casos muestran la pestaña "Referencia" (sección 9.1).
REFERENCIAS = {
    "P2": [
        ("PostgreSQL", "referencia_n2_postgres.sql", "sql"),
        ("MongoDB (mongosh)", "referencia_n2_mongo.js", "javascript"),
    ],
}
NOTA_REFERENCIA = (
    "Referencia para estudiar y comparar tras tu intento. La de PostgreSQL fue probada en un "
    "servidor real; la de MongoDB se validó solo con un emulador. Si tu examen usa otro motor, adáptala."
)
MINUTOS_MIN, MINUTOS_MAX = 5, 600


def _caso_por_codigo(codigo):
    caso = CasoPractico.query.filter_by(codigo=(codigo or "").upper()).first()
    if caso is None:
        abort(404)
    return caso


def _archivos_recursos():
    if not config.RECURSOS_DIR.is_dir():
        return set()
    return {p.name for p in config.RECURSOS_DIR.iterdir() if p.is_file()}


def _recursos_de(caso):
    """Separa los recursos del caso en archivos locales (servidos por la app) y enlaces externos."""
    locales, externos = [], []
    disponibles = _archivos_recursos()
    for recurso in caso.recursos:
        esquema = urlparse(recurso).scheme
        if esquema in ("http", "https"):
            externos.append(recurso)
        else:
            nombre = recurso.replace("\\", "/").rsplit("/", 1)[-1]
            if nombre in disponibles:
                locales.append(nombre)
    return locales, externos


def _leer_referencia(nombre):
    with open(config.RECURSOS_DIR / nombre, encoding="utf-8") as archivo:
        return archivo.read()


def _nota_minima():
    return estadisticas.parametros_examen(current_user)["nota_minima"]


# ---------------------------------------------------------------------------
# Vistas de casos
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
def index():
    nota_minima = _nota_minima()
    return render_template(
        "practica/index.html",
        filas=srv.resumen_casos(current_user.id, nota_minima),
        pendiente=srv.intento_pendiente(current_user.id),
        nota_minima=nota_minima,
        margen=config.MARGEN_SEGURIDAD,
        nombres_nucleo=config.NOMBRES_NUCLEO,
    )


@bp.route("/<codigo>")
@login_required
def caso(codigo):
    caso = _caso_por_codigo(codigo)
    sesion = obtener_sesion_propia(request.args.get("sesion"))
    criterio_objetivo = request.args.get("criterio") or (sesion.criterio_id if sesion else None)
    locales, externos = _recursos_de(caso)
    referencias = [
        {"titulo": titulo, "archivo": nombre, "lenguaje": lenguaje, "contenido": _leer_referencia(nombre)}
        for titulo, nombre, lenguaje in REFERENCIAS.get(caso.codigo, [])
        if nombre in _archivos_recursos()
    ]
    intentos = (
        IntentoPractico.query.filter_by(usuario_id=current_user.id, caso_id=caso.id)
        .options(selectinload(IntentoPractico.evaluaciones))
        .order_by(IntentoPractico.fecha_inicio.desc())
        .all()
    )
    minutos_inicio = caso.tiempo_sugerido_min or config.TIEMPO_PRACTICA_DEFAULT_MIN
    if sesion and sesion.tipo == "intento_practico":
        minutos_inicio = sesion.minutos_planificados
    return render_template(
        "practica/caso.html",
        caso=caso,
        sesion=sesion,
        criterio_objetivo=criterio_objetivo,
        locales=locales,
        externos=externos,
        referencias=referencias,
        nota_referencia=NOTA_REFERENCIA,
        intentos=intentos,
        es_valido=srv.es_intento_valido,
        pendiente=srv.intento_pendiente(current_user.id),
        minutos_inicio=minutos_inicio,
        minutos_examen=config.TIEMPO_PRACTICA_DEFAULT_MIN,
        nombres_nucleo=config.NOMBRES_NUCLEO,
        aviso=srv.AVISO_HONESTIDAD,
    )


@bp.route("/recurso/<path:nombre>")
@login_required
def recurso(nombre):
    """Sirve SOLO archivos existentes de data/recursos/ (lista blanca: sin path traversal)."""
    if nombre not in _archivos_recursos():
        abort(404)
    return send_from_directory(
        config.RECURSOS_DIR,
        nombre,
        mimetype="text/plain",
        as_attachment=request.args.get("descargar") == "1",
    )


# ---------------------------------------------------------------------------
# Intento cronometrado
# ---------------------------------------------------------------------------
@bp.route("/<codigo>/iniciar", methods=["POST"])
@login_required
def iniciar(codigo):
    caso = _caso_por_codigo(codigo)
    pendiente = srv.intento_pendiente(current_user.id)
    if pendiente:
        return render_template("practica/pendiente.html", intento=pendiente,
                               restante=pendiente.segundos_restantes())
    try:
        minutos = int(request.form.get("minutos", caso.tiempo_sugerido_min))
    except (TypeError, ValueError):
        minutos = -1
    if not MINUTOS_MIN <= minutos <= MINUTOS_MAX:
        flash(f"El tiempo debe estar entre {MINUTOS_MIN} y {MINUTOS_MAX} minutos.", "danger")
        return redirect(url_for("practica.caso", codigo=caso.codigo))
    sesion = obtener_sesion_propia(request.form.get("sesion"))
    intento = IntentoPractico(
        usuario_id=current_user.id,
        caso_id=caso.id,
        fecha_inicio=ahora(),
        tiempo_limite_segundos=minutos * 60,
        tareas_ok=[],
        notas="",
        sesion_id=sesion.id if sesion and sesion.estado == "pendiente" and sesion.tipo == "intento_practico" else None,
    )
    db.session.add(intento)
    db.session.commit()
    return redirect(url_for("practica.intento", intento_id=intento.id))


def terminar_intento(intento, momento=None):
    """Detiene el cronómetro (por botón o por expiración). No completa: falta autoevaluar."""
    if intento.terminado:
        return
    momento = momento or ahora()
    limite = intento.fecha_inicio + timedelta(seconds=intento.tiempo_limite_segundos)
    intento.fecha_fin = min(momento, limite)
    intento.duracion_segundos = min(intento.segundos_transcurridos(momento), intento.tiempo_limite_segundos)
    db.session.commit()


@bp.route("/intento/<int:intento_id>")
@login_required
def intento(intento_id):
    intento = obtener_propio(IntentoPractico, intento_id)
    if intento.completado:
        return redirect(url_for("practica.resultado", intento_id=intento.id))
    if intento.terminado:
        return redirect(url_for("practica.autoevaluar", intento_id=intento.id))
    if intento.segundos_restantes() <= 0:
        terminar_intento(intento)
        flash("El tiempo se agotó: el intento terminó automáticamente. Ahora autoevalúate.", "warning")
        return redirect(url_for("practica.autoevaluar", intento_id=intento.id))
    caso = intento.caso
    datos = {
        "intentoId": intento.id,
        "restante": intento.segundos_restantes(),
        "limite": intento.tiempo_limite_segundos,
        "resync": config.INTERVALO_RESYNC_SEGUNDOS,
        "criterios": [
            {"id": c["id"], "puntaje": c["puntaje"], "tareas": [t["id"] for t in c["tareas"]]}
            for c in caso.rubrica
        ],
        "urls": {
            "guardar": url_for("practica.guardar", intento_id=intento.id),
            "tiempo": url_for("practica.tiempo", intento_id=intento.id),
            "autoevaluar": url_for("practica.autoevaluar", intento_id=intento.id),
        },
    }
    return render_template(
        "practica/intento.html",
        intento=intento,
        caso=caso,
        datos=datos,
        tareas_ok=set(intento.tareas_ok or []),
        aviso=srv.AVISO_HONESTIDAD,
    )


@bp.route("/intento/<int:intento_id>/guardar", methods=["POST"])
@login_required
def guardar(intento_id):
    intento = obtener_propio(IntentoPractico, intento_id)
    if intento.completado or intento.terminado:
        return jsonify(ok=False, terminado=True,
                       redirect=url_for("practica.autoevaluar", intento_id=intento.id)), 409
    if intento.segundos_transcurridos() > intento.tiempo_limite_segundos + config.GRACIA_SEGUNDOS:
        return jsonify(ok=False, expirado=True,
                       redirect=url_for("practica.autoevaluar", intento_id=intento.id)), 409
    datos = request.get_json(silent=True) or {}
    validas = set(intento.caso.ids_tareas)
    if "tareas_ok" in datos:
        tareas = datos.get("tareas_ok")
        if not isinstance(tareas, list) or any(t not in validas for t in tareas):
            return jsonify(ok=False, error="Tareas no válidas."), 400
        orden = {t: i for i, t in enumerate(intento.caso.ids_tareas)}
        intento.tareas_ok = sorted(set(tareas), key=orden.get)
    if "notas" in datos:
        notas = datos.get("notas")
        if not isinstance(notas, str):
            return jsonify(ok=False, error="Notas no válidas."), 400
        intento.notas = notas[:20000]
    db.session.commit()
    return jsonify(ok=True, restante=intento.segundos_restantes())


@bp.route("/intento/<int:intento_id>/tiempo")
@login_required
def tiempo(intento_id):
    intento = obtener_propio(IntentoPractico, intento_id)
    terminado = intento.completado or intento.terminado
    return jsonify(
        restante=0 if terminado else intento.segundos_restantes(),
        limite=intento.tiempo_limite_segundos,
        terminado=terminado,
    )


@bp.route("/intento/<int:intento_id>/terminar", methods=["GET", "POST"])
@login_required
def terminar(intento_id):
    intento = obtener_propio(IntentoPractico, intento_id)
    if request.method == "GET":
        return redirect(url_for("practica.intento", intento_id=intento.id))
    if not intento.completado and not intento.terminado:
        terminar_intento(intento)
    return redirect(url_for("practica.autoevaluar", intento_id=intento.id))


@bp.route("/intento/<int:intento_id>/descartar", methods=["POST"])
@login_required
def descartar(intento_id):
    intento = obtener_propio(IntentoPractico, intento_id)
    codigo = intento.caso.codigo
    if intento.completado:
        flash("Un intento completado no se puede descartar.", "warning")
        return redirect(url_for("practica.resultado", intento_id=intento.id))
    db.session.delete(intento)
    db.session.commit()
    flash("Intento práctico descartado.", "info")
    return redirect(url_for("practica.caso", codigo=codigo))


# ---------------------------------------------------------------------------
# Autoevaluación y resultado
# ---------------------------------------------------------------------------
@bp.route("/intento/<int:intento_id>/autoevaluar", methods=["GET", "POST"])
@login_required
def autoevaluar(intento_id):
    intento = obtener_propio(IntentoPractico, intento_id)
    if intento.completado:
        return redirect(url_for("practica.resultado", intento_id=intento.id))
    if not intento.terminado:
        if intento.segundos_restantes() > 0:
            flash("Primero termina el intento para autoevaluarte.", "info")
            return redirect(url_for("practica.intento", intento_id=intento.id))
        terminar_intento(intento)

    caso = intento.caso
    tareas_ok = set(intento.tareas_ok or [])
    filas, errores = [], {}
    for criterio in caso.rubrica:
        sugerido = srv.puntaje_sugerido(criterio, tareas_ok)
        valor = srv.redondear_a_paso(sugerido)
        comentario = ""
        if request.method == "POST":
            texto = request.form.get(f"puntaje_{criterio['id']}")
            comentario = (request.form.get(f"comentario_{criterio['id']}") or "").strip()[:2000]
            valor, error = srv.validar_puntaje(texto, criterio["puntaje"])
            if error:
                errores[criterio["id"]] = error
                valor = texto
        filas.append({
            "criterio": criterio,
            "sugerido": sugerido,
            "valor": valor,
            "comentario": comentario,
            "hechas": sum(1 for t in criterio["tareas"] if t["id"] in tareas_ok),
        })

    if request.method == "POST" and not errores:
        try:
            for fila in filas:
                c = fila["criterio"]
                db.session.add(EvaluacionCriterio(
                    intento_practico_id=intento.id,
                    criterio_id=c["id"],
                    puntaje_maximo=float(c["puntaje"]),
                    puntaje_sugerido=fila["sugerido"],
                    puntaje_final=float(fila["valor"]),
                    comentario=fila["comentario"],
                ))
            db.session.flush()
            db.session.refresh(intento)
            momento = ahora()
            intento.nota_autoevaluada = srv.nota_de_evaluaciones(intento.evaluaciones)
            intento.completado = True
            sesion = intento.sesion
            if sesion is not None and sesion.estado == "pendiente":
                sesion.estado = "completada"
                sesion.completada_en = momento
                sesion.minutos_reales = max(1, math.ceil((intento.duracion_segundos or 0) / 60))
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("Error al guardar la autoevaluación del intento práctico %s", intento.id)
            abort(500)
        try:
            from servicios.planificador import recalcular_plan_usuario
            recalcular_plan_usuario(current_user)
        except Exception:
            db.session.rollback()
            log.exception("Fallo al recalcular el plan tras el intento práctico %s", intento.id)
        flash("Autoevaluación guardada.", "success")
        return redirect(url_for("practica.resultado", intento_id=intento.id))

    if errores:
        flash("Revisa los puntajes marcados en rojo.", "danger")
    return render_template(
        "practica/autoevaluar.html",
        intento=intento,
        caso=caso,
        filas=filas,
        errores=errores,
        tareas_ok=tareas_ok,
        aviso=srv.AVISO_HONESTIDAD,
    ), (400 if errores else 200)


@bp.route("/intento/<int:intento_id>/resultado")
@login_required
def resultado(intento_id):
    intento = obtener_propio(IntentoPractico, intento_id, opciones=(selectinload(IntentoPractico.evaluaciones),))
    if not intento.completado:
        return redirect(url_for("practica.intento", intento_id=intento.id))
    caso = intento.caso
    evaluaciones = {ev.criterio_id: ev for ev in intento.evaluaciones}
    desglose = []
    for criterio in caso.rubrica:
        ev = evaluaciones.get(criterio["id"])
        pct = srv.pct_criterio(ev) if ev else 0.0
        desglose.append({"criterio": criterio, "ev": ev, "pct": pct, "color": srv.color_pct(pct)})
    reforzar = sorted((d for d in desglose if d["pct"] < 70), key=lambda d: (d["pct"], -d["criterio"]["puntaje"]))[:3]
    nota_minima = _nota_minima()
    return render_template(
        "practica/resultado.html",
        intento=intento,
        caso=caso,
        desglose=desglose,
        reforzar=reforzar,
        valido=srv.es_intento_valido(intento, caso),
        nota_ajustada=srv.nota_ajustada(intento.nota_autoevaluada),
        semaforo=srv.semaforo(intento.nota_autoevaluada, nota_minima),
        nota_minima=nota_minima,
    )


# ---------------------------------------------------------------------------
# Defensa
# ---------------------------------------------------------------------------
@bp.route("/<codigo>/defensa")
@login_required
def defensa(codigo):
    caso = _caso_por_codigo(codigo)
    sesion = obtener_sesion_propia(request.args.get("sesion"))
    niveles = srv.ultimos_niveles_defensa(current_user.id, caso)
    tarjetas = [
        {"indice": i, "pregunta": d["pregunta"], "clave": d["clave"], "nivel": niveles.get(i)}
        for i, d in enumerate(caso.defensa)
    ]
    datos = {
        "caso": caso.codigo,
        "tarjetas": tarjetas,
        "segundosOral": config.SEGUNDOS_DEFENSA_ORAL,
        "urlCalificar": url_for("practica.calificar_defensa", codigo=caso.codigo),
    }
    return render_template(
        "practica/defensa.html",
        caso=caso,
        sesion=sesion,
        datos=datos,
        dominio=srv.dominio_defensa(current_user.id, caso, niveles),
        umbral=config.UMBRAL_DEFENSA,
    )


@bp.route("/<codigo>/defensa/calificar", methods=["POST"])
@login_required
def calificar_defensa(codigo):
    caso = _caso_por_codigo(codigo)
    datos = request.get_json(silent=True) or {}
    try:
        indice = int(datos.get("indice"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Pregunta no válida."), 400
    nivel = datos.get("nivel")
    if not 0 <= indice < len(caso.defensa) or nivel not in NIVELES_DEFENSA:
        return jsonify(ok=False, error="Datos no válidos."), 400
    db.session.add(RepasoDefensa(usuario_id=current_user.id, caso_id=caso.id,
                                 indice_pregunta=indice, nivel=nivel))
    db.session.commit()
    return jsonify(ok=True, dominio=srv.dominio_defensa(current_user.id, caso))
