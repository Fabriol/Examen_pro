"""Plan de estudio: crear, ver, calendario, ejecutar sesiones, veredicto y pendientes (secciones 10 y 12)."""
import calendar
import logging
from datetime import date, timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, FloatField, IntegerField, SubmitField
from wtforms.validators import InputRequired, NumberRange, Optional

import config
from blueprints import obtener_propio
from extensions import db
from models import DIAS_SEMANA, CasoPractico, PlanEstudio, SesionEstudio, VeredictoDiario, ahora
from servicios import planificador, veredicto as srv_veredicto
from servicios.estadisticas import parametros_examen

bp = Blueprint("plan", __name__, url_prefix="/plan")
log = logging.getLogger(__name__)

NOMBRES_DIA = {"lun": "Lunes", "mar": "Martes", "mie": "Miércoles", "jue": "Jueves",
               "vie": "Viernes", "sab": "Sábado", "dom": "Domingo"}
ETIQUETAS_FASE = {"diagnostico": "Diagnóstico", "cobertura": "Cobertura", "refuerzo": "Refuerzo",
                  "simulacro": "Simulacros", "repaso_final": "Repaso final"}
ETIQUETAS_TIPO = {
    "tarjetas": "Tarjetas", "practica_tema": "Práctica de tema", "simulacro_nucleo": "Simulacro de núcleo",
    "simulacro_completo": "Simulacro completo", "fallidas": "Falladas", "repaso_ligero": "Repaso ligero",
    "practica_caso": "Práctica de caso", "intento_practico": "Intento práctico", "defensa": "Defensa",
}
TIPOS_SIN_INTENTO = ("tarjetas", "practica_caso", "defensa", "repaso_ligero")


def _campo_horas(nombre):
    return DecimalField(
        NOMBRES_DIA[nombre], places=1, default=2,
        validators=[InputRequired(message="Indica las horas (0 = descanso)."),
                    NumberRange(min=0, max=12, message="Entre 0 y 12 horas.")],
    )


class PlanForm(FlaskForm):
    fecha_examen = DateField("Fecha del examen", validators=[InputRequired(message="Indica la fecha del examen.")])
    fecha_inicio = DateField("Fecha de inicio", validators=[Optional()])
    lun = _campo_horas("lun")
    mar = _campo_horas("mar")
    mie = _campo_horas("mie")
    jue = _campo_horas("jue")
    vie = _campo_horas("vie")
    sab = _campo_horas("sab")
    dom = _campo_horas("dom")
    nota_minima = FloatField("Nota mínima de aprobación", default=config.NOTA_MINIMA_APROBACION,
                             validators=[InputRequired(), NumberRange(min=0, max=10, message="Entre 0 y 10.")])
    peso_teoria = IntegerField("Peso de la teoría (%)", default=round(config.PESO_TEORIA * 100),
                               validators=[InputRequired(), NumberRange(min=0, max=100)])
    peso_practica = IntegerField("Peso de la práctica (%)", default=round(config.PESO_PRACTICA * 100),
                                 validators=[InputRequired(), NumberRange(min=0, max=100)])
    porcentaje_tiempo_practica = IntegerField("% del tiempo para práctica", default=50,
                                              validators=[InputRequired(), NumberRange(min=0, max=100)])
    enviar = SubmitField("Generar plan")

    def validate(self, extra_validators=None):
        valido = super().validate(extra_validators)
        hoy = date.today()
        inicio = self.fecha_inicio.data or hoy
        if self.fecha_examen.data:
            if self.fecha_examen.data <= hoy:
                self.fecha_examen.errors.append(
                    "El examen es hoy o ya pasó: no se puede generar un plan. La fecha debe ser posterior a hoy.")
                valido = False
            elif self.fecha_examen.data <= inicio:
                self.fecha_examen.errors.append("La fecha del examen debe ser posterior a la fecha de inicio.")
                valido = False
        horas = [getattr(self, d).data for d in DIAS_SEMANA]
        if all(h is not None for h in horas):
            if not any(float(h) > 0 for h in horas):
                self.lun.errors.append("Asigna horas de estudio al menos a un día de la semana.")
                valido = False
            for d in DIAS_SEMANA:
                valor = getattr(self, d).data
                if valor is not None and (float(valor) * 2) % 1 != 0:
                    getattr(self, d).errors.append("Usa pasos de 0.5 horas.")
                    valido = False
        if self.peso_teoria.data is not None and self.peso_practica.data is not None:
            if self.peso_teoria.data + self.peso_practica.data != 100:
                self.peso_practica.errors.append("Los pesos de teoría y práctica deben sumar 100 %.")
                valido = False
        return valido


