"""Carga idempotente del banco teórico y de los casos prácticos desde data/.

Uso:  flask seed      (o bien)      python seed.py
Nunca modifica los JSON: los lee tal cual y solo inserta lo que falta (por `codigo`).
"""
import json
import logging
import re
import sys
import unicodedata
from collections import Counter

import click

for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        try:
            _flujo.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

from config import DATA_DIR, TOTAL_PREGUNTAS_BANCO  # noqa: E402
from extensions import db  # noqa: E402
from models import CasoPractico, Pregunta  # noqa: E402

log = logging.getLogger(__name__)

PREGUNTAS_POR_NUCLEO = 30
PREGUNTAS_POR_NIVEL = 40
CASOS_ESPERADOS = ("P1", "P2", "P3", "P4")


def slugify(texto):
    """'Índices y Vistas' -> 'indices-y-vistas'."""
    normalizado = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalizado.lower()).strip("-")


def tema_slug(nucleo, tema):
    return f"n{nucleo}-{slugify(tema)}"


def leer_json(nombre):
    with open(DATA_DIR / nombre, encoding="utf-8") as archivo:
        return json.load(archivo)


def validar_bd():
    """Comprueba lo que quedó cargado en la BD. Devuelve una lista de problemas (vacía = OK)."""
    problemas = []
    preguntas = Pregunta.query.all()
    if len(preguntas) != TOTAL_PREGUNTAS_BANCO:
        problemas.append(f"Hay {len(preguntas)} preguntas; se esperaban {TOTAL_PREGUNTAS_BANCO}.")
    por_nucleo = Counter(p.nucleo for p in preguntas)
    for nucleo in (1, 2, 3, 4):
        if por_nucleo.get(nucleo, 0) != PREGUNTAS_POR_NUCLEO:
            problemas.append(
                f"Núcleo {nucleo}: {por_nucleo.get(nucleo, 0)} preguntas (se esperaban {PREGUNTAS_POR_NUCLEO})."
            )
    por_nivel = Counter(p.nivel for p in preguntas)
    for nivel in ("facil", "medio", "dificil"):
        if por_nivel.get(nivel, 0) != PREGUNTAS_POR_NIVEL:
            problemas.append(
                f"Nivel {nivel}: {por_nivel.get(nivel, 0)} preguntas (se esperaban {PREGUNTAS_POR_NIVEL})."
            )
    for p in preguntas:
        if not isinstance(p.opciones, list) or len(p.opciones) != 4 or not 0 <= p.correcta <= 3:
            problemas.append(f"La pregunta {p.codigo} no tiene 4 opciones o su 'correcta' está fuera de 0–3.")

    casos = {c.codigo: c for c in CasoPractico.query.all()}
    if sorted(casos) != list(CASOS_ESPERADOS):
        problemas.append(f"Casos cargados: {sorted(casos)}; se esperaban {list(CASOS_ESPERADOS)}.")
    for codigo, caso in sorted(casos.items()):
        suma = round(sum(float(c["puntaje"]) for c in caso.rubrica), 4)
        if abs(suma - 10.0) > 1e-6:
            problemas.append(f"La rúbrica de {codigo} suma {suma}, no 10.0.")
    return problemas


def sembrar():
    """Inserta preguntas y casos que falten. Devuelve un resumen con los problemas detectados."""
    preguntas_json = leer_json("preguntas.json")
    casos_json = leer_json("casos_practicos.json")

    existentes = {p.codigo: p for p in Pregunta.query.all()}
    nuevas_preguntas = 0
    try:
        for dato in preguntas_json:
            if dato["id"] in existentes:
                continue
            pregunta = Pregunta(
                codigo=dato["id"],
                nucleo=int(dato["nucleo"]),
                nivel=dato["nivel"],
                tema=dato["tema"],
                tema_slug=tema_slug(dato["nucleo"], dato["tema"]),
                enunciado=dato["enunciado"],
                opciones=list(dato["opciones"]),
                correcta=int(dato["correcta"]),
            )
            db.session.add(pregunta)
            existentes[pregunta.codigo] = pregunta
            nuevas_preguntas += 1

        casos_existentes = {c.codigo: c for c in CasoPractico.query.all()}
        nuevos_casos = 0
        for dato in casos_json:
            if dato["codigo"] in casos_existentes:
                continue
            caso = CasoPractico(
                codigo=dato["codigo"],
                nucleo=int(dato["nucleo"]),
                titulo=dato["titulo"],
                tecnologia=dato["tecnologia"],
                tiempo_sugerido_min=int(dato["tiempo_sugerido_min"]),
                enunciado=dato["enunciado"],
                rubrica=dato["rubrica"],
                defensa=dato["defensa"],
                ambiguedades=dato["ambiguedades"],
                recursos=dato["recursos"],
            )
            db.session.add(caso)
            casos_existentes[caso.codigo] = caso
            nuevos_casos += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        log.exception("Error al sembrar la base de datos")
        raise

    return {
        "nuevas_preguntas": nuevas_preguntas,
        "nuevos_casos": nuevos_casos,
        "problemas": validar_bd(),
    }


def mensaje_resultado(resumen):
    if resumen["problemas"]:
        lineas = ["ADVERTENCIA: los datos cargados no cuadran con lo esperado:"]
        lineas += [f"  - {p}" for p in resumen["problemas"]]
        return "\n".join(lineas)
    return (
        f"✔ {TOTAL_PREGUNTAS_BANCO} preguntas y {len(CASOS_ESPERADOS)} casos prácticos cargados "
        f"({PREGUNTAS_POR_NUCLEO} por núcleo, {PREGUNTAS_POR_NIVEL} por nivel)"
    )


@click.command("seed")
def comando_seed():
    """Carga (sin duplicar) las 120 preguntas y los 4 casos prácticos."""
    resumen = sembrar()
    click.echo(
        f"Nuevas preguntas: {resumen['nuevas_preguntas']} · nuevos casos: {resumen['nuevos_casos']}"
    )
    click.echo(mensaje_resultado(resumen))


if __name__ == "__main__":
    from app import create_app

    aplicacion = create_app()
    with aplicacion.app_context():
        resultado = sembrar()
        click.echo(
            f"Nuevas preguntas: {resultado['nuevas_preguntas']} · nuevos casos: {resultado['nuevos_casos']}"
        )
        click.echo(mensaje_resultado(resultado))
