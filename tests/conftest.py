"""Fixtures compartidas de pytest.

- `datos_banco`: temas y casos construidos desde data/*.json (para las funciones puras).
- `db_app`: app Flask mínima con SQLite en memoria y el banco sembrado (servicios con BD).
- `app` / `client`: la aplicación completa de create_app() (pruebas de extremo a extremo).
"""
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
from seed import tema_slug  # noqa: E402
from servicios.planificador import CasoPlan, CriterioPlan, TemaPlan  # noqa: E402


def _cargar(nombre):
    with open(RAIZ / "data" / nombre, encoding="utf-8") as archivo:
        return json.load(archivo)


@pytest.fixture(scope="session")
def datos_banco():
    preguntas = _cargar("preguntas.json")
    casos = _cargar("casos_practicos.json")
    temas = {}
    for q in preguntas:
        slug = tema_slug(q["nucleo"], q["tema"])
        tema = temas.setdefault(slug, TemaPlan(slug, q["tema"], q["nucleo"], 0.0, 0.0))
        tema.peso += config.FACTOR_NIVEL[q["nivel"]] * config.FACTOR_NUCLEO[q["nucleo"]]
    return {"temas": list(temas.values()), "casos_json": casos}


def casos_plan(casos_json, notas=None, pcts=None, validos=None, defensa=None):
    """CasoPlan desde el JSON con notas/porcentajes opcionales por caso y criterio."""
    notas, pcts, validos, defensa = notas or {}, pcts or {}, validos or {}, defensa or {}
    return [
        CasoPlan(
            codigo=c["codigo"], nucleo=c["nucleo"], titulo=c["titulo"],
            tiempo_sugerido_min=c["tiempo_sugerido_min"], nota=notas.get(c["codigo"]),
            n_validos=validos.get(c["codigo"], 1 if c["codigo"] in notas else 0),
            dominio_defensa=defensa.get(c["codigo"], 0.0),
            criterios=[CriterioPlan(r["id"], r["criterio"], float(r["puntaje"]), pcts.get(r["id"]),
                                    "defensa" in r["criterio"].lower()) for r in c["rubrica"]],
        )
        for c in casos_json
    ]


@pytest.fixture()
def db_app():
    from flask import Flask

    from extensions import db
    from seed import sembrar
    import models  # noqa: F401  (registra los modelos)

    app = Flask(__name__)
    app.config.from_object(config.TestingConfig)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        sembrar()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def app():
    """App completa con SQLite en memoria. No deja un app context abierto: cada petición del
    cliente usa el suyo (si no, Flask-Login reutilizaría `g` entre usuarios distintos)."""
    from app import create_app
    from extensions import db

    aplicacion = create_app(config.TestingConfig)
    yield aplicacion
    with aplicacion.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def otro_client(app):
    return app.test_client()
