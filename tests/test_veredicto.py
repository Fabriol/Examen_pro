"""Pruebas del veredicto de aptitud (servicios/veredicto.py, función pura)."""
from datetime import date, datetime, timedelta

import pytest

from servicios.veredicto import CasoVer, DatosVeredicto, ajustar, evaluar, pendiente

HOY = date(2026, 10, 1)


def casos(notas=(9.5, 9.5, 9.5, 9.5), validos=(2, 2, 2, 2), defensa_p2=90.0):
    codigos = ("P1", "P2", "P3", "P4")
    return [CasoVer(c, f"Caso {c}", n, v, defensa_p2 if c == "P2" else 0.0, c == "P2")
            for c, n, v in zip(codigos, notas, validos)]


def serie(*notas):
    inicio = datetime(2026, 9, 1, 10, 0)
    return [(inicio + timedelta(days=3 * i), n) for i, n in enumerate(notas)]


def datos(**cambios):
    base = dict(
        nota_minima=7.0, peso_teoria=0.5, peso_practica=0.5,
        notas_validas=serie(8.6, 8.8, 9.0, 9.2),
        pct_nucleo={1: 90.0, 2: 88.0, 3: 92.0, 4: 85.0},
        dominio_estable_pct=85.0, cobertura_pct=100.0,
        casos=casos(), plan_activo=True, cumplimiento_pct=95.0, hoy=HOY,
    )
    base.update(cambios)
    return DatosVeredicto(**base)


def criterio(v, codigo):
    return next(c for c in v.todos_los_criterios if c.codigo == codigo)


# ---------------------------------------------------------------------------
def test_todos_los_criterios_cumplen_da_apto():
    v = evaluar(datos())
    assert v.estado == "APTO"
    assert all(c.cumple in (True, None) for c in v.todos_los_criterios)


def test_sin_datos_lista_lo_que_falta():
    v = evaluar(datos(notas_validas=[], pct_nucleo={1: None, 2: None, 3: None, 4: None},
                      dominio_estable_pct=0.0, cobertura_pct=0.0,
                      casos=casos(notas=(None,) * 4, validos=(0,) * 4, defensa_p2=0.0), plan_activo=False,
                      cumplimiento_pct=None))
    assert v.estado == "SIN_DATOS" and v.etiqueta == "SIN DATOS"
    textos = " ".join(f["texto"] for f in v.faltantes)
    assert "simulacro válido" in textos
    for codigo in ("P1", "P2", "P3", "P4"):
        assert codigo in textos
    assert all(f["endpoint"] for f in v.faltantes)


def test_sin_datos_muestra_veredicto_parcial():
    v = evaluar(datos(casos=casos(notas=(9.0, None, 9.0, 9.0), validos=(1, 0, 1, 1))))
    assert v.estado == "SIN_DATOS"
    assert any(p.startswith("Teoría") for p in v.parcial)
    assert any(p.startswith("Práctica") for p in v.parcial)


def test_simulacro_afortunado_no_da_apto():
    v = evaluar(datos(notas_validas=serie(10.0)))
    assert v.estado != "APTO"
    assert criterio(v, "T5").cumple is False            # < 2 simulacros válidos
    assert criterio(v, "T6").cumple is False            # sin tendencia con < 3 notas


def test_caso_practico_bajo_minima_nunca_apto():
    v = evaluar(datos(notas_validas=serie(9.8, 9.9, 10.0), casos=casos(notas=(10.0, 10.0, 10.0, 6.5))))
    assert v.estado != "APTO"
    assert criterio(v, "P2").cumple is False
    assert "P4" in criterio(v, "P2").valor


def test_autoevaluacion_10_se_ajusta_a_9_5():
    assert ajustar(10.0) == 9.5
    assert ajustar(0.2) == 0.0
    v = evaluar(datos(casos=casos(notas=(10.0,) * 4)))
    assert v.nota_practica == 10.0
    assert v.nota_practica_ajustada == 9.5
    assert v.notas_caso["P1"] == 9.5


def test_nucleo_bajo_70_en_riesgo_con_criterio_marcado():
    v = evaluar(datos(pct_nucleo={1: 90.0, 2: 65.0, 3: 92.0, 4: 85.0}))
    assert v.estado == "EN_RIESGO" and v.etiqueta == "EN RIESGO"
    t2 = criterio(v, "T2")
    assert t2.cumple is False and "N2" in t2.valor
    assert t2 in v.fallidos


def test_nota_final_bajo_minima_no_apto():
    v = evaluar(datos(notas_validas=serie(5.0, 5.5, 6.0), casos=casos(notas=(6.0, 6.5, 6.0, 6.0))))
    assert v.nota_final_estimada < 7.0
    assert v.estado == "NO_APTO" and v.etiqueta == "NO APTO AÚN"


