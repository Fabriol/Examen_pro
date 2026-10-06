"""Estadísticas del banco teórico: dominio, falladas, cobertura y porcentajes.

Reglas (sección 5):
  1. Nota del intento = aciertos / total_preguntas * 10 (sobre el TOTAL asignado).
  2. En blanco (opcion_elegida NULL): no suma, no es "fallada" ni cuenta como respondida.
  3. % por tema/núcleo/nivel = aciertos / respondidas (excluye blancos).
  4. Fallada = su ÚLTIMA respuesta (por Intento.fecha_fin, solo completados) es incorrecta y no en blanco.
  5. Dominada = última respuesta correcta; dominada estable = últimas dos (intentos distintos) correctas.
  6. Cobertura = preguntas con al menos una respuesta no en blanco / 120.
"""
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import config
from extensions import db
from models import Intento, Pregunta, Respuesta

NOTA_PIE_PORCENTAJES = (
    "Los porcentajes por tema, núcleo y nivel excluyen las preguntas dejadas en blanco; "
    "la nota del intento se calcula sobre el total."
)


def calcular_nota(aciertos, total):
    """Nota /10 con 2 decimales sobre el total asignado."""
    if not total:
        return 0.0
    return round(aciertos / total * 10, 2)


def mensaje_motivacional(nota):
    if nota >= 9:
        return "success", "¡Excelente! Dominas este contenido; mantén el ritmo con simulacros completos."
    if nota >= 7:
        return "primary", "Bien. Vas por buen camino: repasa tus falladas para asegurar la nota."
    if nota >= 5:
        return "warning", "Necesitas reforzar. Estudia las tarjetas de tus temas más débiles y vuelve a intentarlo."
    return "danger", "Estudio intensivo: empieza por las tarjetas de cada tema y practica tema por tema."


def parametros_examen(usuario):
    """Nota mínima, pesos y fecha del examen: del plan activo si existe; si no, de config.py."""
    plan = usuario.plan_activo if usuario is not None else None
    if plan:
        return {
            "nota_minima": plan.nota_minima,
            "peso_teoria": plan.peso_teoria,
            "peso_practica": plan.peso_practica,
            "fecha_examen": plan.fecha_examen,
            "plan": plan,
        }
    fecha = None
    if config.FECHA_EXAMEN:
        try:
            fecha = date.fromisoformat(config.FECHA_EXAMEN)
        except ValueError:
            fecha = None
    return {
        "nota_minima": config.NOTA_MINIMA_APROBACION,
        "peso_teoria": config.PESO_TEORIA,
        "peso_practica": config.PESO_PRACTICA,
        "fecha_examen": fecha,
        "plan": None,
    }


# ---------------------------------------------------------------------------
# Historial de respuestas y estado por pregunta
# ---------------------------------------------------------------------------
def historial_respuestas(usuario_id):
    """{pregunta_id: [filas]} de la más reciente a la más antigua; solo intentos completados."""
    filas = (
        db.session.query(
            Respuesta.pregunta_id,
            Respuesta.opcion_elegida,
            Respuesta.es_correcta,
            Respuesta.intento_id,
            Intento.fecha_fin,
        )
        .join(Intento, Respuesta.intento_id == Intento.id)
        .filter(Intento.usuario_id == usuario_id, Intento.completado.is_(True))
        .order_by(Intento.fecha_fin.desc(), Intento.id.desc())
        .all()
    )
    historial = defaultdict(list)
    for fila in filas:
        historial[fila.pregunta_id].append(fila)
    return historial


@dataclass
class EstadoPregunta:
    respondida: bool = False          # al menos una respuesta no en blanco
    ultima: str | None = None         # 'correcta' | 'incorrecta' | 'blanco' | None (nunca vista)
    fallos: int = 0                   # respuestas incorrectas no en blanco (acumuladas)
    aciertos: int = 0
    respondidas: int = 0              # respuestas no en blanco (acumuladas)
    dominada_estable: bool = False

    @property
    def fallada(self):
        return self.ultima == "incorrecta"

    @property
    def dominada(self):
        return self.ultima == "correcta"


