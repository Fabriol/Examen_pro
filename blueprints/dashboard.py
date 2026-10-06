"""Dashboard: indicadores, gráficas, debilidades, falladas, historial y revisión (sección 13)."""
import logging
from datetime import date

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

import config
from blueprints import obtener_propio
from blueprints.examen import describir_intento
from extensions import db
from models import Intento, IntentoPractico
from servicios import estadisticas
from servicios import practica as srv_practica
from servicios import planificador
from servicios import veredicto as srv_veredicto

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")
log = logging.getLogger(__name__)


@bp.route("/")
@login_required
def index():
    hoy = date.today()
    usuario = current_user
    params = estadisticas.parametros_examen(usuario)
    resumen = estadisticas.resumen_teoria(usuario.id)
    intentos = estadisticas.intentos_completados(usuario.id)
    filas_casos = srv_practica.resumen_casos(usuario.id, params["nota_minima"])
    temas_por_slug = {t.slug: t.nombre for t in resumen.temas.values()}

    try:
        v = srv_veredicto.calcular_veredicto_usuario(usuario, hoy)
    except Exception:
        db.session.rollback()
        log.exception("No se pudo calcular el veredicto en el dashboard")
        v = None

    plan = params["plan"]
    stats_plan = planificador.estadisticas_plan(plan, hoy) if plan else None

    mejora = None
    if len(intentos) >= 2:
        primero, ultimo = intentos[0].nota, intentos[-1].nota
        cambio = ((ultimo - primero) / primero * 100) if primero else None
        mejora = {"primero": primero, "ultimo": ultimo, "diferencia": round(ultimo - primero, 2),
                  "pct": round(cambio, 1) if cambio is not None else None}

    graficas = {
        "evolucion": {
            "etiquetas": [i.fecha_fin.strftime("%d/%m %H:%M") for i in intentos],
            "notas": [i.nota for i in intentos],
            "descripciones": [describir_intento(i, temas_por_slug) for i in intentos],
        },
        "nucleos": {
            "etiquetas": [f"N{n}" for n in (1, 2, 3, 4)],
            "valores": [resumen.por_nucleo[n].pct for n in (1, 2, 3, 4)],
        },
        "niveles": {
            "etiquetas": [config.NOMBRES_NIVEL[n] for n in ("facil", "medio", "dificil")],
            "valores": [resumen.por_nivel[n].pct for n in ("facil", "medio", "dificil")],
        },
        "casos": {
            "etiquetas": [f["caso"].codigo for f in filas_casos],
            "ultima": [f["ultima_nota"] for f in filas_casos],
            "mejor": [f["mejor_nota"] for f in filas_casos],
            "colores": [f["semaforo"] for f in filas_casos],
        },
        "practica": _evolucion_practica(usuario.id),
        "nota_minima": params["nota_minima"],
    }

    return render_template(
        "dashboard/index.html",
        usuario=usuario,
        params=params,
        resumen=resumen,
        intentos=intentos,
        v=v,
        stats_plan=stats_plan,
        mejora=mejora,
        graficas=graficas,
        temas_debiles=resumen.temas_mas_debiles(8),
        criterios_debiles=srv_practica.criterios_mas_debiles(filas_casos, 6),
        ranking=resumen.ranking_fallos(10),
        n_falladas=len(resumen.falladas_ids),
        filas_casos=filas_casos,
        nota_pie=estadisticas.NOTA_PIE_PORCENTAJES,
        hoy=hoy,
        nombres_nucleo=config.NOMBRES_NUCLEO,
    )


def _evolucion_practica(usuario_id):
    puntos = srv_practica.notas_practicas_cronologicas(usuario_id)
    return {
        "etiquetas": [f.strftime("%d/%m") for f, _, _ in puntos],
        "notas": [n for _, _, n in puntos],
        "casos": [c for _, c, _ in puntos],
    }


@bp.route("/historial")
@login_required
def historial():
    teoricos = (Intento.query.filter_by(usuario_id=current_user.id, completado=True)
                .order_by(Intento.fecha_fin.desc()).all())
    practicos = (IntentoPractico.query.options(selectinload(IntentoPractico.caso))
                 .filter_by(usuario_id=current_user.id, completado=True)
                 .order_by(IntentoPractico.fecha_fin.desc()).all())
    resumen = estadisticas.resumen_teoria(current_user.id)
    temas_por_slug = {t.slug: t.nombre for t in resumen.temas.values()}
    filas = [{
        "fecha": i.fecha_fin, "tipo": "Teórico", "detalle": describir_intento(i, temas_por_slug),
        "nota": i.nota, "duracion": i.duracion_segundos, "extra": f"{i.aciertos}/{i.total_preguntas}",
        "url": url_for("dashboard.revision", intento_id=i.id),
    } for i in teoricos] + [{
        "fecha": p.fecha_fin, "tipo": "Práctico", "detalle": f"{p.caso.codigo} · {p.caso.titulo}",
        "nota": p.nota_autoevaluada, "duracion": p.duracion_segundos, "extra": "autoevaluada",
        "url": url_for("practica.resultado", intento_id=p.id),
    } for p in practicos]
    filas.sort(key=lambda f: f["fecha"], reverse=True)
    return render_template("dashboard/historial.html", filas=filas)


@bp.route("/debilidades")
@login_required
def debilidades():
    params = estadisticas.parametros_examen(current_user)
    resumen = estadisticas.resumen_teoria(current_user.id)
    filas_casos = srv_practica.resumen_casos(current_user.id, params["nota_minima"])
    return render_template(
        "dashboard/debilidades.html",
        temas=resumen.temas_mas_debiles(limite=None),
        criterios=srv_practica.criterios_mas_debiles(filas_casos, incluir_sin_datos=True),
        ranking=resumen.ranking_fallos(),
        nota_pie=estadisticas.NOTA_PIE_PORCENTAJES,
        nombres_nucleo=config.NOMBRES_NUCLEO,
    )


@bp.route("/revision/<int:intento_id>")
@login_required
def revision(intento_id):
    intento = obtener_propio(Intento, intento_id, opciones=(selectinload(Intento.respuestas),))
    if not intento.completado:
        return redirect(url_for("examen.rendir", intento_id=intento.id))
    return render_template(
        "dashboard/revision.html",
        intento=intento,
        descripcion=describir_intento(intento),
        revision=estadisticas.construir_revision(intento),
    )
