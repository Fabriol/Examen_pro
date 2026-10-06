"""Modelo de datos del Simulador Complexivo (sección 4 de la especificación)."""
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, login_manager

MODOS_EXAMEN = ("completo", "nucleo", "nivel", "tema", "fallidas")
NIVELES = ("facil", "medio", "dificil")
NIVELES_DEFENSA = ("no_se", "parcial", "dominado")
FASES = ("diagnostico", "cobertura", "refuerzo", "simulacro", "repaso_final")
TIPOS_SESION = (
    "tarjetas", "practica_tema", "simulacro_nucleo", "simulacro_completo", "fallidas",
    "repaso_ligero", "practica_caso", "intento_practico", "defensa",
)
TIPOS_SESION_PRACTICA = ("practica_caso", "intento_practico", "defensa")
ESTADOS_SESION = ("pendiente", "completada", "omitida")
DIAS_SEMANA = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")


def ahora():
    """Fecha y hora local sin zona horaria (ver DECISIONES.md)."""
    return datetime.now()


# ---------------------------------------------------------------------------
# Usuario
# ---------------------------------------------------------------------------
class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=ahora, nullable=False)

    intentos = db.relationship("Intento", back_populates="usuario", cascade="all, delete-orphan")
    intentos_practicos = db.relationship(
        "IntentoPractico", back_populates="usuario", cascade="all, delete-orphan"
    )
    repasos_defensa = db.relationship(
        "RepasoDefensa", back_populates="usuario", cascade="all, delete-orphan"
    )
    repasos_tarjeta = db.relationship(
        "RepasoTarjeta", back_populates="usuario", cascade="all, delete-orphan"
    )
    planes = db.relationship("PlanEstudio", back_populates="usuario", cascade="all, delete-orphan")
    veredictos = db.relationship(
        "VeredictoDiario", back_populates="usuario", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def _completados(self):
        return Intento.query.filter(Intento.usuario_id == self.id, Intento.completado.is_(True))

    @property
    def total_intentos(self):
        return self._completados().count()

    @property
    def mejor_nota(self):
        return (
            db.session.query(func.max(Intento.nota))
            .filter(Intento.usuario_id == self.id, Intento.completado.is_(True))
            .scalar()
        )

    @property
    def nota_promedio(self):
        valor = (
            db.session.query(func.avg(Intento.nota))
            .filter(Intento.usuario_id == self.id, Intento.completado.is_(True))
            .scalar()
        )
        return round(valor, 2) if valor is not None else None

    @property
    def ultima_nota(self):
        ultimo = self._completados().order_by(Intento.fecha_fin.desc()).first()
        return ultimo.nota if ultimo else None

    @property
    def tiempo_total_practicado(self):
        """Segundos de intentos teóricos y prácticos + sesiones de estudio sin intento."""
        teoria = (
            db.session.query(func.coalesce(func.sum(Intento.duracion_segundos), 0))
            .filter(Intento.usuario_id == self.id, Intento.completado.is_(True))
            .scalar()
        )
        practica = (
            db.session.query(func.coalesce(func.sum(IntentoPractico.duracion_segundos), 0))
            .filter(IntentoPractico.usuario_id == self.id, IntentoPractico.completado.is_(True))
            .scalar()
        )
        sesiones_min = (
            db.session.query(func.coalesce(func.sum(SesionEstudio.minutos_reales), 0))
            .join(PlanEstudio, SesionEstudio.plan_id == PlanEstudio.id)
            .filter(
                PlanEstudio.usuario_id == self.id,
                SesionEstudio.estado == "completada",
                SesionEstudio.tipo.in_(("tarjetas", "practica_caso", "defensa", "repaso_ligero")),
            )
            .scalar()
        )
        return int(teoria) + int(practica) + int(sesiones_min) * 60

    @property
    def plan_activo(self):
        return PlanEstudio.query.filter_by(usuario_id=self.id, activo=True).first()


@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))


# ---------------------------------------------------------------------------
# Banco teórico
# ---------------------------------------------------------------------------
class Pregunta(db.Model):
    __tablename__ = "preguntas"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)
    nucleo = db.Column(db.Integer, nullable=False, index=True)
    nivel = db.Column(db.String(10), nullable=False, index=True)
    tema = db.Column(db.String(80), nullable=False)
    tema_slug = db.Column(db.String(100), nullable=False, index=True)
    enunciado = db.Column(db.Text, nullable=False)
    opciones = db.Column(db.JSON, nullable=False)
    correcta = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f"<Pregunta {self.codigo}>"


