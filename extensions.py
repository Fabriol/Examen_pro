"""Extensiones de Flask compartidas (se inicializan dentro de create_app)."""
import sqlite3

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
csrf = CSRFProtect()

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Inicia sesión para continuar."
login_manager.login_message_category = "warning"


@event.listens_for(Engine, "connect")
def _activar_claves_foraneas_sqlite(dbapi_connection, connection_record):
    """SQLite ignora las FK (y ON DELETE) si no se activan en cada conexión."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