def _plan_activo_o_none():
    return current_user.plan_activo


def _agrupar_por_fecha(sesiones):
    dias = {}
    for s in sesiones:
        dias.setdefault(s.fecha, []).append(s)
    return dias


# ---------------------------------------------------------------------------
# Vistas del plan
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
def index():
    plan = _plan_activo_o_none()
    anteriores = (PlanEstudio.query.filter_by(usuario_id=current_user.id, activo=False)
                  .order_by(PlanEstudio.fecha_creacion.desc()).all())
    if plan is None:
        return render_template("plan/index.html", plan=None, anteriores=anteriores)
    return _render_plan(plan, anteriores)


@bp.route("/<int:plan_id>")
@login_required
def ver(plan_id):
    plan = obtener_propio(PlanEstudio, plan_id)
    if plan.activo:
        return redirect(url_for("plan.index"))
    return _render_plan(plan, [])


def _render_plan(plan, anteriores):
    hoy = date.today()
    stats = planificador.estadisticas_plan(plan, hoy)
    resumen_veredicto = None
    if plan.activo:
        try:
            resumen_veredicto = srv_veredicto.calcular_veredicto_usuario(current_user, hoy)
        except Exception:
            db.session.rollback()
            log.exception("No se pudo calcular el veredicto")
    proximas = [s for s in plan.sesiones if hoy < s.fecha <= hoy + timedelta(days=7)]
    atrasadas = [s for s in plan.sesiones if s.estado == "pendiente" and s.fecha < hoy]
    return render_template(
        "plan/index.html",
        plan=plan,
        stats=stats,
        veredicto=resumen_veredicto,
        proximas=_agrupar_por_fecha(proximas),
        atrasadas=atrasadas,
        anteriores=anteriores,
        hoy=hoy,
        etiquetas_fase=ETIQUETAS_FASE,
        etiquetas_tipo=ETIQUETAS_TIPO,
        nombres_dia=NOMBRES_DIA,
    )


@bp.route("/crear", methods=["GET", "POST"])
@login_required
def crear():
    form = PlanForm()
    activo = _plan_activo_o_none()
    if request.method == "GET":
        form.fecha_inicio.data = date.today()
        if activo:
            form.fecha_examen.data = activo.fecha_examen
            for d in DIAS_SEMANA:
                getattr(form, d).data = activo.horas_por_dia.get(d, 0)
            form.nota_minima.data = activo.nota_minima
            form.peso_teoria.data = round(activo.peso_teoria * 100)
            form.peso_practica.data = round(activo.peso_practica * 100)
            form.porcentaje_tiempo_practica.data = activo.porcentaje_tiempo_practica
        elif config.FECHA_EXAMEN:
            try:
                form.fecha_examen.data = date.fromisoformat(config.FECHA_EXAMEN)
            except ValueError:
                pass
    if form.validate_on_submit():
        datos = {
            "fecha_inicio": form.fecha_inicio.data or date.today(),
            "fecha_examen": form.fecha_examen.data,
            "horas_por_dia": {d: float(getattr(form, d).data) for d in DIAS_SEMANA},
            "nota_minima": float(form.nota_minima.data),
            "peso_teoria": form.peso_teoria.data / 100,
            "peso_practica": form.peso_practica.data / 100,
            "porcentaje_tiempo_practica": int(form.porcentaje_tiempo_practica.data),
        }
        try:
            plan, resultado = planificador.crear_plan(current_user, datos)
        except Exception:
            db.session.rollback()
            log.exception("Error al crear el plan")
            abort(500)
        if resultado.modo_intensivo:
            flash("Plan creado en MODO INTENSIVO: quedan menos de 3 días de estudio.", "warning")
        elif resultado.minutos_faltantes:
            flash("Plan creado, pero el tiempo no alcanza para todo: revisa las advertencias.", "warning")
        else:
            flash("¡Plan de estudio creado!", "success")
        return redirect(url_for("plan.index"))
    return render_template("plan/crear.html", form=form, activo=activo, nombres_dia=NOMBRES_DIA,
                           dias=DIAS_SEMANA)