def test_eslabon_debil_global_impide_apto():
    # Promedio ponderado >= 7, pero la práctica ajustada queda bajo la mínima.
    v = evaluar(datos(notas_validas=serie(9.9, 10.0, 10.0), casos=casos(notas=(7.2, 7.2, 7.2, 7.2))))
    assert v.nota_final_estimada >= 7.0
    assert v.nota_practica_ajustada < 7.0
    assert v.eslabon_debil and v.estado == "EN_RIESGO"


def test_defensa_p2_baja_en_riesgo():
    v = evaluar(datos(casos=casos(defensa_p2=40.0)))
    assert v.estado == "EN_RIESGO"
    assert criterio(v, "P4").cumple is False


def test_cumplimiento_bajo_y_sin_plan():
    assert criterio(evaluar(datos(cumplimiento_pct=50.0)), "C1").cumple is False
    sin_plan = evaluar(datos(plan_activo=False, cumplimiento_pct=None))
    assert criterio(sin_plan, "C1").cumple is None
    assert sin_plan.estado == "APTO"                      # C1 solo aplica con plan activo


def test_cada_criterio_muestra_valor_actual_y_meta():
    v = evaluar(datos())
    codigos = [c.codigo for c in v.todos_los_criterios]
    assert codigos == ["T1", "T2", "T3", "T4", "T5", "T6", "P1", "P2", "P3", "P4", "C1"]
    for c in v.todos_los_criterios:
        assert c.valor and c.meta


def test_p3_recomienda_dos_intentos():
    v = evaluar(datos(casos=casos(validos=(1, 2, 2, 2))))
    assert criterio(v, "P3").cumple is True
    assert "recomendado 2" in criterio(v, "P3").aviso.lower()


def test_tendencia_negativa():
    v = evaluar(datos(notas_validas=serie(9.8, 9.4, 9.0, 8.6)))
    assert criterio(v, "T6").cumple is False
    assert pendiente([1, 2, 3]) == pytest.approx(1.0)


def test_indice_entre_0_y_100_y_redistribuye_sin_plan():
    lleno = evaluar(datos())
    assert 0 <= lleno.indice <= 100
    vacio = evaluar(datos(notas_validas=[], pct_nucleo={1: None, 2: None, 3: None, 4: None},
                          dominio_estable_pct=0.0, cobertura_pct=0.0,
                          casos=casos(notas=(None,) * 4, validos=(0,) * 4, defensa_p2=0.0),
                          plan_activo=False, cumplimiento_pct=None))
    assert vacio.indice == 0.0
    solo_plan = evaluar(datos(notas_validas=[], pct_nucleo={1: None, 2: None, 3: None, 4: None},
                              dominio_estable_pct=0.0, cobertura_pct=0.0,
                              casos=casos(notas=(None,) * 4, validos=(0,) * 4, defensa_p2=0.0),
                              plan_activo=True, cumplimiento_pct=100.0))
    assert solo_plan.indice == 5.0                          # el cumplimiento pesa 5 %
    sin_plan = evaluar(datos(plan_activo=False, cumplimiento_pct=None))
    assert 0 <= sin_plan.indice <= 100


def test_proyeccion_insuficiente_y_acotada():
    v = evaluar(datos(fecha_examen=HOY + timedelta(days=20)))
    assert v.proyeccion is None and "insuficientes" in v.proyeccion_msg
    v = evaluar(datos(fecha_examen=HOY + timedelta(days=400),
                      notas_practicas=serie(8.0, 9.0, 10.0)))
    assert v.proyeccion is not None and 0.0 <= v.proyeccion <= 10.0


def test_suficiencia_de_tiempo():
    assert evaluar(datos(minutos_necesarios=600, minutos_disponibles=900)).suficiencia == "Suficiente"
    assert evaluar(datos(minutos_necesarios=600, minutos_disponibles=650)).suficiencia == "Justo"
    assert evaluar(datos(minutos_necesarios=600, minutos_disponibles=300)).suficiencia == "Insuficiente"


def test_recomendaciones_maximo_cinco():
    v = evaluar(datos(notas_validas=serie(6.0), casos=casos(notas=(5.0, None, 6.0, 6.0), validos=(1, 0, 1, 1),
                                                            defensa_p2=10.0),
                      plan_activo=False, cumplimiento_pct=None,
                      tema_mas_debil={"nombre": "Vistas", "slug": "n2-vistas", "pct": 20.0},
                      criterio_mas_debil={"caso": "P1", "id": "P1-R4", "nombre": "Lógica", "pct": 10.0}))
    assert 1 <= len(v.recomendaciones) <= 5
    assert all(r["endpoint"] for r in v.recomendaciones)
