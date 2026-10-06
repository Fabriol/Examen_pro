"""Simulacro teórico: configurar, rendir (AJAX), finalizar y revisar (sección 7)."""
import logging
import math
from datetime import timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import config
from blueprints import obtener_propio, obtener_sesion_propia
from extensions import db
from models import MODOS_EXAMEN, NIVELES, Intento, Pregunta, Respuesta, ahora
from servicios import estadisticas

bp = Blueprint("examen", __name__, url_prefix="/examen")
log = logging.getLogger(__name__)

ETIQUETAS_MODO = {
    "completo": "Simulacro completo (120)",
    "nucleo": "Por núcleo (30)",
    "nivel": "Por nivel (40)",
    "tema": "Por tema",
    "fallidas": "Solo mis falladas",
}


def _intento_pendiente():
    return (
        Intento.query.filter_by(usuario_id=current_user.id, completado=False)
        .order_by(Intento.fecha_inicio.desc())
        .first()
    )


def describir_intento(intento, temas=None):
    """Texto legible del modo y filtro de un intento."""
    if intento.modo == "completo":
        return "Simulacro completo"
    if intento.modo == "nucleo":
        return f"Núcleo {intento.filtro} · {config.NOMBRES_NUCLEO.get(int(intento.filtro), '')}"
    if intento.modo == "nivel":
        return f"Nivel {config.NOMBRES_NIVEL.get(intento.filtro, intento.filtro)}"
    if intento.modo == "tema":
        if temas is None:
            p = Pregunta.query.filter_by(tema_slug=intento.filtro).first()
            nombre = p.tema if p else intento.filtro
        else:
            nombre = temas.get(intento.filtro, intento.filtro)
        return f"Tema: {nombre}"
    return "Preguntas falladas"


def _temas_por_nucleo():
    filas = (
        db.session.query(Pregunta.nucleo, Pregunta.tema_slug, Pregunta.tema)
        .distinct()
        .order_by(Pregunta.nucleo, Pregunta.tema)
        .all()
    )
    agrupados = {1: [], 2: [], 3: [], 4: []}
    for nucleo, slug, tema in filas:
        agrupados[nucleo].append((slug, tema))
    return agrupados