@bp.route("/recalcular", methods=["POST"])
@login_required
def recalcular():
    plan = _plan_activo_o_none()
    if plan is None:
        flash("No tienes un plan activo.", "info")
        return redirect(url_for("plan.crear"))
    try:
        planificador.recalcular_plan(plan)
        flash("Plan recalculado con tus datos más recientes.", "success")
    except Exception:
        db.session.rollback()
        log.exception("Error al recalcular el plan %s", plan.id)
        abort(500)
    return redirect(url_for("plan.index"))


@bp.route("/semana")
@login_required
def semana():
    plan = _plan_activo_o_none()
    if plan is None:
        flash("Primero crea tu plan de estudio.", "info")
        return redirect(url_for("plan.crear"))
    hoy = date.today()
    vista = request.args.get("vista", "semana")
    try:
        referencia = date.fromisoformat(request.args.get("fecha", "")) if request.args.get("fecha") else hoy
    except ValueError:
        referencia = hoy
    if vista == "mes":
        inicio_mes = referencia.replace(day=1)
        inicio = inicio_mes - timedelta(days=inicio_mes.weekday())
        fin_mes = referencia.replace(day=calendar.monthrange(referencia.year, referencia.month)[1])
        fin = fin_mes + timedelta(days=6 - fin_mes.weekday())
        anterior = (inicio_mes - timedelta(days=1)).replace(day=1)
        siguiente = fin_mes + timedelta(days=1)
    else:
        vista = "semana"
        inicio = referencia - timedelta(days=referencia.weekday())
        fin = inicio + timedelta(days=6)
        anterior, siguiente = inicio - timedelta(days=7), inicio + timedelta(days=7)
    por_fecha = _agrupar_por_fecha(s for s in plan.sesiones if inicio <= s.fecha <= fin)
    dias = [inicio + timedelta(days=i) for i in range((fin - inicio).days + 1)]
    return render_template(
        "plan/semana.html", plan=plan, vista=vista, dias=dias, por_fecha=por_fecha, hoy=hoy,
        referencia=referencia, anterior=anterior, siguiente=siguiente, etiquetas_tipo=ETIQUETAS_TIPO,
        etiquetas_fase=ETIQUETAS_FASE,
    )