def _estado_desde_historial(filas):
    estado = EstadoPregunta()
    if not filas:
        return estado
    ultima = filas[0]
    if ultima.opcion_elegida is None:
        estado.ultima = "blanco"
    else:
        estado.ultima = "correcta" if ultima.es_correcta else "incorrecta"
    for fila in filas:
        if fila.opcion_elegida is None:
            continue
        estado.respondidas += 1
        if fila.es_correcta:
            estado.aciertos += 1
        else:
            estado.fallos += 1
    estado.respondida = estado.respondidas > 0
    estado.dominada_estable = len(filas) >= 2 and all(
        f.opcion_elegida is not None and f.es_correcta for f in filas[:2]
    )
    return estado


@dataclass
class Stat:
    aciertos: int = 0
    respondidas: int = 0

    @property
    def pct(self):
        return round(self.aciertos / self.respondidas * 100, 1) if self.respondidas else None


@dataclass
class TemaInfo:
    slug: str
    nombre: str
    nucleo: int
    total: int = 0
    dominadas: int = 0
    peso: float = 0.0
    stat: Stat = field(default_factory=Stat)
    pregunta_ids: list = field(default_factory=list)

    @property
    def dominio(self):
        """Fracción 0–1 de preguntas del tema cuya última respuesta es correcta."""
        return self.dominadas / self.total if self.total else 0.0

    @property
    def pct(self):
        return self.stat.pct


@dataclass
class ResumenTeoria:
    preguntas: list
    por_id: dict
    estados: dict
    por_nucleo: dict
    por_nivel: dict
    temas: dict

    @property
    def total_banco(self):
        return len(self.preguntas) or config.TOTAL_PREGUNTAS_BANCO

    @property
    def respondidas_unicas(self):
        return sum(1 for e in self.estados.values() if e.respondida)

    @property
    def cobertura_pct(self):
        return round(self.respondidas_unicas / self.total_banco * 100, 1)

    @property
    def dominadas(self):
        return sum(1 for e in self.estados.values() if e.dominada)

    @property
    def dominadas_estables(self):
        return sum(1 for e in self.estados.values() if e.dominada_estable)

    @property
    def dominio_estable_pct(self):
        return round(self.dominadas_estables / self.total_banco * 100, 1)

    @property
    def falladas_ids(self):
        """Preguntas falladas ahora mismo (regla 5.4), ordenadas por fallos acumulados."""
        ids = [pid for pid, e in self.estados.items() if e.fallada]
        return sorted(ids, key=lambda pid: (-self.estados[pid].fallos, self.por_id[pid].codigo))

    def ranking_fallos(self, limite=None):
        """[(pregunta, estado)] con fallos acumulados > 0, de más a menos fallos."""
        filas = [
            (self.por_id[pid], e) for pid, e in self.estados.items() if e.fallos > 0
        ]
        filas.sort(key=lambda t: (-t[1].fallos, not t[1].fallada, t[0].codigo))
        return filas[:limite] if limite else filas

    def temas_mas_debiles(self, limite=8):
        """Temas con menor % de acierto; si faltan, se completan con temas aún sin responder."""
        con_datos = sorted(
            (t for t in self.temas.values() if t.stat.respondidas),
            key=lambda t: (t.pct, -t.peso),
        )
        sin_datos = sorted(
            (t for t in self.temas.values() if not t.stat.respondidas),
            key=lambda t: (-t.peso, t.nombre),
        )
        return (con_datos + sin_datos)[:limite] if limite else con_datos + sin_datos

    def nucleo_mas_debil(self):
        """Núcleo con menor %; los núcleos sin datos cuentan como 0."""
        return min((1, 2, 3, 4), key=lambda n: (self.por_nucleo[n].pct or 0.0, n))