# ---------------------------------------------------------------------------
# 7.1 Configurar
# ---------------------------------------------------------------------------
@bp.route("/configurar", methods=["GET", "POST"])
@login_required
def configurar():
    pendiente = _intento_pendiente()
    if pendiente:
        return render_template(
            "examen/pendiente.html",
            intento=pendiente,
            descripcion=describir_intento(pendiente),
            restante=pendiente.segundos_restantes(),
        )

    fuente = request.form if request.method == "POST" else request.args
    sesion = obtener_sesion_propia(fuente.get("sesion"))
    valores = {
        "modo": fuente.get("modo", "completo"),
        "nucleo": fuente.get("nucleo", "1"),
        "nivel": fuente.get("nivel", "facil"),
        "tema": fuente.get("tema", ""),
        "segundos": fuente.get("segundos_por_pregunta", str(config.SEGUNDOS_POR_PREGUNTA_DEFAULT)),
        "aleatorio": ("aleatorio" in fuente) if request.method == "POST" else True,
        "barajar": ("barajar" in fuente) if request.method == "POST" else True,
    }
    if valores["modo"] not in MODOS_EXAMEN:
        valores["modo"] = "completo"
    temas = _temas_por_nucleo()
    slugs_validos = {slug for lista in temas.values() for slug, _ in lista}
    resumen = estadisticas.resumen_teoria(current_user.id)
    n_falladas = len(resumen.falladas_ids)

    if request.method == "POST":
        errores = []
        modo = valores["modo"]
        filtro = None
        if modo == "nucleo":
            filtro = valores["nucleo"] if valores["nucleo"] in ("1", "2", "3", "4") else None
            if filtro is None:
                errores.append("Elige un núcleo válido.")
        elif modo == "nivel":
            filtro = valores["nivel"] if valores["nivel"] in NIVELES else None
            if filtro is None:
                errores.append("Elige un nivel válido.")
        elif modo == "tema":
            filtro = valores["tema"] if valores["tema"] in slugs_validos else None
            if filtro is None:
                errores.append("Elige un tema válido.")
        try:
            segundos = int(valores["segundos"])
        except (TypeError, ValueError):
            segundos = -1
        if not config.SEGUNDOS_POR_PREGUNTA_MIN <= segundos <= config.SEGUNDOS_POR_PREGUNTA_MAX:
            errores.append(
                f"El tiempo por pregunta debe estar entre {config.SEGUNDOS_POR_PREGUNTA_MIN} "
                f"y {config.SEGUNDOS_POR_PREGUNTA_MAX} segundos."
            )
        if not errores:
            ids = estadisticas.preguntas_para_modo(current_user.id, modo, filtro)
            if modo == "fallidas" and not ids:
                flash("¡No tienes preguntas falladas! No se creó ningún intento.", "info")
                return redirect(url_for("examen.configurar", sesion=sesion.id if sesion else None))
            if not ids:
                errores.append("No hay preguntas para esa selección.")
        if errores:
            for error in errores:
                flash(error, "danger")
        else:
            orden, mapeo = estadisticas.generar_orden_y_mapeo(
                ids, aleatorio=valores["aleatorio"], barajar=valores["barajar"]
            )
            intento = Intento(
                usuario_id=current_user.id,
                fecha_inicio=ahora(),
                modo=modo,
                filtro=filtro,
                total_preguntas=len(orden),
                tiempo_limite_segundos=segundos * len(orden),
                orden_preguntas=orden,
                mapeo_opciones=mapeo,
                sesion_id=sesion.id if sesion and sesion.estado == "pendiente" else None,
            )
            db.session.add(intento)
            db.session.commit()
            return redirect(url_for("examen.rendir", intento_id=intento.id))

    return render_template(
        "examen/configurar.html",
        valores=valores,
        temas=temas,
        n_falladas=n_falladas,
        sesion=sesion,
        etiquetas=ETIQUETAS_MODO,
        nombres_nucleo=config.NOMBRES_NUCLEO,
        nombres_nivel=config.NOMBRES_NIVEL,
    )


@bp.route("/<int:intento_id>/descartar", methods=["POST"])
@login_required
def descartar(intento_id):
    intento = obtener_propio(Intento, intento_id)
    if intento.completado:
        flash("Un intento completado no se puede descartar.", "warning")
        return redirect(url_for("examen.resultado", intento_id=intento.id))
    db.session.delete(intento)
    db.session.commit()
    flash("Intento descartado.", "info")
    return redirect(url_for("examen.configurar"))


# ---------------------------------------------------------------------------
# 7.2 Rendir
# ---------------------------------------------------------------------------
@bp.route("/<int:intento_id>")
@login_required
def rendir(intento_id):
    intento = obtener_propio(Intento, intento_id)
    if intento.completado:
        return redirect(url_for("examen.resultado", intento_id=intento.id))
    if intento.segundos_restantes() <= 0:
        _finalizar_seguro(intento)
        flash("El tiempo se agotó: el intento se finalizó automáticamente.", "warning")
        return redirect(url_for("examen.resultado", intento_id=intento.id))

    preguntas = {p.id: p for p in Pregunta.query.filter(Pregunta.id.in_(intento.orden_preguntas)).all()}
    respuestas = {r.pregunta_id: r for r in Respuesta.query.filter_by(intento_id=intento.id).all()}
    items = []
    for pid in intento.orden_preguntas:
        p = preguntas[pid]
        mapeo = estadisticas.mapeo_de(intento, pid)
        r = respuestas.get(pid)
        items.append({
            "id": pid,
            "codigo": p.codigo,
            "tema": p.tema,
            "nivel": config.NOMBRES_NIVEL.get(p.nivel, p.nivel),
            "nucleo": p.nucleo,
            "enunciado": p.enunciado,
            "opciones": [p.opciones[i] for i in mapeo],
            "seleccion": estadisticas.posicion_mostrada(intento, pid, r.opcion_elegida) if r else None,
        })
    datos = {
        "intentoId": intento.id,
        "preguntas": items,
        "restante": intento.segundos_restantes(),
        "limite": intento.tiempo_limite_segundos,
        "resync": config.INTERVALO_RESYNC_SEGUNDOS,
        "urls": {
            "responder": url_for("examen.responder", intento_id=intento.id),
            "tiempo": url_for("examen.tiempo", intento_id=intento.id),
            "resultado": url_for("examen.resultado", intento_id=intento.id),
        },
    }
    return render_template(
        "examen/rendir.html", intento=intento, datos=datos, descripcion=describir_intento(intento)
    )