# ---------------------------------------------------------------------------
# Ejecutar sesiones
# ---------------------------------------------------------------------------
@bp.route("/sesion/<int:sesion_id>/iniciar")
@login_required
def iniciar_sesion(sesion_id):
    s = obtener_propio(SesionEstudio, sesion_id)
    if s.estado != "pendiente":
        flash(f"Esta sesión ya está {s.estado}.", "info")
        return redirect(url_for("plan.index"))
    if not s.plan.activo:
        flash("Esa sesión pertenece a un plan inactivo.", "warning")
        return redirect(url_for("plan.index"))
    destinos = {
        "tarjetas": lambda: url_for("estudio.tema", slug=s.tema_slug, sesion=s.id),
        "practica_tema": lambda: url_for("examen.configurar", modo="tema", tema=s.tema_slug, sesion=s.id),
        "simulacro_nucleo": lambda: url_for("examen.configurar", modo="nucleo", nucleo=s.nucleo, sesion=s.id),
        "simulacro_completo": lambda: url_for("examen.configurar", modo="completo", sesion=s.id),
        "fallidas": lambda: url_for("examen.configurar", modo="fallidas", sesion=s.id),
        "practica_caso": lambda: url_for("practica.caso", codigo=s.caso_codigo, sesion=s.id, criterio=s.criterio_id),
        "intento_practico": lambda: url_for("practica.caso", codigo=s.caso_codigo, sesion=s.id) + "#iniciar",
        "defensa": lambda: url_for("practica.defensa", codigo=s.caso_codigo, sesion=s.id),
        "repaso_ligero": lambda: url_for("estudio.falladas", sesion=s.id),
    }
    destino = destinos.get(s.tipo)
    if destino is None:
        abort(404)
    return redirect(destino())


@bp.route("/sesion/<int:sesion_id>/omitir", methods=["POST"])
@login_required
def omitir_sesion(sesion_id):
    s = obtener_propio(SesionEstudio, sesion_id)
    if s.estado != "pendiente":
        flash("Solo se pueden omitir sesiones pendientes.", "warning")
        return redirect(url_for("plan.index"))
    s.estado = "omitida"
    db.session.commit()
    try:
        planificador.recalcular_plan(s.plan)
        flash("Sesión omitida: el plan se reprogramó.", "info")
    except Exception:
        db.session.rollback()
        log.exception("Error al reprogramar tras omitir la sesión %s", s.id)
        flash("Sesión omitida, pero no se pudo reprogramar el plan.", "warning")
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url)
                    else url_for("plan.index"))


@bp.route("/sesion/<int:sesion_id>/terminar", methods=["POST"])
@login_required
def terminar_sesion(sesion_id):
    s = obtener_propio(SesionEstudio, sesion_id)
    datos = request.get_json(silent=True) or request.form
    if s.estado != "pendiente":
        return jsonify(ok=True, redirect=url_for("plan.index"))
    if s.tipo not in TIPOS_SIN_INTENTO:
        return jsonify(ok=False, error="Esta sesión se completa al finalizar su intento."), 400
    try:
        minutos = int(datos.get("minutos_reales") or s.minutos_planificados)
    except (TypeError, ValueError):
        minutos = s.minutos_planificados
    s.minutos_reales = max(1, min(minutos, 24 * 60))
    s.estado = "completada"
    s.completada_en = ahora()
    db.session.commit()
    flash(f"Sesión completada: {s.titulo} ({s.minutos_reales} min).", "success")
    return jsonify(ok=True, redirect=url_for("plan.index"))


# ---------------------------------------------------------------------------
# Veredicto y pendientes con el docente
# ---------------------------------------------------------------------------
@bp.route("/veredicto")
@login_required
def veredicto():
    hoy = date.today()
    resultado = srv_veredicto.calcular_veredicto_usuario(current_user, hoy)
    fotos = (VeredictoDiario.query.filter_by(usuario_id=current_user.id)
             .order_by(VeredictoDiario.fecha.asc()).all())
    params = parametros_examen(current_user)
    return render_template(
        "plan/veredicto.html",
        v=resultado,
        params=params,
        evolucion={"fechas": [f.fecha.strftime("%d/%m") for f in fotos], "indices": [f.indice for f in fotos]},
    )


@bp.route("/pendientes-docente")
@login_required
def pendientes_docente():
    params = parametros_examen(current_user)
    casos = CasoPractico.query.order_by(CasoPractico.codigo).all()
    return render_template("plan/pendientes_docente.html", params=params, casos=casos)
