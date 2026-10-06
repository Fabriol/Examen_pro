"""Veredicto de aptitud e índice de preparación (sección 12).

Orientativo y CONSERVADOR: preferible un "EN RIESGO" justificado que un "APTO" por un
intento afortunado o una autoevaluación generosa.

`evaluar(DatosVeredicto) -> Veredicto` es una función PURA (sin BD) probada con pytest.
`calcular_veredicto_usuario()` reúne los datos de la BD y guarda la foto diaria.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

import config

AVISO_FIJO = (
    "Este veredicto es una estimación basada en el banco de práctica y en tu autoevaluación; "
    "no garantiza el resultado del examen real."
)
AVISO_ORIENTATIVO = (
    "Orientativo y conservador: se basa en el banco de 120 preguntas y en tu autoevaluación práctica; "
    "el examen real puede diferir."
)
ESTADOS = {
    "SIN_DATOS": ("SIN DATOS", "secondary"),
    "APTO": ("APTO", "success"),
    "EN_RIESGO": ("EN RIESGO", "warning"),
    "NO_APTO": ("NO APTO AÚN", "danger"),
}


# ---------------------------------------------------------------------------
# Estructuras
# ---------------------------------------------------------------------------
@dataclass
class CasoVer:
    codigo: str
    titulo: str
    nota: float | None            # nota del caso (promedio últimos 2 válidos), sin ajustar
    n_validos: int
    dominio_defensa: float = 0.0  # 0–100
    tiene_defensa: bool = False


@dataclass
class DatosVeredicto:
    nota_minima: float
    peso_teoria: float
    peso_practica: float
    notas_validas: list                      # [(datetime, nota)] cronológico, simulacros >= 60 preguntas
    pct_nucleo: dict                         # {1: pct|None, ...}
    dominio_estable_pct: float
    cobertura_pct: float
    casos: list                              # [CasoVer]
    plan_activo: bool = False
    cumplimiento_pct: float | None = None
    hoy: date = field(default_factory=date.today)
    fecha_examen: date | None = None
    notas_practicas: list = field(default_factory=list)   # [(datetime, nota)] intentos válidos
    minutos_necesarios: int | None = None
    minutos_disponibles: int | None = None
    tema_mas_debil: dict | None = None       # {"nombre", "slug", "pct"}
    criterio_mas_debil: dict | None = None   # {"caso", "id", "nombre", "pct"}


@dataclass
class Criterio:
    codigo: str
    descripcion: str
    valor: str
    meta: str
    cumple: bool | None                      # None = no aplica / sin datos que lo invaliden
    aviso: str = ""


@dataclass
class Veredicto:
    estado: str
    etiqueta: str
    color: str
    criterios_teoria: list
    criterios_practica: list
    criterios_comunes: list
    nota_ref_teoria: float | None
    nota_practica: float | None
    nota_practica_ajustada: float | None
    notas_caso: dict
    nota_final_estimada: float | None
    faltantes: list
    fallidos: list
    parcial: list
    eslabon_debil: bool
    indice: float
    proyeccion: float | None
    proyeccion_msg: str
    suficiencia: str | None
    suficiencia_msg: str
    recomendaciones: list
    aviso_fijo: str = AVISO_FIJO
    aviso_orientativo: str = AVISO_ORIENTATIVO

    @property
    def todos_los_criterios(self):
        return self.criterios_teoria + self.criterios_practica + self.criterios_comunes


# ---------------------------------------------------------------------------
# Cálculos auxiliares puros
# ---------------------------------------------------------------------------
def ajustar(nota):
    if nota is None:
        return None
    return round(max(0.0, nota - config.DESCUENTO_AUTOEVALUACION), 2)


def pendiente(valores):
    """Pendiente de la regresión lineal de `valores` contra su índice (0, 1, 2...)."""
    n = len(valores)
    if n < 2:
        return None
    media_x = (n - 1) / 2
    media_y = sum(valores) / n
    num = sum((i - media_x) * (v - media_y) for i, v in enumerate(valores))
    den = sum((i - media_x) ** 2 for i in range(n))
    return num / den if den else 0.0


def regresion_en(puntos, x_objetivo):
    """Regresión lineal y = a + b·x sobre [(x, y)] evaluada en x_objetivo."""
    n = len(puntos)
    media_x = sum(x for x, _ in puntos) / n
    media_y = sum(y for _, y in puntos) / n
    den = sum((x - media_x) ** 2 for x, _ in puntos)
    b = sum((x - media_x) * (y - media_y) for x, y in puntos) / den if den else 0.0
    return media_y + b * (x_objetivo - media_x)


def _dias(momento, origen):
    momento = momento if isinstance(momento, datetime) else datetime.combine(momento, datetime.min.time())
    return (momento - origen).total_seconds() / 86400


def _proyectar(serie, fecha_examen):
    origen = serie[0][0] if isinstance(serie[0][0], datetime) else datetime.combine(serie[0][0], datetime.min.time())
    puntos = [(_dias(f, origen), nota) for f, nota in serie]
    x = _dias(datetime.combine(fecha_examen, datetime.min.time()), origen)
    return min(10.0, max(0.0, regresion_en(puntos, x)))


def _fmt(valor, sufijo=""):
    return "sin datos" if valor is None else f"{valor:.2f}{sufijo}"


def _fmt_pct(valor):
    return "sin datos" if valor is None else f"{valor:.1f} %"


# ---------------------------------------------------------------------------
# Evaluación pura
# ---------------------------------------------------------------------------
def evaluar(d):
    minima = d.nota_minima
    meta_nota = minima + config.MARGEN_SEGURIDAD
    notas = [n for _, n in d.notas_validas]
    n_validos = len(notas)
    referencia = notas[-config.N_SIMULACROS_REFERENCIA:]
    nota_ref = round(sum(referencia) / len(referencia), 2) if referencia else None

    # ----- Teoría -----
    teoria = []
    teoria.append(Criterio(
        "T1", "Nota de referencia (promedio de los últimos simulacros válidos, ≥ "
              f"{config.MIN_PREGUNTAS_SIMULACRO_VALIDO} preguntas)",
        f"{_fmt(nota_ref)}" + (f" (promedio de {len(referencia)})" if referencia else ""),
        f"≥ {meta_nota:.2f}", nota_ref is not None and nota_ref >= meta_nota))
    faltan_nucleos = [n for n in (1, 2, 3, 4) if d.pct_nucleo.get(n) is None]
    if faltan_nucleos:
        valor_t2 = "sin datos en " + ", ".join(f"N{n}" for n in faltan_nucleos)
        cumple_t2 = False
    else:
        n_min = min((1, 2, 3, 4), key=lambda n: d.pct_nucleo[n])
        valor_t2 = f"mínimo N{n_min}: {d.pct_nucleo[n_min]:.1f} %"
        cumple_t2 = all(d.pct_nucleo[n] >= config.UMBRAL_NUCLEO_MIN for n in (1, 2, 3, 4))
    teoria.append(Criterio("T2", "Ningún núcleo por debajo del umbral", valor_t2,
                           f"todos ≥ {config.UMBRAL_NUCLEO_MIN} %", cumple_t2))
    teoria.append(Criterio("T3", "Dominio estable (últimas dos respuestas correctas)",
                           _fmt_pct(d.dominio_estable_pct), f"≥ {config.UMBRAL_DOMINIO_ESTABLE} %",
                           d.dominio_estable_pct >= config.UMBRAL_DOMINIO_ESTABLE))
    teoria.append(Criterio("T4", "Cobertura del banco (preguntas respondidas al menos una vez)",
                           _fmt_pct(d.cobertura_pct), f"≥ {config.UMBRAL_COBERTURA} %",
                           d.cobertura_pct >= config.UMBRAL_COBERTURA))
    teoria.append(Criterio("T5", "Simulacros válidos realizados", str(n_validos),
                           f"≥ {config.MIN_SIMULACROS_VALIDOS}", n_validos >= config.MIN_SIMULACROS_VALIDOS))
    ultimas = notas[-5:]
    tendencia = pendiente(ultimas) if len(ultimas) >= 3 else None
    teoria.append(Criterio(
        "T6", "Tendencia de las últimas 3–5 notas (regresión lineal)",
        "necesita ≥ 3 simulacros válidos" if tendencia is None else f"{tendencia:+.2f} puntos/simulacro",
        "≥ 0", tendencia is not None and tendencia >= -1e-9))

    # ----- Práctica -----
    notas_caso = {c.codigo: ajustar(c.nota) for c in d.casos}
    con_nota = [c.nota for c in d.casos if c.nota is not None and c.n_validos >= 1]
    nota_practica = round(sum(con_nota) / len(con_nota), 2) if con_nota else None
    nota_practica_aj = ajustar(nota_practica)
    practica = []
    practica.append(Criterio(
        "P1", f"Nota práctica ajustada promedio (autoevaluada − {config.DESCUENTO_AUTOEVALUACION})",
        _fmt(nota_practica_aj), f"≥ {meta_nota:.2f}",
        nota_practica_aj is not None and nota_practica_aj >= meta_nota))
    sin_nota = [c.codigo for c in d.casos if notas_caso[c.codigo] is None]
    bajos = [c.codigo for c in d.casos if notas_caso[c.codigo] is not None and notas_caso[c.codigo] < minima]
    if sin_nota:
        valor_p2 = "sin datos en " + ", ".join(sin_nota)
    elif bajos:
        valor_p2 = "por debajo: " + ", ".join(f"{c} ({notas_caso[c]:.2f})" for c in bajos)
    else:
        peor = min(d.casos, key=lambda c: notas_caso[c.codigo]) if d.casos else None
        valor_p2 = f"el más bajo: {peor.codigo} ({notas_caso[peor.codigo]:.2f})" if peor else "sin casos"
    practica.append(Criterio("P2", "Ningún caso con nota ajustada bajo la mínima (eslabón débil)", valor_p2,
                             f"todos ≥ {minima:.2f}", bool(d.casos) and not sin_nota and not bajos))
    sin_intentos = [c.codigo for c in d.casos if c.n_validos < config.MIN_INTENTOS_PRACTICA_POR_CASO]
    con_uno = [c.codigo for c in d.casos if c.n_validos == 1]
    practica.append(Criterio(
        "P3", "Intentos válidos por caso (completados, cronometrados y autoevaluados)",
        "falta en " + ", ".join(sin_intentos) if sin_intentos else "todos los casos tienen intento válido",
        f"≥ {config.MIN_INTENTOS_PRACTICA_POR_CASO} por caso", not sin_intentos and bool(d.casos),
        aviso=("Recomendado 2 intentos en: " + ", ".join(con_uno)) if con_uno else ""))
    caso_defensa = next((c for c in d.casos if c.tiene_defensa), None)
    dominio_def = caso_defensa.dominio_defensa if caso_defensa else None
    practica.append(Criterio(
        "P4", f"Dominio de la defensa del caso {caso_defensa.codigo if caso_defensa else 'P2'} (vale 3 de 10)",
        _fmt_pct(dominio_def), f"≥ {config.UMBRAL_DEFENSA} %",
        dominio_def is not None and dominio_def >= config.UMBRAL_DEFENSA))

    # ----- Común -----
    if not d.plan_activo:
        c1 = Criterio("C1", "Cumplimiento del plan de estudio", "sin plan activo",
                      f"≥ {config.UMBRAL_CUMPLIMIENTO_PLAN} %", None, aviso="Crea un plan para evaluar este criterio.")
    elif d.cumplimiento_pct is None:
        c1 = Criterio("C1", "Cumplimiento del plan de estudio", "aún no hay sesiones vencidas",
                      f"≥ {config.UMBRAL_CUMPLIMIENTO_PLAN} %", None)
    else:
        c1 = Criterio("C1", "Cumplimiento del plan de estudio", _fmt_pct(d.cumplimiento_pct),
                      f"≥ {config.UMBRAL_CUMPLIMIENTO_PLAN} %", d.cumplimiento_pct >= config.UMBRAL_CUMPLIMIENTO_PLAN)
    comunes = [c1]

    # ----- Veredicto global -----
    falta_teoria = n_validos == 0
    falta_practica = bool(sin_intentos) or not d.casos
    faltantes = []
    if falta_teoria:
        faltantes.append({"texto": f"Haz al menos un simulacro válido (≥ {config.MIN_PREGUNTAS_SIMULACRO_VALIDO} "
                                   "preguntas; el completo tiene 120).",
                          "endpoint": "examen.configurar", "params": {"modo": "completo"}})
    for codigo in sin_intentos:
        faltantes.append({"texto": f"Haz un intento cronometrado y autoevaluado del caso {codigo}.",
                          "endpoint": "practica.caso", "params": {"codigo": codigo}})

    nota_final = None
    if nota_ref is not None and nota_practica_aj is not None:
        nota_final = round(d.peso_teoria * nota_ref + d.peso_practica * nota_practica_aj, 2)
    eslabon = (nota_ref is not None and nota_ref < minima) or (nota_practica_aj is not None and nota_practica_aj < minima)
    fallidos = [c for c in teoria + practica + comunes if c.cumple is False]

    if falta_teoria or falta_practica:
        estado = "SIN_DATOS"
    elif nota_final < minima:
        estado = "NO_APTO"
    elif not fallidos and not eslabon:
        estado = "APTO"
    else:
        estado = "EN_RIESGO"

    parcial = []
    if not falta_teoria:
        ok = sum(1 for c in teoria if c.cumple)
        parcial.append(f"Teoría: cumple {ok} de {len(teoria)} criterios · nota de referencia {nota_ref:.2f}"
                       + (" (bajo la mínima)" if nota_ref < minima else ""))
    if con_nota:
        ok = sum(1 for c in practica if c.cumple)
        parcial.append(f"Práctica: cumple {ok} de {len(practica)} criterios · nota ajustada {nota_practica_aj:.2f}"
                       + (" (bajo la mínima)" if nota_practica_aj < minima else ""))

    # ----- Índice de preparación (0–100) -----
    nucleos = [d.pct_nucleo.get(n) or 0.0 for n in (1, 2, 3, 4)]
    componentes = {
        "teoria": (35, (nota_ref or 0) / 10),
        "dominio": (15, (d.dominio_estable_pct or 0) / 100),
        "practica": (30, (nota_practica_aj or 0) / 10),
        "nucleo": (10, min(nucleos) / 100),
        "defensa": (5, (dominio_def or 0) / 100),
    }
    if d.plan_activo and d.cumplimiento_pct is not None:
        componentes["cumplimiento"] = (5, d.cumplimiento_pct / 100)
    peso_total = sum(p for p, _ in componentes.values())
    indice = round(sum(p * min(1.0, max(0.0, v)) for p, v in componentes.values()) / peso_total * 100, 1)

    # ----- Proyección -----
    if d.fecha_examen is None:
        proyeccion, proy_msg = None, "Define la fecha del examen en tu plan para proyectar."
    elif len(d.notas_validas) < 3 or len(d.notas_practicas) < 3:
        proyeccion, proy_msg = None, "Datos insuficientes para proyectar."
    else:
        teo = _proyectar(d.notas_validas, d.fecha_examen)
        pra = max(0.0, _proyectar(d.notas_practicas, d.fecha_examen) - config.DESCUENTO_AUTOEVALUACION)
        proyeccion = round(min(10.0, max(0.0, d.peso_teoria * teo + d.peso_practica * pra)), 2)
        proy_msg = "Estimación por regresión lineal de tus notas hasta el día del examen."

    # ----- Suficiencia de tiempo -----
    if d.minutos_necesarios is None or d.minutos_disponibles is None:
        suficiencia, suf_msg = None, "Crea un plan de estudio para estimar si te alcanza el tiempo."
    else:
        nec, disp = d.minutos_necesarios, d.minutos_disponibles
        if disp >= nec * 1.2:
            suficiencia = "Suficiente"
        elif disp >= nec:
            suficiencia = "Justo"
        else:
            suficiencia = "Insuficiente"
        suf_msg = f"Necesitas ~{nec / 60:.1f} h y tienes {disp / 60:.1f} h disponibles hasta el examen."

    recomendaciones = _recomendaciones(d, notas_caso, n_validos, tendencia, dominio_def, caso_defensa,
                                       suficiencia, meta_nota, sin_intentos)
    etiqueta, color = ESTADOS[estado]
    return Veredicto(
        estado=estado, etiqueta=etiqueta, color=color,
        criterios_teoria=teoria, criterios_practica=practica, criterios_comunes=comunes,
        nota_ref_teoria=nota_ref, nota_practica=nota_practica, nota_practica_ajustada=nota_practica_aj,
        notas_caso=notas_caso, nota_final_estimada=nota_final, faltantes=faltantes, fallidos=fallidos,
        parcial=parcial, eslabon_debil=eslabon, indice=indice, proyeccion=proyeccion, proyeccion_msg=proy_msg,
        suficiencia=suficiencia, suficiencia_msg=suf_msg, recomendaciones=recomendaciones,
    )


def _recomendaciones(d, notas_caso, n_validos, tendencia, dominio_def, caso_defensa, suficiencia,
                     meta_nota, sin_intentos):
    recs = []
    for codigo in sin_intentos:
        recs.append({"texto": f"Haz tu primer intento cronometrado del caso {codigo}.",
                     "endpoint": "practica.caso", "params": {"codigo": codigo}})
    con_nota = [c for c in d.casos if notas_caso.get(c.codigo) is not None]
    if con_nota:
        peor = min(con_nota, key=lambda c: notas_caso[c.codigo])
        if notas_caso[peor.codigo] < meta_nota:
            recs.append({"texto": f"Refuerza el caso {peor.codigo}: nota ajustada {notas_caso[peor.codigo]:.2f}.",
                         "endpoint": "practica.caso", "params": {"codigo": peor.codigo}})
    if d.criterio_mas_debil and (d.criterio_mas_debil.get("pct") or 0) < 70:
        c = d.criterio_mas_debil
        recs.append({"texto": f"Practica el criterio {c['id']} ({c['nombre']}): {c['pct']:.0f} %.",
                     "endpoint": "practica.caso", "params": {"codigo": c["caso"], "criterio": c["id"]}})
    if d.tema_mas_debil and (d.tema_mas_debil.get("pct") is None or d.tema_mas_debil["pct"] < 70):
        t = d.tema_mas_debil
        detalle = "sin responder" if t.get("pct") is None else f"{t['pct']:.0f} %"
        recs.append({"texto": f"Estudia el tema {t['nombre']} ({detalle}).",
                     "endpoint": "estudio.tema", "params": {"slug": t["slug"]}})
    if n_validos < max(config.MIN_SIMULACROS_VALIDOS, config.N_SIMULACROS_REFERENCIA):
        recs.append({"texto": f"Haz un simulacro completo: llevas {n_validos} válido(s) y la referencia usa "
                              f"los últimos {config.N_SIMULACROS_REFERENCIA}.",
                     "endpoint": "examen.configurar", "params": {"modo": "completo"}})
    if tendencia is not None and tendencia < 0:
        recs.append({"texto": "Tu tendencia es negativa: repasa tus preguntas falladas antes del próximo simulacro.",
                     "endpoint": "examen.configurar", "params": {"modo": "fallidas"}})
    if caso_defensa and (dominio_def or 0) < config.UMBRAL_DEFENSA:
        recs.append({"texto": f"Ensaya la defensa de {caso_defensa.codigo} (dominio {dominio_def or 0:.0f} %): "
                              "vale 3 de 10 puntos.",
                     "endpoint": "practica.defensa", "params": {"codigo": caso_defensa.codigo}})
    if suficiencia == "Insuficiente":
        falta = (d.minutos_necesarios - d.minutos_disponibles) / 60
        recs.append({"texto": f"Sube tus horas de estudio: te faltan ~{falta:.1f} h para cubrir lo pendiente.",
                     "endpoint": "plan.crear", "params": {}})
    if not d.plan_activo:
        recs.append({"texto": "Crea tu plan de estudio con la fecha del examen.", "endpoint": "plan.crear", "params": {}})
    return recs[:5]


# ---------------------------------------------------------------------------
# Capa de base de datos
# ---------------------------------------------------------------------------
def minutos_necesarios(resumen, filas_casos, n_validos):
    """Temas con dominio < 70 % + criterios < 70 % + intentos y simulacros que faltan."""
    from servicios.planificador import minutos_criterio, minutos_tema

    total = sum(minutos_tema(t.peso) for t in resumen.temas.values() if t.dominio < config.UMBRAL_DOMINIO_ESTABLE / 100)
    for fila in filas_casos:
        caso = fila["caso"]
        for c in caso.rubrica:
            if "defensa" in c["criterio"].lower():
                continue
            pct = fila["criterios"].get(c["id"])
            if pct is None or pct < 70:
                total += minutos_criterio(float(c["puntaje"]))
        if fila["n_validos"] < config.MIN_INTENTOS_PRACTICA_POR_CASO:
            total += caso.tiempo_sugerido_min
        if any("defensa" in c["criterio"].lower() for c in caso.rubrica) and fila["dominio_defensa"] < config.UMBRAL_DEFENSA:
            total += 2 * config.DURACION_DEFENSA_MIN
    total += max(0, config.MIN_SIMULACROS_VALIDOS - n_validos) * config.DURACION_SIMULACRO_COMPLETO_MIN
    return int(total)


def datos_veredicto(usuario, hoy=None):
    from servicios import estadisticas
    from servicios import practica as srv_practica
    from servicios.planificador import estadisticas_plan

    hoy = hoy or date.today()
    params = estadisticas.parametros_examen(usuario)
    resumen = estadisticas.resumen_teoria(usuario.id)
    filas = srv_practica.resumen_casos(usuario.id, params["nota_minima"])
    notas_validas = estadisticas.notas_simulacros_validos(usuario.id)
    plan = params["plan"]
    stats = estadisticas_plan(plan, hoy) if plan else None
    debiles = resumen.temas_mas_debiles(1)
    tema = debiles[0] if debiles else None
    criterio = next(iter(srv_practica.criterios_mas_debiles(filas, 1)), None)
    return DatosVeredicto(
        nota_minima=params["nota_minima"],
        peso_teoria=params["peso_teoria"],
        peso_practica=params["peso_practica"],
        notas_validas=notas_validas,
        pct_nucleo={n: resumen.por_nucleo[n].pct for n in (1, 2, 3, 4)},
        dominio_estable_pct=resumen.dominio_estable_pct,
        cobertura_pct=resumen.cobertura_pct,
        casos=[CasoVer(f["caso"].codigo, f["caso"].titulo, f["nota_caso"], f["n_validos"], f["dominio_defensa"],
                       any("defensa" in c["criterio"].lower() for c in f["caso"].rubrica)) for f in filas],
        plan_activo=plan is not None,
        cumplimiento_pct=stats["cumplimiento"] if stats else None,
        hoy=hoy,
        fecha_examen=params["fecha_examen"],
        notas_practicas=[(f, n) for f, _, n in srv_practica.notas_practicas_cronologicas(usuario.id)],
        minutos_necesarios=minutos_necesarios(resumen, filas, len(notas_validas)) if plan else None,
        minutos_disponibles=stats["capacidad_restante"] if stats else None,
        tema_mas_debil={"nombre": tema.nombre, "slug": tema.slug, "pct": tema.pct} if tema else None,
        criterio_mas_debil=(
            {"caso": criterio[0].codigo, "id": criterio[1]["id"], "nombre": criterio[1]["criterio"], "pct": criterio[2]}
            if criterio else None
        ),
    )


def calcular_veredicto_usuario(usuario, hoy=None, guardar_foto=True):
    """Calcula el veredicto y guarda (o actualiza) la foto del día en VeredictoDiario."""
    from extensions import db
    from models import VeredictoDiario

    hoy = hoy or date.today()
    veredicto = evaluar(datos_veredicto(usuario, hoy))
    if guardar_foto:
        foto = VeredictoDiario.query.filter_by(usuario_id=usuario.id, fecha=hoy).first()
        if foto is None:
            foto = VeredictoDiario(usuario_id=usuario.id, fecha=hoy)
            db.session.add(foto)
        foto.veredicto = veredicto.estado
        foto.indice = veredicto.indice
        foto.nota_teoria = veredicto.nota_ref_teoria
        foto.nota_practica = veredicto.nota_practica_ajustada
        foto.nota_final_estimada = veredicto.nota_final_estimada
        db.session.commit()
    return veredicto