@bp.route("/<int:intento_id>/responder", methods=["POST"])
@login_required
def responder(intento_id):
    intento = obtener_propio(Intento, intento_id)
    if intento.completado:
        return jsonify(ok=False, completado=True,
                       redirect=url_for("examen.resultado", intento_id=intento.id)), 409
    if intento.segundos_transcurridos() > intento.tiempo_limite_segundos + config.GRACIA_SEGUNDOS:
        return jsonify(ok=False, expirado=True), 409

    datos = request.get_json(silent=True)
    if datos is None:
        datos = request.form.to_dict()
    try:
        pregunta_id = int(datos.get("pregunta_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Pregunta no válida."), 400
    if pregunta_id not in intento.orden_preguntas:
        return jsonify(ok=False, error="La pregunta no pertenece a este intento."), 400
    try:
        segundos = max(0, min(int(datos.get("segundos") or 0), intento.tiempo_limite_segundos))
    except (TypeError, ValueError):
        segundos = 0

    solo_tiempo = datos.get("accion") == "tiempo"
    original = None
    if not solo_tiempo:
        posicion = datos.get("posicion")
        if posicion not in (None, "", "null"):
            try:
                posicion = int(posicion)
            except (TypeError, ValueError):
                return jsonify(ok=False, error="Opción no válida."), 400
            if not 0 <= posicion <= 3:
                return jsonify(ok=False, error="Opción no válida."), 400
            original = estadisticas.mapeo_de(intento, pregunta_id)[posicion]

    for _ in range(2):  # un reintento ante una carrera de doble inserción
        try:
            respuesta = Respuesta.query.filter_by(intento_id=intento.id, pregunta_id=pregunta_id).first()
            if respuesta is None:
                respuesta = Respuesta(intento_id=intento.id, pregunta_id=pregunta_id,
                                      opcion_elegida=None, es_correcta=False, segundos_empleados=0)
                db.session.add(respuesta)
            if not solo_tiempo:
                pregunta = db.session.get(Pregunta, pregunta_id)
                respuesta.opcion_elegida = original
                respuesta.es_correcta = original is not None and original == pregunta.correcta
            respuesta.segundos_empleados = (respuesta.segundos_empleados or 0) + segundos
            db.session.commit()
            break
        except IntegrityError:
            db.session.rollback()
    else:
        return jsonify(ok=False, error="No se pudo guardar; reintenta."), 409

    respondidas = (
        Respuesta.query.filter(Respuesta.intento_id == intento.id, Respuesta.opcion_elegida.isnot(None)).count()
    )
    return jsonify(ok=True, respondidas=respondidas, restante=intento.segundos_restantes())


@bp.route("/<int:intento_id>/tiempo")
@login_required
def tiempo(intento_id):
    intento = obtener_propio(Intento, intento_id)
    return jsonify(
        restante=0 if intento.completado else intento.segundos_restantes(),
        limite=intento.tiempo_limite_segundos,
        completado=intento.completado,
    )


# ---------------------------------------------------------------------------
# 7.3 Finalizar
# ---------------------------------------------------------------------------
def finalizar_intento(intento, momento=None):
    """Calcula nota y duración, completa la sesión del plan y dispara el recálculo.

    Idempotente: un intento ya completado no se recalcula.
    """
    if intento.completado:
        return intento
    momento = momento or ahora()
    respuestas = {r.pregunta_id: r for r in Respuesta.query.filter_by(intento_id=intento.id).all()}
    for pid in intento.orden_preguntas:
        if pid not in respuestas:
            blanco = Respuesta(intento_id=intento.id, pregunta_id=pid, opcion_elegida=None,
                               es_correcta=False, segundos_empleados=0)
            db.session.add(blanco)
            respuestas[pid] = blanco
    aciertos = sum(
        1 for pid in intento.orden_preguntas
        if respuestas[pid].opcion_elegida is not None and respuestas[pid].es_correcta
    )
    duracion = min(intento.segundos_transcurridos(momento), intento.tiempo_limite_segundos)
    intento.aciertos = aciertos
    intento.nota = estadisticas.calcular_nota(aciertos, intento.total_preguntas)
    intento.duracion_segundos = duracion
    intento.fecha_fin = min(momento, intento.fecha_inicio + timedelta(seconds=intento.tiempo_limite_segundos))
    intento.completado = True
    sesion = intento.sesion
    if sesion is not None and sesion.estado == "pendiente":
        sesion.estado = "completada"
        sesion.completada_en = momento
        sesion.minutos_reales = max(1, math.ceil(duracion / 60))
        sesion.resultado_aciertos = aciertos
        sesion.resultado_total = intento.total_preguntas
    db.session.commit()

    try:
        from servicios.planificador import recalcular_plan_usuario
        recalcular_plan_usuario(intento.usuario)
    except Exception:  # el recálculo nunca debe impedir ver el resultado
        db.session.rollback()
        log.exception("Fallo al recalcular el plan tras el intento %s", intento.id)
    return intento


def _finalizar_seguro(intento):
    try:
        finalizar_intento(intento)
    except Exception:
        db.session.rollback()
        log.exception("Error al finalizar el intento %s", intento.id)
        abort(500)


@bp.route("/<int:intento_id>/finalizar", methods=["GET", "POST"])
@login_required
def finalizar(intento_id):
    intento = obtener_propio(Intento, intento_id)
    if request.method == "GET":
        return redirect(url_for("examen.rendir", intento_id=intento.id))
    if not intento.completado:
        _finalizar_seguro(intento)
    return redirect(url_for("examen.resultado", intento_id=intento.id))


# ---------------------------------------------------------------------------
# 7.4 Resultado y revisión
# ---------------------------------------------------------------------------
@bp.route("/<int:intento_id>/resultado")
@login_required
def resultado(intento_id):
    intento = obtener_propio(Intento, intento_id, opciones=(selectinload(Intento.respuestas),))
    if not intento.completado:
        return redirect(url_for("examen.rendir", intento_id=intento.id))
    revision = estadisticas.construir_revision(intento)
    por_nucleo, por_nivel = estadisticas.desglose_intento(revision)
    blancos = sum(1 for i in revision if i["resultado"] == "blanco")
    fallos = sum(1 for i in revision if i["resultado"] == "incorrecta")
    color, mensaje = estadisticas.mensaje_motivacional(intento.nota)
    return render_template(
        "examen/resultado.html",
        intento=intento,
        descripcion=describir_intento(intento),
        revision=revision,
        por_nucleo=por_nucleo,
        por_nivel=por_nivel,
        blancos=blancos,
        fallos=fallos,
        pct=round(intento.aciertos / intento.total_preguntas * 100, 1) if intento.total_preguntas else 0,
        color=color,
        mensaje=mensaje,
        nombres_nucleo=config.NOMBRES_NUCLEO,
        nombres_nivel=config.NOMBRES_NIVEL,
    )
