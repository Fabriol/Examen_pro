"""Blueprints de la aplicación: auth, examen, estudio, practica, plan y dashboard.

Incluye los helpers de aislamiento (regla 5.11): toda ruta que recibe el id de un
intento, intento práctico, plan o sesión verifica que pertenezca al usuario → 403.
"""
from flask import abort
from flask_login import current_user

from extensions import db


def obtener_propio(modelo, objeto_id, opciones=()):
    """Carga `modelo` por id: 404 si no existe, 403 si pertenece a otro usuario."""
    consulta = db.session.query(modelo)
    if opciones:
        consulta = consulta.options(*opciones)
    objeto = consulta.filter(modelo.id == objeto_id).first()
    if objeto is None:
        abort(404)
    if _dueno(objeto) != current_user.id:
        abort(403)
    return objeto


def obtener_sesion_propia(sesion_id):
    """SesionEstudio del usuario o None si no se pasó id; 403 si es de otro usuario."""
    from models import SesionEstudio

    if sesion_id in (None, "", "None"):
        return None
    try:
        sesion_id = int(sesion_id)
    except (TypeError, ValueError):
        abort(404)
    return obtener_propio(SesionEstudio, sesion_id)


def _dueno(objeto):
    if hasattr(objeto, "usuario_id"):
        return objeto.usuario_id
    if hasattr(objeto, "plan"):
        return objeto.plan.usuario_id
    return None
