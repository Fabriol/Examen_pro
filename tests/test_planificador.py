"""Pruebas del algoritmo del plan de estudio (servicios/planificador.py, función pura)."""
from collections import Counter
from datetime import date, timedelta

import pytest

from servicios.planificador import (BLOQUE_MIN, BLOQUE_TEORIA_MAX, EntradaPlan, SesionPrevia, TemaPlan,
                                    generar_plan, minutos_criterio, minutos_tema)
from tests.conftest import casos_plan

HOY = date(2026, 10, 1)
SEMANA = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")


def horas(valor):
    return {d: valor for d in SEMANA}


def entrada(datos, dias=30, h=2, pct=50, temas=None, casos=None, **extra):
    return EntradaPlan(
        fecha_inicio=HOY, fecha_examen=HOY + timedelta(days=dias),
        horas_por_dia=h if isinstance(h, dict) else horas(h),
        porcentaje_tiempo_practica=pct,
        temas=temas if temas is not None else [TemaPlan(t.slug, t.nombre, t.nucleo, t.peso, t.dominio)
                                               for t in datos["temas"]],
        casos=casos if casos is not None else casos_plan(datos["casos_json"]),
        hoy=HOY, **extra,
    )


def capacidad(e, fecha):
    return int(round(float(e.horas_por_dia[SEMANA[fecha.weekday()]]) * 60))


# ---------------------------------------------------------------------------
def test_minutos_tema_y_criterio():
    assert minutos_tema(1.0) == 20            # mínimo 20
    assert minutos_tema(7.5) == 60            # 8 × 7.5
    assert minutos_tema(4.2) % 5 == 0
    assert minutos_criterio(0.5) == 45 and minutos_criterio(3.0) == 90


def test_30_dias_2h_genera_todas_las_fases(datos_banco):
    r = generar_plan(entrada(datos_banco))
    assert not r.modo_intensivo and not r.sin_plan
    fases = {s.fase for s in r.sesiones}
    assert fases == {"diagnostico", "cobertura", "refuerzo", "simulacro", "repaso_final"}
    diag = Counter(s.tipo for s in r.sesiones if s.fase == "diagnostico")
    assert diag["simulacro_nucleo"] == 4                     # teoría: 4 núcleos
    assert diag["intento_practico"] == 4                     # práctica: 1 por caso
    assert {s.caso_codigo for s in r.sesiones if s.fase == "diagnostico" and s.tipo == "intento_practico"} == \
        {"P1", "P2", "P3", "P4"}
    sim = Counter(s.tipo for s in r.sesiones if s.fase == "simulacro")
    assert sim["simulacro_completo"] >= 2 and sim["intento_practico"] == 4


def test_ningun_dia_excede_su_capacidad(datos_banco):
    for dias, h in ((30, 2), (15, 3), (10, 1.5), (45, 1)):
        e = entrada(datos_banco, dias=dias, h=h)
        for fecha, sesiones in generar_plan(e).por_fecha().items():
            assert sum(s.minutos for s in sesiones) <= capacidad(e, fecha)


@pytest.mark.parametrize("dias,h", [(30, 2), (10, 3), (7, 1), (20, {"lun": 2, "mar": 2, "mie": 0, "jue": 2,
                                                                      "vie": 2, "sab": 4, "dom": 0})])
def test_ultimo_dia_solo_repaso_ligero(datos_banco, dias, h):
    r = generar_plan(entrada(datos_banco, dias=dias, h=h))
    por_fecha = r.por_fecha()
    ultimo = max(por_fecha)
    assert [s.tipo for s in por_fecha[ultimo]] == ["repaso_ligero"]
    assert por_fecha[ultimo][0].minutos <= 60
    assert ultimo < HOY + timedelta(days=dias)


def test_penultimo_dia_simulacro_final(datos_banco):
    r = generar_plan(entrada(datos_banco, dias=30, h=3))
    fechas = sorted(r.por_fecha())
    tipos = [s.tipo for s in r.por_fecha()[fechas[-2]]]
    assert "simulacro_completo" in tipos and "defensa" in tipos


def test_examen_en_2_dias_modo_intensivo(datos_banco):
    r = generar_plan(entrada(datos_banco, dias=2, h=2))
    assert r.modo_intensivo
    assert any("Modo intensivo" in a["texto"] for a in r.advertencias)
    ultimo = max(r.por_fecha())
    assert [s.tipo for s in r.por_fecha()[ultimo]] == ["repaso_ligero"]


def test_tiempo_insuficiente_advierte_horas_y_sin_cubrir(datos_banco):
    r = generar_plan(entrada(datos_banco, dias=6, h=1))
    assert r.minutos_faltantes > 0
    textos = " ".join(a["texto"] for a in r.advertencias)
    assert "Tiempo insuficiente" in textos and "faltan aprox." in textos
    assert "Sin cubrir" in textos and "Temas" in textos
    assert any(a["nivel"] == "danger" for a in r.advertencias)


def test_se_deja_fuera_lo_de_menor_prioridad(datos_banco):
    temas = [TemaPlan(t.slug, t.nombre, t.nucleo, t.peso, t.dominio) for t in datos_banco["temas"]]
    r = generar_plan(entrada(datos_banco, dias=20, h=2, temas=temas))
    cubiertos = {s.tema_slug for s in r.sesiones if s.fase == "cobertura" and s.tema_slug}
    fuera = [t for t in temas if t.slug not in cubiertos]
    assert cubiertos and fuera
    assert min(t.prioridad for t in temas if t.slug in cubiertos) >= max(t.prioridad for t in fuera)


