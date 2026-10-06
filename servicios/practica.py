"""Cálculos del módulo de práctica (casos P1–P4).

Reglas (sección 5):
  7. Nota de un intento práctico = Σ puntaje_final de sus criterios (máx. 10), autoevaluada.
  8. Nota de un caso = promedio de sus últimos 2 intentos completados válidos (o el único).
  9. Intento válido = completado, cronometrado y con todos los criterios con puntaje_final confirmado.
 10. La checklist solo SUGIERE el puntaje; el estudiante lo confirma.
"""
import math
from collections import defaultdict

from sqlalchemy.orm import selectinload

import config
from models import CasoPractico, IntentoPractico, RepasoDefensa

PASO_PUNTAJE = 0.25
AVISO_HONESTIDAD = "Marca una tarea solo si ejecutaste su verificación."
VALOR_DEFENSA = {"no_se": 0.0, "parcial": 0.5, "dominado": 1.0}


# ---------------------------------------------------------------------------
# Puntajes
# ---------------------------------------------------------------------------
def puntaje_sugerido(criterio, tareas_ok):
    """máximo × tareas marcadas / tareas del criterio (2 decimales)."""
    ids = [t["id"] for t in criterio["tareas"]]
    if not ids:
        return 0.0
    marcadas = set(tareas_ok or [])
    hechas = sum(1 for i in ids if i in marcadas)
    return round(float(criterio["puntaje"]) * hechas / len(ids), 2)


def redondear_a_paso(valor, paso=PASO_PUNTAJE):
    """Redondea HACIA ABAJO al múltiplo de 0.25 (prefijado conservador del puntaje final)."""
    return round(math.floor(valor / paso + 1e-9) * paso, 2)


def validar_puntaje(texto, maximo):
    """Valida un puntaje final escrito por el estudiante. Devuelve (valor, error)."""
    if texto is None or str(texto).strip() == "":
        return None, "Falta el puntaje."
    try:
        valor = float(str(texto).strip().replace(",", "."))
    except ValueError:
        return None, "El puntaje debe ser un número."
    if math.isnan(valor) or math.isinf(valor):
        return None, "El puntaje debe ser un número."
    if valor < 0:
        return None, "El puntaje no puede ser negativo."
    if valor > float(maximo) + 1e-9:
        return None, f"El puntaje no puede superar el máximo del criterio ({maximo:g})."
    if abs(valor / PASO_PUNTAJE - round(valor / PASO_PUNTAJE)) > 1e-6:
        return None, "El puntaje debe ir en pasos de 0.25."
    return round(valor, 2), None


def nota_de_evaluaciones(evaluaciones):
    """Σ puntaje_final acotado a su máximo; nunca supera 10."""
    total = 0.0
    for ev in evaluaciones:
        if ev.puntaje_final is None:
            continue
        total += min(max(ev.puntaje_final, 0.0), ev.puntaje_maximo)
    return round(min(total, 10.0), 2)


def pct_criterio(evaluacion):
    if not evaluacion.puntaje_maximo:
        return 0.0
    return round((evaluacion.puntaje_final or 0.0) / evaluacion.puntaje_maximo * 100, 1)


def color_pct(pct):
    """Verde >= 70 %, amarillo >= 50 %, rojo < 50 %."""
    if pct is None:
        return "secondary"
    if pct >= 70:
        return "success"
    if pct >= 50:
        return "warning"
    return "danger"


def semaforo(nota, nota_minima):
    """Verde >= mínima + margen, amarillo >= mínima, rojo < mínima, gris sin datos."""
    if nota is None:
        return "secondary"
    if nota >= nota_minima + config.MARGEN_SEGURIDAD:
        return "success"
    if nota >= nota_minima:
        return "warning"
    return "danger"


def nota_ajustada(nota):
    """Descuento conservador por autoevaluación (sección 12.2)."""
    if nota is None:
        return None
    return round(max(0.0, nota - config.DESCUENTO_AUTOEVALUACION), 2)


# ---------------------------------------------------------------------------
# Validez y notas
# ---------------------------------------------------------------------------
def es_intento_valido(intento, caso=None):
    caso = caso or intento.caso
    if not intento.completado or not intento.tiempo_limite_segundos or intento.fecha_fin is None:
        return False
    evaluadas = {ev.criterio_id for ev in intento.evaluaciones if ev.puntaje_final is not None}
    return all(c["id"] in evaluadas for c in caso.rubrica)


def cargar_intentos(usuario_id):
    """{caso_id: [IntentoPractico completados]} del más reciente al más antiguo (sin N+1)."""
    intentos = (
        IntentoPractico.query.options(selectinload(IntentoPractico.evaluaciones))
        .filter(IntentoPractico.usuario_id == usuario_id, IntentoPractico.completado.is_(True))
        .order_by(IntentoPractico.fecha_fin.desc(), IntentoPractico.id.desc())
        .all()
    )
    por_caso = defaultdict(list)
    for intento in intentos:
        por_caso[intento.caso_id].append(intento)
    return por_caso


def _validos(intentos, caso):
    return [i for i in intentos if es_intento_valido(i, caso)]


def _nota_de_validos(validos):
    ultimos = [i.nota_autoevaluada for i in validos[:2] if i.nota_autoevaluada is not None]
    if not ultimos:
        return None
    return round(sum(ultimos) / len(ultimos), 2)


