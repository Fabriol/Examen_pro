"""Plan de estudio personalizado (teoría + práctica): generación y recálculo (sección 10).

El núcleo es `generar_plan(EntradaPlan) -> ResultadoPlan`, una función PURA (sin BD) que se
prueba con pytest. Las funciones `crear_plan`, `recalcular_plan` y `estadisticas_plan`
leen/escriben la base de datos alrededor de ella.

Resumen del algoritmo (detalles en DECISIONES.md):
  1. Días de estudio = fechas entre inicio y examen-1 con horas > 0.
  2. Modo intensivo si quedan < 3 días de estudio.
  3. Modo normal:
     - último día: solo `repaso_ligero` (<= 60 min); penúltimo: simulacro final + defensa de P2;
     - sesiones atrasadas: se reprograman primero, en los próximos días con capacidad;
     - diagnóstico: 4 `simulacro_nucleo` + 1 `intento_practico` por caso sin línea base;
     - simulacros: `simulacro_completo` cada 3–4 días de estudio en el último tercio (mín. 2)
       y un `intento_practico` por caso;
     - el tiempo restante (flexible) se reparte teoría/práctica según `porcentaje_tiempo_practica`
       y, dentro de cada componente, 2/3 cobertura y 1/3 refuerzo (proporción 50:25);
     - lo que no cabe en cobertura se deja fuera por MENOR prioridad y va a advertencias.
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

import config
from models import DIAS_SEMANA, TIPOS_SESION_PRACTICA

PROPORCION_COBERTURA = 50 / (50 + 25)     # cobertura : refuerzo = 50 : 25
BLOQUE_MIN = 20
BLOQUE_TEORIA_MAX = 50
BLOQUE_PRACTICA_MAX = 90
UMBRAL_DOMINIO_TEMA = config.UMBRAL_DOMINIO_ESTABLE / 100   # 0.70
UMBRAL_CRITERIO = 70                      # % del máximo


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def redondear5(valor):
    return int(5 * round(valor / 5.0))


def minutos_tema(peso):
    """MIN_POR_PUNTO_PESO × peso, múltiplo de 5, mínimo 20."""
    return max(20, redondear5(config.MIN_POR_PUNTO_PESO * peso))


def minutos_criterio(puntaje):
    """Bloque de práctica de 45–90 min proporcional al puntaje del criterio."""
    return min(BLOQUE_PRACTICA_MAX, max(45, redondear5(config.MIN_POR_PUNTO_CRITERIO * puntaje)))


def dia_semana(fecha):
    return DIAS_SEMANA[fecha.weekday()]


def formatear_minutos(minutos):
    horas, resto = divmod(int(round(minutos)), 60)
    if horas and resto:
        return f"{horas} h {resto} min"
    if horas:
        return f"{horas} h"
    return f"{resto} min"


def advertencia(nivel, texto):
    return {"nivel": nivel, "texto": texto}


def es_practica(tipo):
    return tipo in TIPOS_SESION_PRACTICA


# ---------------------------------------------------------------------------
# Datos de entrada y salida (puros)
# ---------------------------------------------------------------------------
@dataclass
class TemaPlan:
    slug: str
    nombre: str
    nucleo: int
    peso: float
    dominio: float                       # 0–1

    @property
    def prioridad(self):
        return self.peso * (1 - self.dominio)


@dataclass
class CriterioPlan:
    id: str
    nombre: str
    puntaje: float
    pct: float | None = None             # % del máximo en el último intento válido
    es_defensa: bool = False

    @property
    def prioridad(self):
        return self.puntaje * (1 - (self.pct or 0) / 100)


@dataclass
class CasoPlan:
    codigo: str
    nucleo: int
    titulo: str
    tiempo_sugerido_min: int
    nota: float | None = None
    n_validos: int = 0
    criterios: list = field(default_factory=list)
    dominio_defensa: float = 0.0         # 0–100

    @property
    def prioridad(self):
        return 1.0 if self.nota is None else max(0.0, (10 - self.nota) / 10)

    @property
    def tiene_defensa(self):
        return any(c.es_defensa for c in self.criterios)


@dataclass
class SesionPrevia:
    """Sesión pendiente atrasada (fecha < hoy) que debe reprogramarse."""
    id: int
    fecha: date
    orden: int
    fase: str
    tipo: str
    titulo: str
    minutos: int
    nucleo: int | None = None
    tema_slug: str | None = None
    caso_codigo: str | None = None
    criterio_id: str | None = None


@dataclass
class EntradaPlan:
    fecha_inicio: date
    fecha_examen: date
    horas_por_dia: dict
    porcentaje_tiempo_practica: int
    temas: list
    casos: list
    hoy: date
    nucleos_diagnosticados: set = field(default_factory=set)
    n_falladas: int = 0
    nucleo_mas_debil: int = 2
    minutos_ocupados: dict = field(default_factory=dict)   # {fecha: minutos ya usados por sesiones conservadas}
    atrasadas: list = field(default_factory=list)          # [SesionPrevia]
    hechas: dict = field(default_factory=dict)             # {clave: minutos completados}


@dataclass
class SesionPlan:
    fecha: date
    orden: int
    fase: str
    tipo: str
    titulo: str
    minutos: int
    nucleo: int | None = None
    tema_slug: str | None = None
    caso_codigo: str | None = None
    criterio_id: str | None = None
    id_existente: int | None = None

    @property
    def componente(self):
        return "practica" if es_practica(self.tipo) else "teoria"


@dataclass
class ResultadoPlan:
    sesiones: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)
    modo_intensivo: bool = False
    sin_plan: bool = False
    mensaje: str = ""
    minutos_disponibles: int = 0
    minutos_faltantes: int = 0
    no_cubierto: list = field(default_factory=list)
    atrasadas_descartadas: list = field(default_factory=list)

    def minutos_por_componente(self):
        totales = {"teoria": 0, "practica": 0}
        for s in self.sesiones:
            totales[s.componente] += s.minutos
        return totales

    def por_fecha(self):
        dias = defaultdict(list)
        for s in self.sesiones:
            dias[s.fecha].append(s)
        return dict(sorted(dias.items()))


def clave_sesion(tipo, fase, tema_slug=None, criterio_id=None, caso_codigo=None, nucleo=None):
    """Identifica el "contenido" de una sesión para no duplicarlo al recalcular."""
    if fase == "cobertura" and tipo in ("tarjetas", "practica_tema"):
        return (tipo, tema_slug)
    if fase == "cobertura" and tipo == "practica_caso":
        return (tipo, criterio_id)
    if fase == "cobertura" and tipo == "defensa":
        return (tipo, caso_codigo)
    if fase == "simulacro" and tipo == "intento_practico":
        return ("intento_practico_sim", caso_codigo)
    if fase == "diagnostico" and tipo == "intento_practico":
        return ("intento_practico_diag", caso_codigo)
    if fase == "diagnostico" and tipo == "simulacro_nucleo":
        return ("simulacro_nucleo_diag", str(nucleo))
    return None


# ---------------------------------------------------------------------------
# Elementos internos
# ---------------------------------------------------------------------------
@dataclass
class _Item:
    fase: str
    tipo: str
    titulo: str
    minutos: int
    divisible: bool = False
    necesario: bool = True
    etiqueta: str = ""
    nucleo: int | None = None
    tema_slug: str | None = None
    caso_codigo: str | None = None
    criterio_id: str | None = None
    id_existente: int | None = None
    partes: int = 0

    @property
    def componente(self):
        return "practica" if es_practica(self.tipo) else "teoria"

    @property
    def clave(self):
        return clave_sesion(self.tipo, self.fase, self.tema_slug, self.criterio_id, self.caso_codigo, self.nucleo)


class _Calendario:
    def __init__(self, dias):
        self.fechas = [f for f, _ in dias]
        self.cap = dict(dias)
        self.usado = {f: 0 for f in self.fechas}
        self.sesiones = {f: [] for f in self.fechas}

    def libre(self, fecha):
        return self.cap.get(fecha, 0) - self.usado.get(fecha, 0)

    def colocar(self, fecha, item, minutos=None):
        minutos = item.minutos if minutos is None else minutos
        titulo = item.titulo
        if item.divisible and (item.partes or minutos < item.minutos):
            item.partes += 1
            titulo = f"{item.titulo} (parte {item.partes})"
        sesion = SesionPlan(
            fecha=fecha, orden=len(self.sesiones[fecha]), fase=item.fase, tipo=item.tipo,
            titulo=titulo[:200], minutos=minutos, nucleo=item.nucleo, tema_slug=item.tema_slug,
            caso_codigo=item.caso_codigo, criterio_id=item.criterio_id, id_existente=item.id_existente,
        )
        self.sesiones[fecha].append(sesion)
        self.usado[fecha] += minutos
        return sesion

    def primero_que_quepa(self, minutos, fechas):
        return next((f for f in fechas if self.libre(f) >= minutos), None)

    def minutos_de(self, componente):
        return sum(s.minutos for lista in self.sesiones.values() for s in lista if s.componente == componente)


# ---------------------------------------------------------------------------
# Generación (pura)
# ---------------------------------------------------------------------------
def _dias_con_horas(e, desde):
    dias = []
    actual = desde
    while actual < e.fecha_examen:
        horas = float(e.horas_por_dia.get(dia_semana(actual), 0) or 0)
        if horas > 0:
            dias.append((actual, int(round(horas * 60))))
        actual += timedelta(days=1)
    return dias


def generar_plan(e):
    """Genera las sesiones del plan a partir de un snapshot de datos. No toca la BD."""
    r = ResultadoPlan()
    if e.fecha_examen <= e.hoy:
        r.sin_plan = True
        r.mensaje = (
            "El examen es hoy: no se genera un plan. Descansa, repasa lo esencial y ¡mucho éxito!"
            if e.fecha_examen == e.hoy
            else "La fecha del examen ya pasó: no se genera un plan."
        )
        r.atrasadas_descartadas = [a.id for a in e.atrasadas]
        return r

    todos = _dias_con_horas(e, e.fecha_inicio)              # define las fases (fechas fijas)
    disponibles = [
        (f, cap - int(e.minutos_ocupados.get(f, 0)))
        for f, cap in _dias_con_horas(e, max(e.fecha_inicio, e.hoy))
    ]
    r.minutos_disponibles = sum(max(0, c) for _, c in disponibles)
    if not disponibles:
        r.advertencias.append(advertencia(
            "danger", "No quedan días con horas de estudio antes del examen: revisa tus horas por día."))
        r.atrasadas_descartadas = [a.id for a in e.atrasadas]
        return r

    cal = _Calendario([(f, max(0, c)) for f, c in disponibles])
    no_colocados = []
    r.modo_intensivo = len(disponibles) < 3
    if r.modo_intensivo:
        _plan_intensivo(e, cal, r, no_colocados)
    else:
        _plan_normal(e, cal, todos, r, no_colocados)

    r.sesiones = [s for f in cal.fechas for s in cal.sesiones[f]]
    _registrar_faltantes(r, no_colocados)
    return r


def _plan_normal(e, cal, todos, r, no_colocados):
    fechas_todas = [f for f, _ in todos]
    disponibles = set(cal.fechas)
    ultimo, penultimo = cal.fechas[-1], cal.fechas[-2]
    contenido_todo = [f for f in fechas_todas if f < penultimo] if len(fechas_todas) >= 3 else []
    contenido = [f for f in cal.fechas if f < penultimo]
    tercio_todo = contenido_todo[(len(contenido_todo) * 2) // 3:] or contenido_todo[-1:]
    tercio = [f for f in tercio_todo if f in disponibles] or contenido[-1:]

    _reservar_final(e, cal, ultimo, penultimo)
    excluir = dict(e.hechas)
    for clave, minutos in _reprogramar_atrasadas(e, cal, contenido, r).items():
        excluir[clave] = excluir.get(clave, 0) + minutos

    max_cap = max((cal.cap[f] for f in contenido), default=0)
    for item in _items_diagnostico(e, excluir, max_cap, r):
        fecha = cal.primero_que_quepa(item.minutos, contenido)
        if fecha:
            cal.colocar(fecha, item)
        else:
            no_colocados.append(item)

    _colocar_simulacros(e, cal, tercio_todo, tercio, excluir, r, no_colocados)

    # Tiempo flexible: reparto global teoría/práctica y 2/3 cobertura, 1/3 refuerzo.
    total = sum(cal.cap.values())
    objetivo_p = total * e.porcentaje_tiempo_practica / 100
    flex_p = max(0.0, objetivo_p - cal.minutos_de("practica"))
    flex_t = max(0.0, (total - objetivo_p) - cal.minutos_de("teoria"))
    libre = sum(cal.libre(f) for f in contenido)
    if flex_p + flex_t > libre > 0:
        factor = libre / (flex_p + flex_t)
        flex_p, flex_t = flex_p * factor, flex_t * factor
    elif libre <= 0:
        flex_p = flex_t = 0.0

    cola_t, fuera_t = _cola_teoria(e, excluir, flex_t)
    cola_p, fuera_p = _cola_practica(e, excluir, flex_p)
    no_colocados.extend(fuera_t + fuera_p)
    sobrantes = _llenar(cal, contenido, cola_t, cola_p, flex_t, flex_p)
    no_colocados.extend(i for i in sobrantes if i.necesario)


def _plan_intensivo(e, cal, r, no_colocados):
    r.advertencias.append(advertencia(
        "danger",
        f"Modo intensivo: quedan {len(cal.fechas)} día(s) de estudio. Plan de emergencia: diagnóstico "
        "rápido, preguntas falladas, criterios prácticos más débiles y repaso final.",
    ))
    fechas = list(cal.fechas)
    ultimo = fechas[-1]
    if len(fechas) >= 2:
        _reservar_repaso_ligero(cal, ultimo, cal.libre(ultimo))
        dias_trabajo = fechas[:-1]
    else:
        # Un único día: el repaso ligero se reserva al final de ese mismo día.
        minutos = min(config.DURACION_REPASO_LIGERO_MAX_MIN, max(15, redondear5(cal.cap[ultimo] * 0.25)))
        minutos = min(minutos, cal.cap[ultimo])
        cal.cap[ultimo] -= minutos
        dias_trabajo = fechas

    if e.atrasadas:
        r.atrasadas_descartadas = [a.id for a in e.atrasadas]
        r.advertencias.append(advertencia(
            "warning", f"{len(e.atrasadas)} sesión(es) atrasada(s) se sustituyeron por el plan de emergencia."))
    teoria = []
    for n in sorted({1, 2, 3, 4} - set(e.nucleos_diagnosticados), key=lambda x: (-config.FACTOR_NUCLEO[x], x)):
        teoria.append(_Item("diagnostico", "simulacro_nucleo", f"Diagnóstico rápido N{n} (30 preguntas)",
                            config.DURACION_SIMULACRO_NUCLEO_MIN, etiqueta=f"Diagnóstico N{n}", nucleo=n))
    teoria.append(_Item("refuerzo", "fallidas", "Practicar mis preguntas falladas",
                        config.DURACION_FALLIDAS_MIN, etiqueta="Preguntas falladas"))
    for t in sorted(e.temas, key=lambda t: (-t.prioridad, t.nombre))[:6]:
        teoria.append(_Item("refuerzo", "tarjetas", f"Tarjetas: {t.nombre}", config.DURACION_REPASO_TARJETAS_MIN,
                            divisible=True, necesario=False, etiqueta=t.nombre, nucleo=t.nucleo, tema_slug=t.slug))
    practica = []
    for caso in sorted(e.casos, key=lambda c: (-c.prioridad, c.codigo)):
        criterios = sorted((c for c in caso.criterios if not c.es_defensa),
                           key=lambda c: (-c.prioridad, -c.puntaje, c.id))
        if criterios:
            c = criterios[0]
            practica.append(_Item("refuerzo", "practica_caso", f"Práctica {caso.codigo}: {c.nombre}",
                                  minutos_criterio(c.puntaje), etiqueta=f"{c.id} {c.nombre}",
                                  caso_codigo=caso.codigo, criterio_id=c.id))
        if caso.tiene_defensa:
            practica.append(_Item("refuerzo", "defensa", f"Defensa {caso.codigo}: ensayo de preguntas",
                                  config.DURACION_DEFENSA_MIN, etiqueta=f"Defensa {caso.codigo}",
                                  caso_codigo=caso.codigo))
    total = sum(cal.cap[f] for f in dias_trabajo)
    flex_p = total * e.porcentaje_tiempo_practica / 100
    sobrantes = _llenar(cal, dias_trabajo, teoria, practica, total - flex_p, flex_p)
    no_colocados.extend(i for i in sobrantes if i.necesario)
    if len(fechas) == 1:
        cal.cap[ultimo] += minutos
        _reservar_repaso_ligero(cal, ultimo, minutos)


def _reservar_repaso_ligero(cal, fecha, maximo):
    minutos = min(config.DURACION_REPASO_LIGERO_MAX_MIN, maximo, cal.libre(fecha))
    if minutos >= 10:
        cal.colocar(fecha, _Item(
            "repaso_final", "repaso_ligero",
            "Repaso ligero: tarjetas de falladas y defensa · después, descansa", minutos,
            etiqueta="Repaso ligero"))


def _reservar_final(e, cal, ultimo, penultimo):
    _reservar_repaso_ligero(cal, ultimo, config.DURACION_REPASO_LIGERO_MAX_MIN)
    caso_defensa = next((c for c in e.casos if c.tiene_defensa), None)
    libre = cal.libre(penultimo)
    if libre >= config.DURACION_SIMULACRO_COMPLETO_MIN:
        cal.colocar(penultimo, _Item("repaso_final", "simulacro_completo", "Simulacro final completo (120 preguntas)",
                                     config.DURACION_SIMULACRO_COMPLETO_MIN, etiqueta="Simulacro final"))
    elif libre >= config.DURACION_SIMULACRO_NUCLEO_MIN:
        n = e.nucleo_mas_debil
        cal.colocar(penultimo, _Item("repaso_final", "simulacro_nucleo", f"Simulacro final del núcleo más débil (N{n})",
                                     config.DURACION_SIMULACRO_NUCLEO_MIN, etiqueta="Simulacro final", nucleo=n))
    if caso_defensa and cal.libre(penultimo) >= config.DURACION_DEFENSA_MIN:
        cal.colocar(penultimo, _Item("repaso_final", "defensa", f"Defensa {caso_defensa.codigo}: repaso final",
                                     config.DURACION_DEFENSA_MIN, etiqueta=f"Defensa {caso_defensa.codigo}",
                                     caso_codigo=caso_defensa.codigo))


def _reprogramar_atrasadas(e, cal, contenido, r):
    """Coloca las atrasadas (antes que lo nuevo) en los próximos días con capacidad."""
    cubiertas = defaultdict(int)
    for a in sorted(e.atrasadas, key=lambda a: (a.fecha, a.orden)):
        if a.fase == "repaso_final":
            r.atrasadas_descartadas.append(a.id)
            continue
        if a.tipo == "simulacro_nucleo" and a.fase == "diagnostico" and a.nucleo in e.nucleos_diagnosticados:
            r.atrasadas_descartadas.append(a.id)
            continue
        caso = next((c for c in e.casos if c.codigo == a.caso_codigo), None)
        if a.tipo == "intento_practico" and a.fase == "diagnostico" and caso and caso.n_validos > 0:
            r.atrasadas_descartadas.append(a.id)
            continue
        item = _Item(a.fase, a.tipo, a.titulo, a.minutos, etiqueta=a.titulo, nucleo=a.nucleo,
                     tema_slug=a.tema_slug, caso_codigo=a.caso_codigo, criterio_id=a.criterio_id,
                     id_existente=a.id)
        fecha = cal.primero_que_quepa(a.minutos, contenido)
        if fecha:
            cal.colocar(fecha, item)
            if item.clave:
                cubiertas[item.clave] += a.minutos
        else:
            r.atrasadas_descartadas.append(a.id)
            r.advertencias.append(advertencia(
                "warning", f"Sesión atrasada sin espacio para reprogramar: {a.titulo} ({a.fecha.isoformat()})."))
    return cubiertas


def _truncar(minutos, maximo, r, avisados):
    if minutos <= maximo or maximo <= 0:
        return minutos
    ajustado = max(5, (maximo // 5) * 5)
    if "truncado" not in avisados:
        avisados.add("truncado")
        r.advertencias.append(advertencia(
            "warning",
            f"Tu día de estudio más largo tiene {formatear_minutos(maximo)} y los intentos prácticos sugieren "
            f"{formatear_minutos(minutos)}: se agendaron con {formatear_minutos(ajustado)}. "
            "Puedes ajustar el tiempo al iniciarlos o subir las horas de algún día.",
        ))
    return ajustado


def _items_diagnostico(e, excluir, max_cap, r):
    avisados = set()
    teoria = [
        _Item("diagnostico", "simulacro_nucleo", f"Diagnóstico N{n}: simulacro de núcleo (30 preguntas)",
              config.DURACION_SIMULACRO_NUCLEO_MIN, etiqueta=f"Diagnóstico N{n}", nucleo=n)
        for n in (1, 2, 3, 4)
        if n not in e.nucleos_diagnosticados and ("simulacro_nucleo_diag", str(n)) not in excluir
    ]
    practica = []
    for caso in sorted(e.casos, key=lambda c: c.codigo):
        if caso.n_validos > 0 or ("intento_practico_diag", caso.codigo) in excluir:
            continue
        minutos = _truncar(caso.tiempo_sugerido_min, max_cap, r, avisados)
        practica.append(_Item("diagnostico", "intento_practico",
                              f"Diagnóstico {caso.codigo}: intento cronometrado (línea base)", minutos,
                              etiqueta=f"Intento diagnóstico {caso.codigo}", caso_codigo=caso.codigo))
    intercalados = []
    for i in range(max(len(teoria), len(practica))):
        if i < len(teoria):
            intercalados.append(teoria[i])
        if i < len(practica):
            intercalados.append(practica[i])
    return intercalados


def _colocar_simulacros(e, cal, tercio_todo, tercio, excluir, r, no_colocados):
    if not tercio_todo:
        return
    disponibles = set(tercio)
    paso = 3 if len(tercio_todo) <= 9 else 4
    fechas_objetivo = tercio_todo[::paso]
    if len(fechas_objetivo) < 2 and len(tercio_todo) >= 2:
        fechas_objetivo = [tercio_todo[0], tercio_todo[-1]]
    usados = set()
    sustituido = False
    for objetivo in fechas_objetivo:
        if objetivo < min(cal.fechas):
            continue                                     # simulacro de un día ya pasado
        cercanos = sorted((f for f in tercio if f not in usados), key=lambda f: (abs((f - objetivo).days), f))
        destino = next((f for f in cercanos if cal.libre(f) >= config.DURACION_SIMULACRO_COMPLETO_MIN), None)
        if destino:
            cal.colocar(destino, _Item("simulacro", "simulacro_completo", "Simulacro teórico completo (120 preguntas)",
                                       config.DURACION_SIMULACRO_COMPLETO_MIN, etiqueta="Simulacro completo"))
            usados.add(destino)
            continue
        destino = next((f for f in cercanos if cal.libre(f) >= config.DURACION_SIMULACRO_NUCLEO_MIN), None)
        if destino:
            n = e.nucleo_mas_debil
            cal.colocar(destino, _Item("simulacro", "simulacro_nucleo", f"Simulacro del núcleo N{n}",
                                       config.DURACION_SIMULACRO_NUCLEO_MIN, etiqueta=f"Simulacro N{n}", nucleo=n))
            usados.add(destino)
            sustituido = True
        else:
            no_colocados.append(_Item("simulacro", "simulacro_completo", "Simulacro teórico completo",
                                      config.DURACION_SIMULACRO_COMPLETO_MIN, etiqueta="Simulacro completo"))
    if sustituido:
        r.advertencias.append(advertencia(
            "warning", "Algunos días del último tercio tienen menos de 2 h: parte de los simulacros completos "
                       "se sustituyó por simulacros de núcleo."))

    max_cap = max((cal.cap[f] for f in tercio if f in disponibles), default=0)
    avisados = {"truncado"} if any(a["texto"].startswith("Tu día de estudio más largo") for a in r.advertencias) else set()
    for caso in sorted(e.casos, key=lambda c: (-c.prioridad, c.codigo)):
        if ("intento_practico_sim", caso.codigo) in excluir:
            continue
        minutos = _truncar(caso.tiempo_sugerido_min, max_cap, r, avisados)
        item = _Item("simulacro", "intento_practico", f"Simulacro práctico {caso.codigo}: intento cronometrado completo",
                     minutos, etiqueta=f"Simulacro práctico {caso.codigo}", caso_codigo=caso.codigo)
        fecha = cal.primero_que_quepa(minutos, tercio)
        if fecha:
            cal.colocar(fecha, item)
        else:
            no_colocados.append(item)


def _descontar(item, excluir):
    """Resta los minutos ya hechos de ese contenido; None si ya está cubierto."""
    hechos = excluir.get(item.clave, 0) if item.clave else 0
    if hechos >= item.minutos:
        return None
    if hechos:
        item.minutos = max(10, redondear5(item.minutos - hechos))
    return item


def _cola_teoria(e, excluir, presupuesto):
    """Cobertura por prioridad (hasta 2/3 del presupuesto) + refuerzo que rellena el resto."""
    limite_cob = presupuesto * PROPORCION_COBERTURA
    temas = sorted((t for t in e.temas if t.dominio < 1.0), key=lambda t: (-t.prioridad, -t.peso, t.nombre))
    cobertura, fuera, cubiertos = [], [], []
    usado = 0
    cortado = False
    for t in temas:
        m = minutos_tema(t.peso)
        m_tarjetas = max(10, redondear5(0.35 * m))
        m_practica = max(10, m - m_tarjetas)
        necesario = t.dominio < UMBRAL_DOMINIO_TEMA      # >= 70 % no cuenta como faltante
        items = [
            _descontar(_Item("cobertura", "tarjetas", f"Tarjetas: {t.nombre}", m_tarjetas, divisible=True,
                             necesario=necesario, etiqueta=t.nombre, nucleo=t.nucleo, tema_slug=t.slug), excluir),
            _descontar(_Item("cobertura", "practica_tema", f"Práctica del tema: {t.nombre}", m_practica,
                             necesario=necesario, etiqueta=t.nombre, nucleo=t.nucleo, tema_slug=t.slug), excluir),
        ]
        items = [i for i in items if i is not None]
        if not items:
            cubiertos.append(t)
            continue
        minutos = sum(i.minutos for i in items)
        if not cortado and usado + minutos <= limite_cob:
            cobertura.extend(items)
            usado += minutos
            cubiertos.append(t)
        elif not cortado and items[0].tipo == "tarjetas" and usado + items[0].minutos <= limite_cob:
            # Cobertura parcial del tema de mayor prioridad restante: al menos sus tarjetas.
            cortado = True
            cobertura.append(items[0])
            usado += items[0].minutos
            cubiertos.append(t)
            fuera.extend(items[1:])
        else:
            cortado = True
            fuera.extend(items)

    refuerzo = []
    restante = presupuesto - usado
    debiles = [t for t in sorted(cubiertos, key=lambda t: (-t.prioridad, t.nombre)) if t.dominio < UMBRAL_DOMINIO_TEMA]
    if not debiles:
        debiles = sorted(cubiertos, key=lambda t: (t.dominio, t.nombre))
    ciclo, acumulado, guardia = 0, 0, 0
    while acumulado < restante + BLOQUE_MIN and guardia < 400:
        guardia += 1
        if ciclo % 4 == 0 or not debiles:
            item = _Item("refuerzo", "fallidas", "Practicar mis preguntas falladas", config.DURACION_FALLIDAS_MIN,
                         necesario=False, etiqueta="Preguntas falladas")
        else:
            t = debiles[(ciclo - 1 - ciclo // 4) % len(debiles)]
            item = _Item("refuerzo", "tarjetas", f"Repaso de tarjetas: {t.nombre}", config.DURACION_REPASO_TARJETAS_MIN,
                         necesario=False, etiqueta=t.nombre, nucleo=t.nucleo, tema_slug=t.slug)
        refuerzo.append(item)
        acumulado += item.minutos
        ciclo += 1
    return cobertura + refuerzo, fuera


def _rondas_criterios(casos, filtro, fase, prefijo, excluir):
    por_caso = []
    for caso in casos:
        criterios = sorted((c for c in caso.criterios if not c.es_defensa and filtro(c)),
                           key=lambda c: (-c.prioridad, -c.puntaje, c.id))
        por_caso.append((caso, criterios))
    rondas = []
    for indice in range(max((len(c) for _, c in por_caso), default=0)):
        ronda = []
        for caso, criterios in por_caso:
            if indice < len(criterios):
                c = criterios[indice]
                item = _descontar(_Item(fase, "practica_caso", f"{prefijo} {caso.codigo}: {c.nombre}",
                                        minutos_criterio(c.puntaje), necesario=(fase == "cobertura"),
                                        etiqueta=f"{c.id} · {c.nombre}", caso_codigo=caso.codigo,
                                        criterio_id=c.id), excluir if fase == "cobertura" else {})
                if item:
                    ronda.append(item)
        rondas.append(ronda)
    return rondas


def _defensa(caso, fase, necesario=True):
    return _Item(fase, "defensa", f"Defensa {caso.codigo}: ensayo de preguntas", config.DURACION_DEFENSA_MIN,
                 necesario=necesario, etiqueta=f"Defensa {caso.codigo}", caso_codigo=caso.codigo)


def _cola_practica(e, excluir, presupuesto):
    """Cobertura: criterio más débil de cada caso (ronda a ronda) + defensa; refuerzo rellena."""
    limite_cob = presupuesto * PROPORCION_COBERTURA
    casos = sorted(e.casos, key=lambda c: (-c.prioridad, c.codigo))
    debil = lambda c: c.pct is None or c.pct < UMBRAL_CRITERIO  # noqa: E731
    rondas = _rondas_criterios(casos, debil, "cobertura", "Práctica", excluir)
    alta = [_defensa(c, "cobertura") for c in casos
            if c.tiene_defensa and c.dominio_defensa < config.UMBRAL_DEFENSA and ("defensa", c.codigo) not in excluir]
    media = [_defensa(c, "cobertura") for c in casos
             if not c.tiene_defensa and c.dominio_defensa < config.UMBRAL_DEFENSA and ("defensa", c.codigo) not in excluir]
    # Defensa de P2 (vale 3 de 10) = prioridad alta: va primero; la de los demás casos, tras la 1.ª ronda.
    secuencia = list(alta)
    for indice, ronda in enumerate(rondas):
        secuencia.extend(ronda)
        if indice == 0:
            secuencia.extend(media)
    if not rondas:
        secuencia.extend(media)

    cobertura, fuera = [], []
    usado = 0
    cortado = False
    for item in secuencia:
        if not cortado and usado + item.minutos <= limite_cob:
            cobertura.append(item)
            usado += item.minutos
        else:
            cortado = True
            fuera.append(item)
    criterios_cubiertos = {i.criterio_id for i in cobertura if i.criterio_id} | {
        k[1] for k in excluir if k and k[0] == "practica_caso"}

    refuerzo = []
    restante = presupuesto - usado
    base = [i for ronda in _rondas_criterios(casos, debil, "refuerzo", "Refuerzo", {}) for i in ronda
            if i.criterio_id in criterios_cubiertos]
    if not base:
        base = [i for ronda in _rondas_criterios(casos, lambda c: (c.pct or 0) < 100, "refuerzo", "Refuerzo", {})
                for i in ronda]
    defensas_cubiertas = {i.caso_codigo for i in cobertura if i.tipo == "defensa"} | {
        k[1] for k in excluir if k and k[0] == "defensa"}
    defensa_ref = [_defensa(c, "refuerzo", necesario=False) for c in casos
                   if c.tiene_defensa and c.dominio_defensa < config.UMBRAL_DEFENSA and c.codigo in defensas_cubiertas]
    acumulado, indice, guardia = 0, 0, 0
    fuentes = base + defensa_ref
    while fuentes and acumulado < restante + BLOQUE_MIN and guardia < 400:
        guardia += 1
        plantilla = fuentes[indice % len(fuentes)]
        item = _Item(plantilla.fase, plantilla.tipo, plantilla.titulo, plantilla.minutos, necesario=False,
                     etiqueta=plantilla.etiqueta, caso_codigo=plantilla.caso_codigo, criterio_id=plantilla.criterio_id)
        refuerzo.append(item)
        acumulado += item.minutos
        indice += 1
    return cobertura + refuerzo, fuera


def _tomar_uno(cal, fecha, cola):
    """Coloca en `fecha` el primer elemento de la cola que quepa (dividiendo si se puede)."""
    if not cola:
        return 0
    libre = cal.libre(fecha)
    item = cola[0]
    if item.minutos <= libre:
        cola.pop(0)
        cal.colocar(fecha, item)
        return item.minutos
    if item.divisible and libre >= BLOQUE_MIN:
        maximo = BLOQUE_PRACTICA_MAX if item.componente == "practica" else BLOQUE_TEORIA_MAX
        bloque = (min(libre, maximo) // 5) * 5
        if 0 < item.minutos - bloque < BLOQUE_MIN:
            bloque = item.minutos - BLOQUE_MIN
        if bloque >= BLOQUE_MIN:
            cal.colocar(fecha, item, minutos=bloque)
            item.minutos -= bloque
            return bloque
    for indice in range(1, min(len(cola), 15)):
        candidato = cola[indice]
        if candidato.fase != item.fase:
            break                                   # no adelantar refuerzo antes de acabar la cobertura
        if candidato.minutos <= libre:
            cola.pop(indice)
            cal.colocar(fecha, candidato)
            return candidato.minutos
    return 0


def _llenar(cal, fechas, cola_t, cola_p, objetivo_t, objetivo_p):
    """Llena los días en orden; en cada hueco coloca primero el componente (teoría/práctica)
    más atrasado respecto a su objetivo global. Si una cola se vacía, la otra aprovecha el hueco."""
    asignado = {"teoria": 0, "practica": 0}
    objetivo = {"teoria": objetivo_t, "practica": objetivo_p}
    colas = {"teoria": cola_t, "practica": cola_p}

    def avance(componente):
        return asignado[componente] / objetivo[componente] if objetivo[componente] > 0 else float("inf")

    for fecha in fechas:
        guardia = 0
        while cal.libre(fecha) >= 5 and (cola_t or cola_p) and guardia < 300:
            guardia += 1
            colocado = 0
            for componente in sorted(("practica", "teoria"), key=avance):
                colocado = _tomar_uno(cal, fecha, colas[componente])
                if colocado:
                    asignado[componente] += colocado
                    break
            if not colocado:
                break
    return cola_t + cola_p


def _registrar_faltantes(r, no_colocados):
    necesarios = [i for i in no_colocados if i.necesario]
    if not necesarios:
        return
    r.minutos_faltantes = sum(i.minutos for i in necesarios)
    temas, criterios, otros = [], [], []
    for i in necesarios:
        if i.tipo in ("tarjetas", "practica_tema"):
            if i.etiqueta not in temas:
                temas.append(i.etiqueta)
        elif i.tipo in ("practica_caso", "defensa"):
            if i.etiqueta not in criterios:
                criterios.append(i.etiqueta)
        elif i.etiqueta not in otros:
            otros.append(i.etiqueta)
    def resumir(nombres, maximo=12):
        texto = ", ".join(nombres[:maximo])
        return texto + (f" y {len(nombres) - maximo} más" if len(nombres) > maximo else "")

    partes = []
    if temas:
        partes.append(f"Temas ({len(temas)}): " + resumir(temas))
    if criterios:
        partes.append(f"Práctica ({len(criterios)}): " + resumir(criterios))
    if otros:
        partes.append(f"Sesiones ({len(otros)}): " + resumir(otros))
    r.no_cubierto = partes
    cabecera = advertencia(
        "danger",
        f"Tiempo insuficiente: faltan aprox. {formatear_minutos(r.minutos_faltantes)} para cubrir todo lo "
        "prioritario. Se dejó fuera lo de menor prioridad (se recalcula tras cada intento):",
    )
    r.advertencias = [cabecera] + [advertencia("danger", "Sin cubrir → " + p) for p in partes] + r.advertencias


# ---------------------------------------------------------------------------
# Capa de base de datos
# ---------------------------------------------------------------------------
def construir_entrada(usuario, plan, hoy):
    from servicios import estadisticas
    from servicios import practica as srv_practica
    from models import CasoPractico, Intento, IntentoPractico

    resumen = estadisticas.resumen_teoria(usuario.id)
    temas = [TemaPlan(t.slug, t.nombre, t.nucleo, t.peso, t.dominio) for t in resumen.temas.values()]
    casos = []
    for fila in srv_practica.resumen_casos(usuario.id, plan.nota_minima):
        caso = fila["caso"]
        casos.append(CasoPlan(
            codigo=caso.codigo, nucleo=caso.nucleo, titulo=caso.titulo,
            tiempo_sugerido_min=caso.tiempo_sugerido_min or config.TIEMPO_PRACTICA_DEFAULT_MIN,
            nota=fila["nota_caso"], n_validos=fila["n_validos"], dominio_defensa=fila["dominio_defensa"],
            criterios=[CriterioPlan(c["id"], c["criterio"], float(c["puntaje"]), fila["criterios"].get(c["id"]),
                                    CasoPractico.es_criterio_defensa(c)) for c in caso.rubrica],
        ))

    # Sesiones ligadas a un intento en curso: se conservan como si estuvieran hechas.
    en_curso = {i.sesion_id for i in Intento.query.filter_by(usuario_id=usuario.id, completado=False) if i.sesion_id}
    en_curso |= {i.sesion_id for i in IntentoPractico.query.filter_by(usuario_id=usuario.id, completado=False)
                 if i.sesion_id}
    ocupados, hechas, atrasadas = defaultdict(int), defaultdict(int), []
    for s in plan.sesiones:
        conservada = s.estado != "pendiente" or s.id in en_curso
        if conservada:
            if s.fecha >= hoy:
                ocupados[s.fecha] += s.minutos_reales or s.minutos_planificados
            clave = clave_sesion(s.tipo, s.fase, s.tema_slug, s.criterio_id, s.caso_codigo, s.nucleo)
            if clave and (s.estado == "completada" or s.id in en_curso):
                hechas[clave] += s.minutos_planificados
        elif s.fecha < hoy:
            atrasadas.append(SesionPrevia(s.id, s.fecha, s.orden, s.fase, s.tipo, s.titulo, s.minutos_planificados,
                                          s.nucleo, s.tema_slug, s.caso_codigo, s.criterio_id))
    return EntradaPlan(
        fecha_inicio=plan.fecha_inicio, fecha_examen=plan.fecha_examen, horas_por_dia=plan.horas_por_dia,
        porcentaje_tiempo_practica=plan.porcentaje_tiempo_practica, temas=temas, casos=casos, hoy=hoy,
        nucleos_diagnosticados=estadisticas.nucleos_diagnosticados(usuario.id),
        n_falladas=len(resumen.falladas_ids), nucleo_mas_debil=resumen.nucleo_mas_debil(),
        minutos_ocupados=dict(ocupados), atrasadas=atrasadas, hechas=dict(hechas),
    )


def aplicar_resultado(plan, resultado, hoy, conservar_ids=()):
    from extensions import db
    from models import SesionEstudio, ahora

    colocadas = {s.id_existente for s in resultado.sesiones if s.id_existente}
    conservar = set(conservar_ids)
    for s in list(plan.sesiones):
        if s.estado != "pendiente" or s.id in conservar or s.id in colocadas:
            continue
        # Pendiente futura (se regenera) o atrasada sin espacio (pasó a advertencias).
        plan.sesiones.remove(s)
        db.session.delete(s)
    existentes = {s.id: s for s in plan.sesiones}
    max_orden = defaultdict(lambda: -1)
    for s in plan.sesiones:
        if s.id not in colocadas:
            max_orden[s.fecha] = max(max_orden[s.fecha], s.orden)
    for sp in resultado.sesiones:
        orden = max_orden[sp.fecha] + 1 + sp.orden
        if sp.id_existente and sp.id_existente in existentes:
            fila = existentes[sp.id_existente]
            fila.fecha, fila.orden = sp.fecha, orden
        else:
            plan.sesiones.append(SesionEstudio(
                fecha=sp.fecha, orden=orden, fase=sp.fase, tipo=sp.tipo, nucleo=sp.nucleo,
                tema_slug=sp.tema_slug, caso_codigo=sp.caso_codigo, criterio_id=sp.criterio_id,
                titulo=sp.titulo, minutos_planificados=sp.minutos, estado="pendiente",
            ))
    avisos = list(resultado.advertencias)
    if resultado.sin_plan and resultado.mensaje:
        avisos.insert(0, advertencia("info", resultado.mensaje))
    plan.advertencias = avisos
    plan.ultima_recalculacion = ahora()


def _sesiones_en_curso(usuario):
    from models import Intento, IntentoPractico
    ids = {i.sesion_id for i in Intento.query.filter_by(usuario_id=usuario.id, completado=False) if i.sesion_id}
    ids |= {i.sesion_id for i in IntentoPractico.query.filter_by(usuario_id=usuario.id, completado=False)
            if i.sesion_id}
    return ids


def crear_plan(usuario, datos, hoy=None):
    """Crea el plan activo (desactiva el anterior sin borrar su historial) y genera sus sesiones."""
    from extensions import db
    from models import PlanEstudio

    hoy = hoy or date.today()
    for anterior in PlanEstudio.query.filter_by(usuario_id=usuario.id, activo=True).all():
        anterior.activo = False
    plan = PlanEstudio(
        usuario_id=usuario.id,
        fecha_inicio=datos["fecha_inicio"],
        fecha_examen=datos["fecha_examen"],
        horas_por_dia=datos["horas_por_dia"],
        nota_minima=datos["nota_minima"],
        peso_teoria=datos["peso_teoria"],
        peso_practica=datos["peso_practica"],
        porcentaje_tiempo_practica=datos["porcentaje_tiempo_practica"],
        activo=True,
        advertencias=[],
    )
    db.session.add(plan)
    db.session.flush()
    resultado = generar_plan(construir_entrada(usuario, plan, hoy))
    aplicar_resultado(plan, resultado, hoy)
    db.session.commit()
    return plan, resultado


def recalcular_plan(plan, hoy=None):
    """Conserva completadas/omitidas; regenera las pendientes desde hoy y reprograma atrasadas."""
    from extensions import db

    hoy = hoy or date.today()
    usuario = plan.usuario
    resultado = generar_plan(construir_entrada(usuario, plan, hoy))
    aplicar_resultado(plan, resultado, hoy, conservar_ids=_sesiones_en_curso(usuario))
    db.session.commit()
    return resultado


def recalcular_plan_usuario(usuario, hoy=None):
    plan = usuario.plan_activo
    if plan is None:
        return None
    return recalcular_plan(plan, hoy)


def capacidad_restante(plan, hoy):
    """Minutos de estudio disponibles desde hoy hasta el día antes del examen."""
    total = 0
    actual = max(hoy, plan.fecha_inicio)
    while actual < plan.fecha_examen:
        total += int(round(float(plan.horas_por_dia.get(dia_semana(actual), 0) or 0) * 60))
        actual += timedelta(days=1)
    return total


def estadisticas_plan(plan, hoy=None):
    """Cumplimiento, horas, racha, "hoy toca" y cuenta regresiva de un plan."""
    hoy = hoy or date.today()
    sesiones = list(plan.sesiones)
    completadas = [s for s in sesiones if s.estado == "completada"]
    vencidas = [s for s in sesiones if s.fecha < hoy] + [s for s in completadas if s.fecha >= hoy]
    cumplimiento = round(len(completadas) / len(vencidas) * 100, 1) if vencidas else None
    atrasadas = [s for s in sesiones if s.estado == "pendiente" and s.fecha < hoy]
    dias_completados = {s.completada_en.date() for s in completadas if s.completada_en}
    racha = 0
    dia = hoy if hoy in dias_completados else hoy - timedelta(days=1)
    while dia in dias_completados:
        racha += 1
        dia -= timedelta(days=1)
    return {
        "dias_restantes": (plan.fecha_examen - hoy).days,
        "total": len(sesiones),
        "completadas": len(completadas),
        "omitidas": sum(1 for s in sesiones if s.estado == "omitida"),
        "vencidas": len(vencidas),
        "atrasadas": len(atrasadas),
        "cumplimiento": cumplimiento,
        "min_planificados": sum(s.minutos_planificados for s in sesiones),
        "min_planificados_vencidos": sum(s.minutos_planificados for s in vencidas),
        "min_reales": sum(s.minutos_reales or 0 for s in completadas),
        "racha": racha,
        "hoy": [s for s in sesiones if s.fecha == hoy],
        "proxima": next((s for s in sesiones if s.estado == "pendiente" and s.fecha >= hoy), None),
        "capacidad_restante": capacidad_restante(plan, hoy),
    }
