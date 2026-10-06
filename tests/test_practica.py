"""Pruebas de los cálculos del módulo de práctica (servicios/practica.py)."""
from datetime import timedelta

import pytest

from extensions import db
from models import CasoPractico, EvaluacionCriterio, IntentoPractico, RepasoDefensa, Usuario, ahora
from servicios import practica as srv


# ---------------------------------------------------------------------------
# Funciones puras
# ---------------------------------------------------------------------------
def test_puntaje_sugerido_proporcional_a_tareas():
    criterio = {"puntaje": 2.5, "tareas": [{"id": f"T{i}"} for i in range(5)]}
    assert srv.puntaje_sugerido(criterio, []) == 0.0
    assert srv.puntaje_sugerido(criterio, ["T0", "T1"]) == 1.0
    assert srv.puntaje_sugerido(criterio, [f"T{i}" for i in range(5)]) == 2.5
    assert srv.puntaje_sugerido(criterio, ["OTRA"]) == 0.0


def test_redondeo_conservador_a_paso_025():
    assert srv.redondear_a_paso(0.33) == 0.25
    assert srv.redondear_a_paso(1.0) == 1.0
    assert srv.redondear_a_paso(0.99) == 0.75


@pytest.mark.parametrize("texto,maximo,valor,hay_error", [
    ("1.5", 1.5, 1.5, False),
    ("0,75", 1.0, 0.75, False),
    ("0", 2.0, 0.0, False),
    ("2.25", 2.0, None, True),     # supera el máximo
    ("-1", 2.0, None, True),       # negativo
    ("0.3", 2.0, None, True),      # no es múltiplo de 0.25
    ("abc", 2.0, None, True),
    ("", 2.0, None, True),
    ("nan", 2.0, None, True),
])
def test_validar_puntaje(texto, maximo, valor, hay_error):
    resultado, error = srv.validar_puntaje(texto, maximo)
    assert (error is not None) == hay_error
    assert resultado == valor


def test_nota_nunca_supera_maximos_ni_10():
    evs = [EvaluacionCriterio(criterio_id="A", puntaje_maximo=3.0, puntaje_sugerido=3, puntaje_final=5.0),
           EvaluacionCriterio(criterio_id="B", puntaje_maximo=7.0, puntaje_sugerido=7, puntaje_final=7.0),
           EvaluacionCriterio(criterio_id="C", puntaje_maximo=1.0, puntaje_sugerido=1, puntaje_final=1.0)]
    assert srv.nota_de_evaluaciones(evs) == 10.0


def test_semaforo_y_ajuste():
    assert srv.semaforo(None, 7) == "secondary"
    assert srv.semaforo(8.0, 7) == "success"
    assert srv.semaforo(7.5, 7) == "warning"
    assert srv.semaforo(6.9, 7) == "danger"
    assert srv.nota_ajustada(10.0) == 9.5


# ---------------------------------------------------------------------------
# Con base de datos
# ---------------------------------------------------------------------------
def _usuario():
    u = Usuario(nombre_completo="Prueba", email="p@p.com")
    u.set_password("12345678")
    db.session.add(u)
    db.session.commit()
    return u


def _intento(usuario, caso, fraccion=1.0, minutos_atras=0, evaluar_todo=True, completado=True):
    inicio = ahora() - timedelta(minutes=200 + minutos_atras)
    intento = IntentoPractico(usuario_id=usuario.id, caso_id=caso.id, fecha_inicio=inicio,
                              fecha_fin=inicio + timedelta(minutes=100), tiempo_limite_segundos=180 * 60,
                              duracion_segundos=6000, tareas_ok=[], completado=completado)
    db.session.add(intento)
    db.session.flush()
    criterios = caso.rubrica if evaluar_todo else caso.rubrica[:-1]
    for c in criterios:
        db.session.add(EvaluacionCriterio(intento_practico_id=intento.id, criterio_id=c["id"],
                                          puntaje_maximo=c["puntaje"], puntaje_sugerido=c["puntaje"] * fraccion,
                                          puntaje_final=c["puntaje"] * fraccion))
    db.session.flush()
    db.session.refresh(intento)
    intento.nota_autoevaluada = srv.nota_de_evaluaciones(intento.evaluaciones)
    db.session.commit()
    return intento