def peso_pregunta(pregunta):
    return config.FACTOR_NIVEL.get(pregunta.nivel, 1.0) * config.FACTOR_NUCLEO.get(pregunta.nucleo, 1.0)


def resumen_teoria(usuario_id):
    """Calcula en una sola pasada todo lo que necesitan dashboard, plan y veredicto."""
    preguntas = Pregunta.query.order_by(Pregunta.nucleo, Pregunta.codigo).all()
    historial = historial_respuestas(usuario_id)
    por_id = {p.id: p for p in preguntas}
    estados = {}
    por_nucleo = {n: Stat() for n in (1, 2, 3, 4)}
    por_nivel = {n: Stat() for n in ("facil", "medio", "dificil")}
    temas = {}

    for p in preguntas:
        estado = _estado_desde_historial(historial.get(p.id, []))
        estados[p.id] = estado
        tema = temas.get(p.tema_slug)
        if tema is None:
            tema = temas[p.tema_slug] = TemaInfo(slug=p.tema_slug, nombre=p.tema, nucleo=p.nucleo)
        tema.total += 1
        tema.peso += peso_pregunta(p)
        tema.pregunta_ids.append(p.id)
        if estado.dominada:
            tema.dominadas += 1
        for stat in (por_nucleo[p.nucleo], por_nivel[p.nivel], tema.stat):
            stat.aciertos += estado.aciertos
            stat.respondidas += estado.respondidas

    for tema in temas.values():
        tema.peso = round(tema.peso, 2)
    return ResumenTeoria(preguntas, por_id, estados, por_nucleo, por_nivel, temas)


# ---------------------------------------------------------------------------
# Intentos
# ---------------------------------------------------------------------------
def intentos_completados(usuario_id):
    return (
        Intento.query.filter(Intento.usuario_id == usuario_id, Intento.completado.is_(True))
        .order_by(Intento.fecha_fin.asc(), Intento.id.asc())
        .all()
    )


def notas_simulacros_validos(usuario_id):
    """[(fecha_fin, nota)] de simulacros válidos (>= MIN_PREGUNTAS_SIMULACRO_VALIDO), cronológico."""
    filas = (
        db.session.query(Intento.fecha_fin, Intento.nota)
        .filter(
            Intento.usuario_id == usuario_id,
            Intento.completado.is_(True),
            Intento.total_preguntas >= config.MIN_PREGUNTAS_SIMULACRO_VALIDO,
        )
        .order_by(Intento.fecha_fin.asc(), Intento.id.asc())
        .all()
    )
    return [(f.fecha_fin, f.nota) for f in filas]


def nucleos_diagnosticados(usuario_id):
    """Núcleos con al menos un simulacro completo o de ese núcleo ya finalizado."""
    filas = (
        db.session.query(Intento.modo, Intento.filtro)
        .filter(
            Intento.usuario_id == usuario_id,
            Intento.completado.is_(True),
            Intento.modo.in_(("completo", "nucleo")),
        )
        .all()
    )
    nucleos = set()
    for modo, filtro in filas:
        if modo == "completo":
            return {1, 2, 3, 4}
        if filtro and filtro.isdigit():
            nucleos.add(int(filtro))
    return nucleos


def preguntas_para_modo(usuario_id, modo, filtro=None):
    """Ids de preguntas (orden por código) para un modo de examen. Lista vacía si no hay."""
    consulta = Pregunta.query
    if modo == "completo":
        filas = consulta.order_by(Pregunta.codigo).all()
    elif modo == "nucleo":
        filas = consulta.filter(Pregunta.nucleo == int(filtro)).order_by(Pregunta.codigo).all()
    elif modo == "nivel":
        filas = consulta.filter(Pregunta.nivel == filtro).order_by(Pregunta.codigo).all()
    elif modo == "tema":
        filas = consulta.filter(Pregunta.tema_slug == filtro).order_by(Pregunta.codigo).all()
    elif modo == "fallidas":
        resumen = resumen_teoria(usuario_id)
        return sorted(resumen.falladas_ids, key=lambda pid: resumen.por_id[pid].codigo)
    else:
        return []
    return [p.id for p in filas]