class Intento(db.Model):
    __tablename__ = "intentos"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fecha_inicio = db.Column(db.DateTime, default=ahora, nullable=False)
    fecha_fin = db.Column(db.DateTime)
    modo = db.Column(db.String(10), nullable=False)
    filtro = db.Column(db.String(100))
    total_preguntas = db.Column(db.Integer, nullable=False)
    aciertos = db.Column(db.Integer, default=0, nullable=False)
    nota = db.Column(db.Float)
    duracion_segundos = db.Column(db.Integer)
    completado = db.Column(db.Boolean, default=False, nullable=False, index=True)
    tiempo_limite_segundos = db.Column(db.Integer, nullable=False)
    orden_preguntas = db.Column(db.JSON, nullable=False)       # [pregunta_id, ...] en el orden mostrado
    mapeo_opciones = db.Column(db.JSON, nullable=False)        # {"<pregunta_id>": [2,0,3,1]} pos. mostrada -> índice original
    sesion_id = db.Column(
        db.Integer, db.ForeignKey("sesiones_estudio.id", ondelete="SET NULL"), nullable=True
    )

    usuario = db.relationship("Usuario", back_populates="intentos")
    respuestas = db.relationship("Respuesta", back_populates="intento", cascade="all, delete-orphan")
    sesion = db.relationship("SesionEstudio", foreign_keys=[sesion_id])

    def segundos_transcurridos(self, momento=None):
        momento = momento or ahora()
        return max(0, int((momento - self.fecha_inicio).total_seconds()))

    def segundos_restantes(self, momento=None):
        return max(0, self.tiempo_limite_segundos - self.segundos_transcurridos(momento))

    @property
    def es_simulacro_valido(self):
        from config import MIN_PREGUNTAS_SIMULACRO_VALIDO
        return self.completado and self.total_preguntas >= MIN_PREGUNTAS_SIMULACRO_VALIDO


