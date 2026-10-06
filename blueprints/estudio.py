"""Modo tarjetas de estudio (sección 8).

Las tarjetas solo ORDENAN el repaso: nunca afectan nota, dominio ni veredicto.
"""
from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required

import config
from blueprints import obtener_sesion_propia
from extensions import db
from models import CasoPractico, Pregunta, RepasoTarjeta
from servicios import estadisticas

bp = Blueprint("estudio", __name__, url_prefix="/estudio")


def ordenar_tarjetas(usuario_id, preguntas):
    """Primero las que NO sabía (último repaso), luego las nunca repasadas y al final las que sabía."""
    ids = [p.id for p in preguntas]
    ultimos = {}
    if ids:
        registros = (
            RepasoTarjeta.query.filter(
                RepasoTarjeta.usuario_id == usuario_id, RepasoTarjeta.pregunta_id.in_(ids)
            )
            .order_by(RepasoTarjeta.fecha.asc(), RepasoTarjeta.id.asc())
            .all()
        )
        for r in registros:
            ultimos[r.pregunta_id] = r

    def clave(p):
        r = ultimos.get(p.id)
        if r is None:
            return (1, 0.0, p.codigo)
        return (0 if not r.sabia else 2, r.fecha.timestamp(), p.codigo)

    ordenadas = sorted(preguntas, key=clave)
    return ordenadas, ultimos


def _tarjetas_json(preguntas, ultimos):
    tarjetas = []
    for p in preguntas:
        r = ultimos.get(p.id)
        tarjetas.append({
            "id": p.id,
            "codigo": p.codigo,
            "tema": p.tema,
            "nivel": config.NOMBRES_NIVEL.get(p.nivel, p.nivel),
            "enunciado": p.enunciado,
            "correcta": p.opciones[p.correcta],
            "incorrectas": [op for i, op in enumerate(p.opciones) if i != p.correcta],
            "previo": None if r is None else ("sabia" if r.sabia else "no_sabia"),
        })
    return tarjetas


@bp.route("/")
@login_required
def index():
    resumen = estadisticas.resumen_teoria(current_user.id)
    por_nucleo = {1: [], 2: [], 3: [], 4: []}
    for tema in sorted(resumen.temas.values(), key=lambda t: t.nombre):
        por_nucleo[tema.nucleo].append(tema)
    return render_template(
        "estudio/index.html",
        por_nucleo=por_nucleo,
        n_falladas=len(resumen.falladas_ids),
        nombres_nucleo=config.NOMBRES_NUCLEO,
    )


@bp.route("/tema/<slug>")
@login_required
def tema(slug):
    preguntas = Pregunta.query.filter_by(tema_slug=slug).order_by(Pregunta.codigo).all()
    if not preguntas:
        abort(404)
    sesion = obtener_sesion_propia(request.args.get("sesion"))
    ordenadas, ultimos = ordenar_tarjetas(current_user.id, preguntas)
    return render_template(
        "estudio/tarjetas.html",
        titulo=f"Tarjetas · {preguntas[0].tema}",
        subtitulo=f"N{preguntas[0].nucleo} · {config.NOMBRES_NUCLEO[preguntas[0].nucleo]}",
        tarjetas=_tarjetas_json(ordenadas, ultimos),
        sesion=sesion,
        slug=slug,
        es_falladas=False,
        casos_defensa=[],
    )


@bp.route("/falladas")
@login_required
def falladas():
    """Tarjetas de las preguntas falladas (también se usa como 'repaso ligero' del plan)."""
    resumen = estadisticas.resumen_teoria(current_user.id)
    preguntas = [resumen.por_id[pid] for pid in resumen.falladas_ids]
    sesion = obtener_sesion_propia(request.args.get("sesion"))
    ordenadas, ultimos = ordenar_tarjetas(current_user.id, preguntas)
    return render_template(
        "estudio/tarjetas.html",
        titulo="Tarjetas · Mis preguntas falladas",
        subtitulo="Repaso ligero: tu última respuesta en estas preguntas fue incorrecta",
        tarjetas=_tarjetas_json(ordenadas, ultimos),
        sesion=sesion,
        slug=None,
        es_falladas=True,
        casos_defensa=CasoPractico.query.order_by(CasoPractico.codigo).all(),
    )


@bp.route("/tarjeta", methods=["POST"])
@login_required
def registrar_tarjeta():
    datos = request.get_json(silent=True) or {}
    try:
        pregunta_id = int(datos.get("pregunta_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Pregunta no válida."), 400
    if db.session.get(Pregunta, pregunta_id) is None:
        return jsonify(ok=False, error="Pregunta no válida."), 404
    sabia = datos.get("sabia")
    if not isinstance(sabia, bool):
        return jsonify(ok=False, error="Valor no válido."), 400
    db.session.add(RepasoTarjeta(usuario_id=current_user.id, pregunta_id=pregunta_id, sabia=sabia))
    db.session.commit()
    return jsonify(ok=True)