def generar_orden_y_mapeo(pregunta_ids, aleatorio=True, barajar=True, rng=None):
    """Orden de preguntas y mapeo {"<id>": [pos mostrada -> índice original]}."""
    rng = rng or random.Random()
    orden = list(pregunta_ids)
    if aleatorio:
        rng.shuffle(orden)
    mapeo = {}
    for pid in orden:
        posiciones = [0, 1, 2, 3]
        if barajar:
            rng.shuffle(posiciones)
        mapeo[str(pid)] = posiciones
    return orden, mapeo


def mapeo_de(intento, pregunta_id):
    return intento.mapeo_opciones.get(str(pregunta_id)) or [0, 1, 2, 3]


def posicion_mostrada(intento, pregunta_id, indice_original):
    """Inverso del mapeo: índice original -> posición en pantalla (None si no hay)."""
    if indice_original is None:
        return None
    mapeo = mapeo_de(intento, pregunta_id)
    return mapeo.index(indice_original) if indice_original in mapeo else None


def construir_revision(intento):
    """Revisión en el orden y con las opciones tal como el estudiante las vio.

    Única función de revisión: la usan el resultado del examen y el dashboard.
    """
    ids = list(intento.orden_preguntas)
    preguntas = {p.id: p for p in Pregunta.query.filter(Pregunta.id.in_(ids)).all()}
    respuestas = {r.pregunta_id: r for r in intento.respuestas}
    items = []
    for numero, pid in enumerate(ids, start=1):
        pregunta = preguntas.get(pid)
        if pregunta is None:
            continue
        respuesta = respuestas.get(pid)
        elegida = respuesta.opcion_elegida if respuesta else None
        opciones = []
        for posicion, original in enumerate(mapeo_de(intento, pid)):
            es_correcta = original == pregunta.correcta
            es_elegida = elegida is not None and original == elegida
            if es_correcta:
                estado = "correcta"
            elif es_elegida:
                estado = "erronea"
            else:
                estado = "neutra"
            opciones.append({
                "letra": "ABCD"[posicion],
                "texto": pregunta.opciones[original],
                "es_correcta": es_correcta,
                "es_elegida": es_elegida,
                "estado": estado,
            })
        if elegida is None:
            resultado = "blanco"
        else:
            resultado = "correcta" if respuesta.es_correcta else "incorrecta"
        items.append({
            "numero": numero,
            "pregunta": pregunta,
            "opciones": opciones,
            "resultado": resultado,
            "segundos": respuesta.segundos_empleados if respuesta else 0,
        })
    return items


def desglose_intento(revision):
    """Aciertos/total/blancos por núcleo y por nivel a partir de construir_revision()."""
    por_nucleo = defaultdict(lambda: {"aciertos": 0, "total": 0, "blancos": 0})
    por_nivel = defaultdict(lambda: {"aciertos": 0, "total": 0, "blancos": 0})
    for item in revision:
        p = item["pregunta"]
        for grupo in (por_nucleo[p.nucleo], por_nivel[p.nivel]):
            grupo["total"] += 1
            if item["resultado"] == "correcta":
                grupo["aciertos"] += 1
            elif item["resultado"] == "blanco":
                grupo["blancos"] += 1
    for grupo in list(por_nucleo.values()) + list(por_nivel.values()):
        grupo["pct"] = round(grupo["aciertos"] / grupo["total"] * 100, 1) if grupo["total"] else 0.0
    orden_niveles = {"facil": 0, "medio": 1, "dificil": 2}
    return (
        dict(sorted(por_nucleo.items())),
        dict(sorted(por_nivel.items(), key=lambda kv: orden_niveles.get(kv[0], 9))),
    )