class Respuesta(db.Model):
    __tablename__ = "respuestas"
    __table_args__ = (db.UniqueConstraint("intento_id", "pregunta_id", name="uq_respuesta_intento_pregunta"),)

    id = db.Column(db.Integer, primary_key=True)
    intento_id = db.Column(
        db.Integer, db.ForeignKey("intentos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pregunta_id = db.Column(db.Integer, db.ForeignKey("preguntas.id"), nullable=False, index=True)
    opcion_elegida = db.Column(db.Integer, nullable=True)   # índice ORIGINAL; NULL = en blanco
    es_correcta = db.Column(db.Boolean, default=False, nullable=False)
    segundos_empleados = db.Column(db.Integer, default=0, nullable=False)

    intento = db.relationship("Intento", back_populates="respuestas")
    pregunta = db.relationship("Pregunta")


# ---------------------------------------------------------------------------
# Casos prácticos
# ---------------------------------------------------------------------------
class CasoPractico(db.Model):
    __tablename__ = "casos_practicos"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(5), unique=True, nullable=False)
    nucleo = db.Column(db.Integer, nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    tecnologia = db.Column(db.String(300), nullable=False)
    tiempo_sugerido_min = db.Column(db.Integer, nullable=False)
    enunciado = db.Column(db.Text, nullable=False)
    rubrica = db.Column(db.JSON, nullable=False)
    defensa = db.Column(db.JSON, nullable=False)
    ambiguedades = db.Column(db.JSON, nullable=False)
    recursos = db.Column(db.JSON, nullable=False)

    @property
    def puntaje_total(self):
        return round(sum(c["puntaje"] for c in self.rubrica), 2)

    def criterio(self, criterio_id):
        return next((c for c in self.rubrica if c["id"] == criterio_id), None)

    @property
    def ids_tareas(self):
        return [t["id"] for c in self.rubrica for t in c["tareas"]]

    @staticmethod
    def es_criterio_defensa(criterio):
        """El criterio de defensa oral (P2-R6) se entrena con las tarjetas de defensa."""
        return "defensa" in criterio["criterio"].lower()


class IntentoPractico(db.Model):
    __tablename__ = "intentos_practicos"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    caso_id = db.Column(db.Integer, db.ForeignKey("casos_practicos.id"), nullable=False)
    fecha_inicio = db.Column(db.DateTime, default=ahora, nullable=False)
    fecha_fin = db.Column(db.DateTime)                 # se fija al terminar (antes de autoevaluar)
    tiempo_limite_segundos = db.Column(db.Integer, nullable=False)
    duracion_segundos = db.Column(db.Integer)
    completado = db.Column(db.Boolean, default=False, nullable=False, index=True)
    tareas_ok = db.Column(db.JSON, nullable=False, default=list)
    notas = db.Column(db.Text, default="")
    nota_autoevaluada = db.Column(db.Float)
    sesion_id = db.Column(
        db.Integer, db.ForeignKey("sesiones_estudio.id", ondelete="SET NULL"), nullable=True
    )

    usuario = db.relationship("Usuario", back_populates="intentos_practicos")
    caso = db.relationship("CasoPractico")
    evaluaciones = db.relationship(
        "EvaluacionCriterio", back_populates="intento_practico", cascade="all, delete-orphan"
    )
    sesion = db.relationship("SesionEstudio", foreign_keys=[sesion_id])

    def segundos_transcurridos(self, momento=None):
        momento = momento or ahora()
        return max(0, int((momento - self.fecha_inicio).total_seconds()))

    def segundos_restantes(self, momento=None):
        return max(0, self.tiempo_limite_segundos - self.segundos_transcurridos(momento))

    @property
    def terminado(self):
        """El cronómetro ya se detuvo (por botón o por expiración) aunque falte autoevaluar."""
        return self.fecha_fin is not None


class EvaluacionCriterio(db.Model):
    __tablename__ = "evaluaciones_criterio"
    __table_args__ = (
        db.UniqueConstraint("intento_practico_id", "criterio_id", name="uq_evaluacion_intento_criterio"),
    )

    id = db.Column(db.Integer, primary_key=True)
    intento_practico_id = db.Column(
        db.Integer, db.ForeignKey("intentos_practicos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterio_id = db.Column(db.String(20), nullable=False)
    puntaje_maximo = db.Column(db.Float, nullable=False)
    puntaje_sugerido = db.Column(db.Float, nullable=False)
    puntaje_final = db.Column(db.Float)
    comentario = db.Column(db.Text, default="")

    intento_practico = db.relationship("IntentoPractico", back_populates="evaluaciones")


class RepasoDefensa(db.Model):
    __tablename__ = "repasos_defensa"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    caso_id = db.Column(db.Integer, db.ForeignKey("casos_practicos.id"), nullable=False)
    indice_pregunta = db.Column(db.Integer, nullable=False)
    nivel = db.Column(db.String(10), nullable=False)
    fecha = db.Column(db.DateTime, default=ahora, nullable=False)

    usuario = db.relationship("Usuario", back_populates="repasos_defensa")
    caso = db.relationship("CasoPractico")


# ---------------------------------------------------------------------------
# Plan de estudio
# ---------------------------------------------------------------------------
class PlanEstudio(db.Model):
    __tablename__ = "planes_estudio"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fecha_creacion = db.Column(db.DateTime, default=ahora, nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_examen = db.Column(db.Date, nullable=False)
    horas_por_dia = db.Column(db.JSON, nullable=False)          # {"lun": 2, ..., "dom": 0}
    nota_minima = db.Column(db.Float, nullable=False)
    peso_teoria = db.Column(db.Float, nullable=False)
    peso_practica = db.Column(db.Float, nullable=False)
    porcentaje_tiempo_practica = db.Column(db.Integer, nullable=False, default=50)
    activo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    advertencias = db.Column(db.JSON, nullable=False, default=list)
    ultima_recalculacion = db.Column(db.DateTime)

    usuario = db.relationship("Usuario", back_populates="planes")
    sesiones = db.relationship(
        "SesionEstudio",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="(SesionEstudio.fecha, SesionEstudio.orden)",
    )


class SesionEstudio(db.Model):
    __tablename__ = "sesiones_estudio"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(
        db.Integer, db.ForeignKey("planes_estudio.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fecha = db.Column(db.Date, nullable=False, index=True)
    orden = db.Column(db.Integer, nullable=False, default=0)
    fase = db.Column(db.String(15), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    nucleo = db.Column(db.Integer)
    tema_slug = db.Column(db.String(100))
    caso_codigo = db.Column(db.String(5))
    criterio_id = db.Column(db.String(20))
    titulo = db.Column(db.String(200), nullable=False)
    minutos_planificados = db.Column(db.Integer, nullable=False)
    minutos_reales = db.Column(db.Integer)
    estado = db.Column(db.String(12), nullable=False, default="pendiente", index=True)
    completada_en = db.Column(db.DateTime)
    resultado_aciertos = db.Column(db.Integer)
    resultado_total = db.Column(db.Integer)

    plan = db.relationship("PlanEstudio", back_populates="sesiones")

    @property
    def es_practica(self):
        return self.tipo in TIPOS_SESION_PRACTICA


class RepasoTarjeta(db.Model):
    """Solo ordena el repaso de tarjetas: nunca afecta nota, dominio ni veredicto."""
    __tablename__ = "repasos_tarjeta"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pregunta_id = db.Column(db.Integer, db.ForeignKey("preguntas.id"), nullable=False, index=True)
    sabia = db.Column(db.Boolean, nullable=False)
    fecha = db.Column(db.DateTime, default=ahora, nullable=False)

    usuario = db.relationship("Usuario", back_populates="repasos_tarjeta")


class VeredictoDiario(db.Model):
    __tablename__ = "veredictos_diarios"
    __table_args__ = (db.UniqueConstraint("usuario_id", "fecha", name="uq_veredicto_usuario_fecha"),)

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fecha = db.Column(db.Date, nullable=False)
    veredicto = db.Column(db.String(12), nullable=False)
    indice = db.Column(db.Float, nullable=False)
    nota_teoria = db.Column(db.Float)
    nota_practica = db.Column(db.Float)
    nota_final_estimada = db.Column(db.Float)

    usuario = db.relationship("Usuario", back_populates="veredictos")