def test_nota_caso_promedia_los_ultimos_dos_validos(db_app):
    u = _usuario()
    caso = CasoPractico.query.filter_by(codigo="P1").first()
    _intento(u, caso, fraccion=0.4, minutos_atras=300)    # 4.0 (el más antiguo, no cuenta)
    _intento(u, caso, fraccion=0.6, minutos_atras=200)    # 6.0
    _intento(u, caso, fraccion=0.8, minutos_atras=100)    # 8.0
    assert srv.nota_caso(u.id, caso) == 7.0
    assert len(srv.intentos_validos(u.id, caso)) == 3


def test_un_solo_intento_es_la_nota_del_caso(db_app):
    u = _usuario()
    caso = CasoPractico.query.filter_by(codigo="P3").first()
    _intento(u, caso, fraccion=0.9)
    assert srv.nota_caso(u.id, caso) == 9.0


def test_intento_sin_todos_los_criterios_no_es_valido(db_app):
    u = _usuario()
    caso = CasoPractico.query.filter_by(codigo="P2").first()
    intento = _intento(u, caso, fraccion=1.0, evaluar_todo=False)
    assert not srv.es_intento_valido(intento, caso)
    assert srv.nota_caso(u.id, caso) is None


def test_intento_no_completado_no_cuenta(db_app):
    u = _usuario()
    caso = CasoPractico.query.filter_by(codigo="P2").first()
    _intento(u, caso, fraccion=1.0, completado=False)
    assert srv.nota_caso(u.id, caso) is None


def test_nota_practica_promedio_de_casos_con_intentos(db_app):
    u = _usuario()
    p1 = CasoPractico.query.filter_by(codigo="P1").first()
    p2 = CasoPractico.query.filter_by(codigo="P2").first()
    _intento(u, p1, fraccion=0.6)
    _intento(u, p2, fraccion=0.8)
    assert srv.nota_practica_promedio(u.id) == 7.0


def test_debilidad_por_criterio_usa_el_ultimo_intento(db_app):
    u = _usuario()
    caso = CasoPractico.query.filter_by(codigo="P4").first()
    assert set(srv.debilidad_por_criterio(u.id, caso).values()) == {None}
    _intento(u, caso, fraccion=1.0, minutos_atras=100)
    _intento(u, caso, fraccion=0.5, minutos_atras=0)
    debilidad = srv.debilidad_por_criterio(u.id, caso)
    assert set(debilidad.values()) == {50.0}


def test_dominio_defensa_con_ultimo_registro_y_parcial(db_app):
    u = _usuario()
    caso = CasoPractico.query.filter_by(codigo="P2").first()     # 7 preguntas de defensa
    registros = [(0, "no_se"), (0, "dominado"), (1, "parcial"), (2, "dominado"), (2, "no_se")]
    for i, (indice, nivel) in enumerate(registros):
        db.session.add(RepasoDefensa(usuario_id=u.id, caso_id=caso.id, indice_pregunta=indice, nivel=nivel,
                                     fecha=ahora() + timedelta(seconds=i)))
    db.session.commit()
    # Últimos: 0 dominado (1) + 1 parcial (0.5) + 2 no_se (0) → 1.5 / 7
    assert srv.dominio_defensa(u.id, caso) == round(1.5 / 7 * 100, 1)


def test_resumen_casos_devuelve_los_cuatro(db_app):
    u = _usuario()
    filas = srv.resumen_casos(u.id, 7.0)
    assert [f["caso"].codigo for f in filas] == ["P1", "P2", "P3", "P4"]
    assert all(f["semaforo"] == "secondary" for f in filas)