@pytest.mark.parametrize("dias", [0, -3])
def test_examen_hoy_o_pasado_sin_plan(datos_banco, dias):
    r = generar_plan(entrada(datos_banco, dias=dias))
    assert r.sin_plan and not r.sesiones and r.mensaje


def test_cero_horas_no_genera_sesiones(datos_banco):
    r = generar_plan(entrada(datos_banco, dias=10, h=0))
    assert not r.sesiones
    assert any("horas" in a["texto"] for a in r.advertencias)


def test_porcentaje_practica_cambia_el_reparto(datos_banco):
    poco = generar_plan(entrada(datos_banco, pct=20)).minutos_por_componente()
    mucho = generar_plan(entrada(datos_banco, pct=80)).minutos_por_componente()
    assert poco["teoria"] > poco["practica"]
    assert mucho["practica"] > mucho["teoria"]
    assert mucho["practica"] > poco["practica"]


def test_tema_con_fallos_sube_de_prioridad(datos_banco):
    temas = [TemaPlan(t.slug, t.nombre, t.nucleo, t.peso, 0.95) for t in datos_banco["temas"]]
    objetivo = next(t for t in temas if t.nombre == "Vistas")
    antes = generar_plan(entrada(datos_banco, temas=temas))
    orden_antes = [s.tema_slug for s in antes.sesiones if s.fase == "cobertura" and s.tema_slug]
    objetivo.dominio = 0.0                                    # muchos fallos en "Vistas"
    despues = generar_plan(entrada(datos_banco, temas=temas))
    orden_despues = [s.tema_slug for s in despues.sesiones if s.fase == "cobertura" and s.tema_slug]
    assert orden_despues[0] == objetivo.slug
    assert objetivo.slug not in orden_antes[:2]


def test_criterio_practico_bajo_agenda_practica_caso(datos_banco):
    pcts = {c["id"]: 100.0 for caso in datos_banco["casos_json"] for c in caso["rubrica"]}
    pcts["P1-R2"] = 20.0
    casos = casos_plan(datos_banco["casos_json"], notas={"P1": 8.0, "P2": 9, "P3": 9, "P4": 9}, pcts=pcts,
                       defensa={"P2": 100.0})
    r = generar_plan(entrada(datos_banco, casos=casos, nucleos_diagnosticados={1, 2, 3, 4}))
    sesiones = [s for s in r.sesiones if s.tipo == "practica_caso" and s.criterio_id == "P1-R2"]
    assert sesiones and sesiones[0].fase == "cobertura" and sesiones[0].caso_codigo == "P1"
    assert not any(s.tipo == "practica_caso" and s.criterio_id == "P1-R1" and s.fase == "cobertura"
                   for s in r.sesiones)


def test_atrasadas_se_reprograman_primero(datos_banco):
    atrasada = SesionPrevia(99, HOY - timedelta(days=2), 0, "cobertura", "tarjetas", "Tarjetas: Vistas", 20,
                            2, "n2-vistas")
    r = generar_plan(entrada(datos_banco, atrasadas=[atrasada]))
    reprogramada = [s for s in r.sesiones if s.id_existente == 99]
    assert len(reprogramada) == 1 and reprogramada[0].fecha == HOY and reprogramada[0].orden == 0
    assert not any(s.fase == "cobertura" and s.tipo == "tarjetas" and s.tema_slug == "n2-vistas"
                   and s.id_existente is None for s in r.sesiones)


def test_contenido_hecho_no_se_repite(datos_banco):
    r = generar_plan(entrada(datos_banco, hechas={("tarjetas", "n2-vistas"): 999, ("practica_tema", "n2-vistas"): 999}))
    assert not any(s.fase == "cobertura" and s.tema_slug == "n2-vistas" for s in r.sesiones)


def test_bloques_divididos_respetan_limites(datos_banco):
    # Un tema grande (tarjetas de 55 min) y días de 30 min: la sesión no cabe y se divide.
    temas = [TemaPlan("n4-grande", "Tema grande", 4, 20.0, 0.0)]
    r = generar_plan(entrada(datos_banco, dias=20, h=0.5, pct=0, temas=temas, casos=[],
                             nucleos_diagnosticados={1, 2, 3, 4}))
    partes = [s for s in r.sesiones if "(parte" in s.titulo]
    assert len(partes) >= 2, "la sesión que no cabe debe dividirse en bloques"
    assert sum(s.minutos for s in partes if s.tipo == "tarjetas" and s.fase == "cobertura") == 55
    for s in partes:
        assert BLOQUE_MIN <= s.minutos <= (90 if s.componente == "practica" else BLOQUE_TEORIA_MAX)


def test_un_solo_dia_plan_de_emergencia(datos_banco):
    r = generar_plan(entrada(datos_banco, dias=1, h=3))
    assert r.modo_intensivo
    sesiones = r.por_fecha()[HOY]
    assert sesiones[-1].tipo == "repaso_ligero"
    assert sum(s.minutos for s in sesiones) <= 180