def intentos_validos(usuario_id, caso, cache=None):
    cache = cache if cache is not None else cargar_intentos(usuario_id)
    return _validos(cache.get(caso.id, []), caso)


def nota_caso(usuario_id, caso, cache=None):
    """Promedio de los últimos 2 intentos válidos (o el único). None si no hay."""
    return _nota_de_validos(intentos_validos(usuario_id, caso, cache))


def nota_practica_promedio(usuario_id, casos=None, cache=None):
    """Promedio simple de las notas de los casos con intentos válidos."""
    casos = casos or CasoPractico.query.order_by(CasoPractico.codigo).all()
    cache = cache if cache is not None else cargar_intentos(usuario_id)
    notas = [n for n in (nota_caso(usuario_id, c, cache) for c in casos) if n is not None]
    return round(sum(notas) / len(notas), 2) if notas else None


def debilidad_por_criterio(usuario_id, caso, cache=None):
    """{criterio_id: % del máximo obtenido en el último intento válido} (None sin intentos)."""
    validos = intentos_validos(usuario_id, caso, cache)
    if not validos:
        return {c["id"]: None for c in caso.rubrica}
    evaluaciones = {ev.criterio_id: ev for ev in validos[0].evaluaciones}
    resultado = {}
    for criterio in caso.rubrica:
        ev = evaluaciones.get(criterio["id"])
        resultado[criterio["id"]] = pct_criterio(ev) if ev else None
    return resultado


# ---------------------------------------------------------------------------
# Defensa
# ---------------------------------------------------------------------------
def ultimos_niveles_defensa(usuario_id, caso):
    """{indice_pregunta: nivel} con el ÚLTIMO registro de cada pregunta de defensa."""
    registros = (
        RepasoDefensa.query.filter_by(usuario_id=usuario_id, caso_id=caso.id)
        .order_by(RepasoDefensa.fecha.asc(), RepasoDefensa.id.asc())
        .all()
    )
    niveles = {}
    for r in registros:
        niveles[r.indice_pregunta] = r.nivel
    return niveles


def dominio_defensa(usuario_id, caso, niveles=None):
    """% de preguntas cuyo último registro es 'dominado' (parcial cuenta 0.5)."""
    total = len(caso.defensa)
    if not total:
        return 0.0
    niveles = niveles if niveles is not None else ultimos_niveles_defensa(usuario_id, caso)
    puntos = sum(VALOR_DEFENSA.get(niveles.get(i), 0.0) for i in range(total))
    return round(puntos / total * 100, 1)


# ---------------------------------------------------------------------------
# Resúmenes para vistas, planificador y veredicto
# ---------------------------------------------------------------------------
def intento_pendiente(usuario_id):
    """El único intento práctico no completado del usuario (o None)."""
    return (
        IntentoPractico.query.filter_by(usuario_id=usuario_id, completado=False)
        .order_by(IntentoPractico.fecha_inicio.desc())
        .first()
    )


def resumen_casos(usuario_id, nota_minima):
    """Una fila por caso con intentos, notas, semáforo, criterios y defensa."""
    casos = CasoPractico.query.order_by(CasoPractico.codigo).all()
    cache = cargar_intentos(usuario_id)
    filas = []
    for caso in casos:
        completados = cache.get(caso.id, [])
        validos = _validos(completados, caso)
        notas = [i.nota_autoevaluada for i in completados if i.nota_autoevaluada is not None]
        nota = _nota_de_validos(validos)
        criterios = debilidad_por_criterio(usuario_id, caso, cache)
        filas.append({
            "caso": caso,
            "n_intentos": len(completados),
            "n_validos": len(validos),
            "ultima_nota": notas[0] if notas else None,
            "mejor_nota": max(notas) if notas else None,
            "nota_caso": nota,
            "nota_ajustada": nota_ajustada(nota),
            "semaforo": semaforo(nota, nota_minima),
            "criterios": criterios,
            "dominio_defensa": dominio_defensa(usuario_id, caso),
            "intentos": completados,
        })
    return filas


def criterios_mas_debiles(filas_casos, limite=None, incluir_sin_datos=False):
    """[(caso, criterio, pct)] ordenados por % ascendente (último intento válido)."""
    resultado = []
    for fila in filas_casos:
        caso = fila["caso"]
        for criterio in caso.rubrica:
            pct = fila["criterios"].get(criterio["id"])
            if pct is None and not incluir_sin_datos:
                continue
            resultado.append((caso, criterio, pct))
    resultado.sort(key=lambda t: (t[2] if t[2] is not None else -1, -t[1]["puntaje"]))
    return resultado[:limite] if limite else resultado


def notas_practicas_cronologicas(usuario_id):
    """[(fecha_fin, codigo_caso, nota)] de intentos válidos, cronológico (evolución)."""
    cache = cargar_intentos(usuario_id)
    casos = {c.id: c for c in CasoPractico.query.all()}
    puntos = []
    for caso_id, intentos in cache.items():
        caso = casos[caso_id]
        for intento in _validos(intentos, caso):
            puntos.append((intento.fecha_fin, caso.codigo, intento.nota_autoevaluada))
    puntos.sort(key=lambda t: t[0])
    return puntos
