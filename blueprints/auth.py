"""Autenticación: registro, inicio y cierre de sesión (sección 6)."""
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from sqlalchemy import func
from wtforms import BooleanField, EmailField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from extensions import db
from models import Usuario

bp = Blueprint("auth", __name__)

MENSAJE_LOGIN_FALLIDO = "Correo o contraseña incorrectos"


class RegistroForm(FlaskForm):
    nombre_completo = StringField(
        "Nombre completo",
        validators=[DataRequired(message="Escribe tu nombre completo."), Length(max=120)],
    )
    email = EmailField(
        "Correo electrónico",
        validators=[
            DataRequired(message="Escribe tu correo."),
            Email(message="El correo no es válido."),
            Length(max=120),
        ],
    )
    password = PasswordField(
        "Contraseña",
        validators=[
            DataRequired(message="Escribe una contraseña."),
            Length(min=8, message="La contraseña debe tener al menos 8 caracteres."),
        ],
    )
    confirmar = PasswordField(
        "Confirmar contraseña",
        validators=[
            DataRequired(message="Confirma la contraseña."),
            EqualTo("password", message="Las contraseñas no coinciden."),
        ],
    )
    enviar = SubmitField("Crear cuenta")

    def validate_email(self, campo):
        correo = (campo.data or "").strip().lower()
        if Usuario.query.filter(func.lower(Usuario.email) == correo).first():
            raise ValidationError("Ya existe una cuenta con ese correo.")


class LoginForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(message="Escribe tu correo.")])
    password = PasswordField("Contraseña", validators=[DataRequired(message="Escribe tu contraseña.")])
    recordarme = BooleanField("Recordarme")
    enviar = SubmitField("Iniciar sesión")


def es_ruta_segura(destino):
    """Solo rutas internas relativas: '/algo'. Rechaza '//host', 'http://', '\\\\host'."""
    if not destino or not destino.startswith("/") or destino.startswith("//") or "\\" in destino:
        return False
    partes = urlsplit(destino)
    return not partes.scheme and not partes.netloc


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    form = RegistroForm()
    if form.validate_on_submit():
        usuario = Usuario(
            nombre_completo=form.nombre_completo.data.strip(),
            email=form.email.data.strip().lower(),
        )
        usuario.set_password(form.password.data)
        db.session.add(usuario)
        db.session.commit()
        login_user(usuario)
        flash(f"¡Bienvenido/a, {usuario.nombre_completo}! Tu cuenta está lista.", "success")
        return redirect(url_for("dashboard.index"))
    return render_template("auth/registro.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    form = LoginForm()
    siguiente = request.args.get("next", "")
    if form.validate_on_submit():
        correo = (form.email.data or "").strip().lower()
        usuario = Usuario.query.filter(func.lower(Usuario.email) == correo).first()
        if usuario is None or not usuario.check_password(form.password.data):
            flash(MENSAJE_LOGIN_FALLIDO, "danger")
        else:
            login_user(usuario, remember=form.recordarme.data)
            if es_ruta_segura(siguiente):
                return redirect(siguiente)
            return redirect(url_for("dashboard.index"))
    return render_template(
        "auth/login.html", form=form, siguiente=siguiente if es_ruta_segura(siguiente) else ""
    )


@bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada. ¡Hasta pronto!", "info")
    return redirect(url_for("auth.login"))
