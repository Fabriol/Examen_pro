"""Pruebas de aceptación de la sección 16 (de extremo a extremo con el cliente de Flask).

Cada prueba lleva el número de la prueba de aceptación que cubre.
"""
import html
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta

import pytest

import config
from extensions import db
from models import (CasoPractico, EvaluacionCriterio, Intento, IntentoPractico, PlanEstudio, Pregunta,
                    RepasoDefensa, RepasoTarjeta, Respuesta, SesionEstudio, Usuario, VeredictoDiario, ahora)
from servicios import estadisticas

RAIZ = config.BASE_DIR


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def registrar(client, email="ana@correo.com", nombre="Ana Prueba", password="clave1234"):
    return client.post("/registro", data={"nombre_completo": nombre, "email": email,
                                          "password": password, "confirmar": password})


def nuevo_examen(client, **campos):
    datos = {"modo": "completo", "segundos_por_pregunta": "60", "aleatorio": "on", "barajar": "on"}
    datos.update(campos)
    r = client.post("/examen/configurar", data=datos)
    assert r.status_code == 302, r.data[:400]
    return int(re.search(r"/examen/(\d+)$", r.headers["Location"]).group(1))


def en_bd(app, funcion):
    with app.app_context():
        return funcion()


def orden(app, intento_id):
    return en_bd(app, lambda: list(db.session.get(Intento, intento_id).orden_preguntas))


def posicion(app, intento_id, pregunta_id, correcta=True):
    def calcular():
        intento = db.session.get(Intento, intento_id)
        pregunta = db.session.get(Pregunta, pregunta_id)
        pos = intento.mapeo_opciones[str(pregunta_id)].index(pregunta.correcta)
        return pos if correcta else (pos + 1) % 4
    return en_bd(app, calcular)


def responder(client, intento_id, pregunta_id, pos):
    return client.post(f"/examen/{intento_id}/responder",
                       json={"pregunta_id": pregunta_id, "posicion": pos, "segundos": 3})


def retrasar_inicio(app, modelo, objeto_id, segundos):
    def mover():
        objeto = db.session.get(modelo, objeto_id)
        objeto.fecha_inicio = ahora() - timedelta(seconds=segundos)
        db.session.commit()
    en_bd(app, mover)


def datos_json(respuesta, id_script):
    texto = respuesta.data.decode("utf-8")
    bloque = re.search(rf'<script id="{id_script}" type="application/json">(.*?)</script>', texto, re.S).group(1)
    return json.loads(html.unescape(bloque))


def crear_plan(client, dias=30, horas=2, pct=50, inicio=None, **extra):
    hoy = date.today()
    datos = {"fecha_examen": (hoy + timedelta(days=dias)).isoformat(),
             "fecha_inicio": (inicio or hoy).isoformat(),
             "nota_minima": "7", "peso_teoria": "50", "peso_practica": "50",
             "porcentaje_tiempo_practica": str(pct)}
    for d in ("lun", "mar", "mie", "jue", "vie", "sab", "dom"):
        datos[d] = str(horas)
    datos.update(extra)
    return client.post("/plan/crear", data=datos)


def plan_activo(app, email="ana@correo.com"):
    def leer():
        u = Usuario.query.filter_by(email=email).first()
        plan = PlanEstudio.query.filter_by(usuario_id=u.id, activo=True).first()
        return plan.id if plan else None
    return en_bd(app, leer)


def sesiones(app, plan_id):
    return en_bd(app, lambda: [
        {"id": s.id, "fecha": s.fecha, "fase": s.fase, "tipo": s.tipo, "tema_slug": s.tema_slug,
         "criterio_id": s.criterio_id, "caso_codigo": s.caso_codigo, "minutos": s.minutos_planificados,
         "estado": s.estado}
        for s in SesionEstudio.query.filter_by(plan_id=plan_id).order_by(SesionEstudio.fecha, SesionEstudio.orden)
    ])


def intento_practico(client, codigo="P2", minutos=180):
    r = client.post(f"/practica/{codigo}/iniciar", data={"minutos": str(minutos)})
    assert r.status_code == 302, r.data[:300]
    return int(re.search(r"/practica/intento/(\d+)$", r.headers["Location"]).group(1))


def autoevaluar(client, app, intento_id, fraccion=1.0, valores=None):
    rubrica = en_bd(app, lambda: db.session.get(IntentoPractico, intento_id).caso.rubrica)
    datos = {}
    for c in rubrica:
        valor = (valores or {}).get(c["id"], round(c["puntaje"] * fraccion * 4) / 4)
        datos[f"puntaje_{c['id']}"] = str(valor)
    return client.post(f"/practica/intento/{intento_id}/autoevaluar", data=datos)


# ---------------------------------------------------------------------------
# 1. Arranque, rutas y seed
# ---------------------------------------------------------------------------
def test_01_arranque_rutas_bd_y_seed_idempotente(app):
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    for requerido in ("auth.registro", "auth.login", "auth.logout", "examen.configurar", "examen.rendir",
                      "examen.responder", "examen.tiempo", "examen.finalizar", "examen.resultado",
                      "estudio.tema", "practica.index", "practica.caso", "practica.intento",
                      "practica.autoevaluar", "practica.resultado", "practica.defensa", "practica.recurso",
                      "plan.index", "plan.crear", "plan.semana", "plan.veredicto", "plan.pendientes_docente",
                      "dashboard.index", "dashboard.historial", "dashboard.debilidades"):
        assert requerido in endpoints, requerido

    def conteos():
        from seed import sembrar
        preguntas = Pregunta.query.all()
        casos = CasoPractico.query.all()
        segunda = sembrar()
        return (len(preguntas), {n: sum(p.nucleo == n for p in preguntas) for n in (1, 2, 3, 4)},
                {n: sum(p.nivel == n for p in preguntas) for n in ("facil", "medio", "dificil")},
                {c.codigo: c.puntaje_total for c in casos}, segunda, Pregunta.query.count(),
                CasoPractico.query.count())
    total, por_nucleo, por_nivel, casos, segunda, total2, casos2 = en_bd(app, conteos)
    assert total == 120 and set(por_nucleo.values()) == {30} and set(por_nivel.values()) == {40}
    assert casos == {"P1": 10.0, "P2": 10.0, "P3": 10.0, "P4": 10.0}
    assert segunda["nuevas_preguntas"] == 0 and segunda["nuevos_casos"] == 0 and not segunda["problemas"]
    assert total2 == 120 and casos2 == 4


def test_01b_cli_flask_routes_y_flask_seed(tmp_path):
    entorno = dict(os.environ, DATABASE_URL="sqlite:///" + (tmp_path / "cli.db").as_posix(),
                   FLASK_APP="app.py", PYTHONIOENCODING="utf-8")
    ejecutar = lambda *args: subprocess.run([sys.executable, "-m", "flask", *args], cwd=RAIZ, env=entorno,  # noqa: E731
                                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    rutas = ejecutar("routes")
    assert rutas.returncode == 0, rutas.stderr
    assert "/examen/<int:intento_id>/finalizar" in rutas.stdout and "/plan/veredicto" in rutas.stdout
    primera = ejecutar("seed")
    segunda = ejecutar("seed")
    assert primera.returncode == 0 and segunda.returncode == 0, primera.stderr + segunda.stderr
    assert "✔ 120 preguntas y 4 casos prácticos cargados (30 por núcleo, 40 por nivel)" in segunda.stdout
    assert "Nuevas preguntas: 0 · nuevos casos: 0" in segunda.stdout


# ---------------------------------------------------------------------------
# 2. Autenticación
# ---------------------------------------------------------------------------
def test_02_registro_login_logout_y_boton_visible(client):
    r = registrar(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard/")
    pagina = client.get("/dashboard/").data.decode()
    assert "Cerrar sesión" in pagina and 'id="btn-cerrar-sesion"' in pagina and "Ana Prueba" in pagina
    for ruta in ("/examen/configurar", "/practica/", "/plan/", "/estudio/"):
        assert "Cerrar sesión" in client.get(ruta).data.decode()

    assert registrar(client, email="ANA@correo.com").status_code in (200, 302)
    client.post("/logout")
    assert "/login" in client.get("/dashboard/").headers["Location"]
    assert "Ya existe una cuenta" in registrar(client, email="ANA@correo.com").data.decode()

    mal = client.post("/login", data={"email": "ana@correo.com", "password": "otra-clave"})
    assert "Correo o contraseña incorrectos" in mal.data.decode()
    mal2 = client.post("/login", data={"email": "nadie@correo.com", "password": "clave1234"})
    assert "Correo o contraseña incorrectos" in mal2.data.decode()
    externo = client.post("/login?next=http://malicioso.com/x", data={"email": "ana@correo.com", "password": "clave1234"})
    assert externo.headers["Location"].endswith("/dashboard/")
    client.post("/logout")
    interno = client.post("/login?next=/plan/", data={"email": "ana@correo.com", "password": "clave1234",
                                                      "recordarme": "y"})
    assert interno.headers["Location"] == "/plan/"
    assert registrar(client).status_code == 302  # logueado: /registro redirige
    client.post("/logout")
    corta = registrar(client, email="b@correo.com", password="corta")
    assert "al menos 8 caracteres" in corta.data.decode()


# ---------------------------------------------------------------------------
# 3. Examen de 120 preguntas por AJAX
# ---------------------------------------------------------------------------
def test_03_examen_120_ajax_finalizar_idempotente(app, client):
    registrar(client)
    intento_id = nuevo_examen(client)
    ids = orden(app, intento_id)
    assert len(ids) == 120
    for n, pid in enumerate(ids):
        r = responder(client, intento_id, pid, posicion(app, intento_id, pid, correcta=n % 4 != 0))
        assert r.status_code == 200 and r.get_json()["ok"]
    assert r.get_json()["respondidas"] == 120

    inicio = time.perf_counter()
    r = client.post(f"/examen/{intento_id}/finalizar")
    assert time.perf_counter() - inicio < 5
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/examen/{intento_id}/resultado")
    pagina = client.get(f"/examen/{intento_id}/resultado")
    assert pagina.status_code == 200 and "7.50" in pagina.data.decode()
    assert en_bd(app, lambda: (db.session.get(Intento, intento_id).aciertos, db.session.get(Intento, intento_id).nota)) == (90, 7.5)

    g = client.get(f"/examen/{intento_id}/finalizar")                    # GET no rompe
    assert g.status_code == 302 and g.headers["Location"].endswith(f"/examen/{intento_id}")

    def manipular():
        intento = db.session.get(Intento, intento_id)
        intento.aciertos = 0                                              # si recalculara, volvería a 90
        db.session.commit()
    en_bd(app, manipular)
    assert client.post(f"/examen/{intento_id}/finalizar").status_code == 302
    assert en_bd(app, lambda: db.session.get(Intento, intento_id).aciertos) == 0
    assert responder(client, intento_id, ids[0], 0).status_code == 409   # completado = inmutable


def test_03b_guardado_ajax_exige_csrf(tmp_path):
    from app import create_app

    class ConCSRF(config.TestingConfig):
        WTF_CSRF_ENABLED = True
    aplicacion = create_app(ConCSRF)
    client = aplicacion.test_client()
    token = lambda pagina: re.search(r'name="csrf_token" (?:type="hidden" )?value="([^"]+)"', pagina).group(1)  # noqa: E731
    pagina = client.get("/registro").data.decode()
    client.post("/registro", data={"csrf_token": token(pagina), "nombre_completo": "C", "email": "c@c.com",
                                   "password": "clave1234", "confirmar": "clave1234"})
    pagina = client.get("/examen/configurar").data.decode()
    r = client.post("/examen/configurar", data={"csrf_token": token(pagina), "modo": "nucleo", "nucleo": "2",
                                                "segundos_por_pregunta": "60"})
    intento_id = int(r.headers["Location"].rsplit("/", 1)[1])
    pagina = client.get(f"/examen/{intento_id}").data.decode()
    meta = re.search(r'<meta name="csrf-token" content="([^"]+)"', pagina).group(1)
    pid = json.loads(html.unescape(re.search(r'id="datos-examen" type="application/json">(.*?)</script>', pagina,
                                             re.S).group(1)))["preguntas"][0]["id"]
    sin_token = client.post(f"/examen/{intento_id}/responder", json={"pregunta_id": pid, "posicion": 1})
    assert sin_token.status_code == 400
    con_token = client.post(f"/examen/{intento_id}/responder", json={"pregunta_id": pid, "posicion": 1},
                            headers={"X-CSRFToken": meta})
    assert con_token.status_code == 200 and con_token.get_json()["ok"]
    with aplicacion.app_context():
        db.drop_all()


# ---------------------------------------------------------------------------
# 4. Temporizador persistente y expiración
# ---------------------------------------------------------------------------
def test_04_temporizador_persiste_y_expira(app, client):
    registrar(client)
    intento_id = nuevo_examen(client, modo="nucleo", nucleo="3")         # 30 × 60 s = 1800 s
    retrasar_inicio(app, Intento, intento_id, 600)
    for _ in range(2):                                                   # recargar dos veces
        restante = datos_json(client.get(f"/examen/{intento_id}"), "datos-examen")["restante"]
        assert 1190 <= restante <= 1200
    assert 1190 <= client.get(f"/examen/{intento_id}/tiempo").get_json()["restante"] <= 1200

    ids = orden(app, intento_id)
    responder(client, intento_id, ids[0], posicion(app, intento_id, ids[0]))
    responder(client, intento_id, ids[1], posicion(app, intento_id, ids[1], correcta=False))
    retrasar_inicio(app, Intento, intento_id, 1900)                      # tiempo agotado
    assert responder(client, intento_id, ids[2], 0).get_json().get("expirado") is True
    r = client.get(f"/examen/{intento_id}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/resultado")

    def estado():
        intento = db.session.get(Intento, intento_id)
        respuestas = Respuesta.query.filter_by(intento_id=intento_id).all()
        blancos = sum(1 for x in respuestas if x.opcion_elegida is None)
        return intento.completado, len(respuestas), blancos, intento.nota, intento.duracion_segundos
    completado, total, blancos, nota, duracion = en_bd(app, estado)
    assert completado and total == 30 and blancos == 28 and nota == 0.33 and duracion == 1800
    assert "Sin responder" in client.get(f"/examen/{intento_id}/resultado").data.decode()


# ---------------------------------------------------------------------------
# 5. Barajado: verde en la correcta real, rojo en la elegida
# ---------------------------------------------------------------------------
def test_05_barajado_colores_en_resultado_y_revision(app, client):
    registrar(client)
    intento_id = nuevo_examen(client, modo="nivel", nivel="dificil")
    ids = orden(app, intento_id)
    mapeos = en_bd(app, lambda: db.session.get(Intento, intento_id).mapeo_opciones)
    assert any(m != [0, 1, 2, 3] for m in mapeos.values())                # realmente barajado
    fallada, acertada = ids[0], ids[1]
    pos_mala = posicion(app, intento_id, fallada, correcta=False)
    responder(client, intento_id, fallada, pos_mala)
    responder(client, intento_id, acertada, posicion(app, intento_id, acertada))
    client.post(f"/examen/{intento_id}/finalizar")

    pregunta = en_bd(app, lambda: db.session.get(Pregunta, fallada))
    texto_correcto = pregunta.opciones[pregunta.correcta]
    texto_elegido = pregunta.opciones[mapeos[str(fallada)][pos_mala]]
    for url in (f"/examen/{intento_id}/resultado", f"/dashboard/revision/{intento_id}"):
        pagina = client.get(url).data.decode()
        tarjeta = pagina.split('data-resultado="incorrecta"')[1].split('class="card mb-3 item-revision')[0]
        verde = re.search(r'text-success border-success bg-success-subtle[^"]*">\s*<strong>([A-D])\.</strong>\s*'
                          r'<span class="texto-opcion">(.*?)</span>', tarjeta, re.S)
        rojo = re.search(r'text-danger border-danger bg-danger-subtle[^"]*">\s*<strong>([A-D])\.</strong>\s*'
                         r'<span class="texto-opcion">(.*?)</span>', tarjeta, re.S)
        assert html.unescape(verde.group(2)) == texto_correcto and "✓" in tarjeta
        assert html.unescape(rojo.group(2)) == texto_elegido and "✗" in tarjeta
        assert rojo.group(1) == "ABCD"[pos_mala]                          # en la posición que vio
        assert verde.group(1) == "ABCD"[mapeos[str(fallada)].index(pregunta.correcta)]


# ---------------------------------------------------------------------------
# 6. Cálculo de notas
# ---------------------------------------------------------------------------
def test_06_notas_sobre_el_total(app, client):
    registrar(client)
    uno = nuevo_examen(client, modo="nucleo", nucleo="1")
    pid = orden(app, uno)[0]
    responder(client, uno, pid, posicion(app, uno, pid))
    client.post(f"/examen/{uno}/finalizar")
    assert en_bd(app, lambda: db.session.get(Intento, uno).nota) == 0.33

    completo = nuevo_examen(client)
    for pid in orden(app, completo)[:60]:
        responder(client, completo, pid, posicion(app, completo, pid))
    client.post(f"/examen/{completo}/finalizar")
    assert en_bd(app, lambda: db.session.get(Intento, completo).nota) == 5.0
    assert "5.00" in client.get(f"/examen/{completo}/resultado").data.decode()


# ---------------------------------------------------------------------------
# 7. Modo fallidas
# ---------------------------------------------------------------------------
def test_07_modo_fallidas(app, client):
    registrar(client)
    r = client.post("/examen/configurar", data={"modo": "fallidas", "segundos_por_pregunta": "60"},
                    follow_redirects=True)
    assert "No tienes preguntas falladas" in r.data.decode()
    assert en_bd(app, lambda: Intento.query.count()) == 0

    tema = nuevo_examen(client, modo="tema", tema="n2-usuarios-y-privilegios-en-mysql")
    ids = orden(app, tema)
    responder(client, tema, ids[0], posicion(app, tema, ids[0], correcta=False))   # fallada
    # ids[1] se deja en blanco
    client.post(f"/examen/{tema}/finalizar")
    uid = en_bd(app, lambda: Usuario.query.first().id)
    falladas = en_bd(app, lambda: estadisticas.resumen_teoria(uid).falladas_ids)
    assert falladas == [ids[0]]                                         # la blanca no es fallada

    solo = nuevo_examen(client, modo="fallidas")
    assert orden(app, solo) == [ids[0]]
    responder(client, solo, ids[0], posicion(app, solo, ids[0]))
    client.post(f"/examen/{solo}/finalizar")
    assert en_bd(app, lambda: estadisticas.resumen_teoria(uid).falladas_ids) == []
    r = client.post("/examen/configurar", data={"modo": "fallidas", "segundos_por_pregunta": "60"})
    assert r.status_code == 302 and "configurar" in r.headers["Location"]


# ---------------------------------------------------------------------------
# 8. Aislamiento entre usuarios
# ---------------------------------------------------------------------------
def test_08_aislamiento_403(app, client, otro_client):
    registrar(client)
    intento_id = nuevo_examen(client, modo="nucleo", nucleo="2")
    crear_plan(client)
    plan_id = plan_activo(app)
    sesion_id = sesiones(app, plan_id)[0]["id"]
    practica_id = intento_practico(client, "P1")
    client.post(f"/practica/intento/{practica_id}/descartar")
    practica_id = intento_practico(client, "P3")

    registrar(otro_client, email="beto@correo.com", nombre="Beto")
    peticiones = [
        ("get", f"/examen/{intento_id}"), ("get", f"/examen/{intento_id}/resultado"),
        ("get", f"/examen/{intento_id}/tiempo"), ("post", f"/examen/{intento_id}/finalizar"),
        ("post", f"/examen/{intento_id}/descartar"), ("get", f"/dashboard/revision/{intento_id}"),
        ("get", f"/plan/{plan_id}"), ("get", f"/plan/sesion/{sesion_id}/iniciar"),
        ("post", f"/plan/sesion/{sesion_id}/omitir"), ("post", f"/plan/sesion/{sesion_id}/terminar"),
        ("get", f"/estudio/tema/n1-patron-mvc?sesion={sesion_id}"),
        ("get", f"/examen/configurar?sesion={sesion_id}"),
        ("get", f"/practica/intento/{practica_id}"), ("get", f"/practica/intento/{practica_id}/tiempo"),
        ("post", f"/practica/intento/{practica_id}/terminar"),
        ("get", f"/practica/intento/{practica_id}/autoevaluar"),
        ("get", f"/practica/intento/{practica_id}/resultado"),
        ("post", f"/practica/intento/{practica_id}/descartar"),
    ]
    for metodo, url in peticiones:
        assert getattr(otro_client, metodo)(url).status_code == 403, url
    r = otro_client.post(f"/examen/{intento_id}/responder", json={"pregunta_id": 1, "posicion": 0})
    assert r.status_code == 403 and r.get_json()["ok"] is False
    assert otro_client.post(f"/practica/intento/{practica_id}/guardar", json={"notas": "x"}).status_code == 403
    assert client.get(f"/examen/{intento_id}").status_code == 200      # el dueño sí entra


# ---------------------------------------------------------------------------
# 9. Práctica
# ---------------------------------------------------------------------------
def test_09a_practica_muestra_los_4_casos(client):
    registrar(client)
    pagina = client.get("/practica/").data.decode()
    for codigo, fragmento in (("P1", "VetCare"), ("P2", "EduTech"), ("P3", "Reserva de mesas"), ("P4", "playlists")):
        assert codigo in pagina and fragmento in pagina
    assert pagina.count("Ver caso") == 4


def test_09b_intento_checklist_autoevaluacion_y_topes(app, client):
    registrar(client)
    intento_id = intento_practico(client, "P2")
    tareas = ["P2-R1-T1", "P2-R1-T2", "P2-R4-T1"]
    r = client.post(f"/practica/intento/{intento_id}/guardar", json={"tareas_ok": tareas, "notas": "BEFORE por la FK"})
    assert r.get_json()["ok"]
    assert client.post(f"/practica/intento/{intento_id}/guardar", json={"tareas_ok": ["NO-EXISTE"]}).status_code == 400
    assert client.get(f"/practica/intento/{intento_id}/autoevaluar").status_code == 302  # primero terminar
    assert client.post(f"/practica/intento/{intento_id}/terminar").status_code == 302
    pagina = client.get(f"/practica/intento/{intento_id}/autoevaluar").data.decode()
    assert "Marca una tarea solo si ejecutaste su verificación." in pagina
    assert "0.50" in pagina and "1.00" in pagina                     # sugeridos P2-R1 (2/4 de 1.0) y P2-R4 (1/2 de 2.0)

    excede = autoevaluar(client, app, intento_id, valores={"P2-R1": 1.5})
    assert excede.status_code == 400 and "no puede superar el máximo" in excede.data.decode()
    paso = autoevaluar(client, app, intento_id, valores={"P2-R2": 0.3})
    assert paso.status_code == 400
    assert en_bd(app, lambda: EvaluacionCriterio.query.count()) == 0

    ok = autoevaluar(client, app, intento_id, fraccion=1.0)
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/resultado")

    def estado():
        ip = db.session.get(IntentoPractico, intento_id)
        evs = EvaluacionCriterio.query.filter_by(intento_practico_id=intento_id).all()
        return ip.completado, ip.nota_autoevaluada, len(evs), all(e.puntaje_final <= e.puntaje_maximo for e in evs), \
            {e.criterio_id: e.puntaje_sugerido for e in evs}
    completado, nota, n, dentro, sugeridos = en_bd(app, estado)
    assert completado and nota == 10.0 and n == 6 and dentro
    assert sugeridos["P2-R1"] == 0.5 and sugeridos["P2-R4"] == 1.0
    assert client.get(f"/practica/intento/{intento_id}/resultado").status_code == 200
    assert autoevaluar(client, app, intento_id, fraccion=0).status_code == 302   # inmutable: redirige
    assert en_bd(app, lambda: db.session.get(IntentoPractico, intento_id).nota_autoevaluada) == 10.0


def test_09c_cronometro_practico_persiste_y_autotermina(app, client):
    registrar(client)
    intento_id = intento_practico(client, "P3", minutos=120)            # 7200 s
    retrasar_inicio(app, IntentoPractico, intento_id, 1000)
    for _ in range(2):
        restante = datos_json(client.get(f"/practica/intento/{intento_id}"), "datos-intento-practico")["restante"]
        assert 6190 <= restante <= 6200
    retrasar_inicio(app, IntentoPractico, intento_id, 7300)
    assert client.post(f"/practica/intento/{intento_id}/guardar", json={"notas": "tarde"}).status_code == 409
    r = client.get(f"/practica/intento/{intento_id}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/autoevaluar")
    fin, duracion = en_bd(app, lambda: (db.session.get(IntentoPractico, intento_id).fecha_fin,
                                        db.session.get(IntentoPractico, intento_id).duracion_segundos))
    assert fin is not None and duracion == 7200


def test_09d_solo_p2_tiene_referencia(client):
    registrar(client)
    for codigo in ("P1", "P2", "P3", "P4"):
        pagina = client.get(f"/practica/{codigo}").data.decode()
        assert ('id="pestana-referencia"' in pagina) == (codigo == "P2"), codigo
    p2 = client.get("/practica/P2").data.decode()
    assert "La de PostgreSQL fue probada en un servidor real" in p2
    assert "trg_eliminar_matriculas_curso" in p2 and "db.cursos.aggregate" in p2
    assert "Confírmalo con tu docente" in p2


def test_09e_recursos_sin_path_traversal(client):
    registrar(client)
    ok = client.get("/practica/recurso/cursos_backup.sql")
    assert ok.status_code == 200 and ok.mimetype == "text/plain" and b"CREATE TABLE estudiantes" in ok.data
    assert client.get("/practica/recurso/referencia_n2_mongo.js").mimetype == "text/plain"
    for malo in ("../preguntas.json", "..%2Fpreguntas.json", "%2e%2e/preguntas.json", "..%5Cpreguntas.json",
                 "../../config.py", "recursos/../../app.py", "no-existe.sql"):
        assert client.get(f"/practica/recurso/{malo}").status_code == 404, malo


def test_09f_defensa_guarda_y_modo_oral_de_2_minutos(app, client):
    registrar(client)
    pagina = client.get("/practica/P2/defensa")
    datos = datos_json(pagina, "datos-defensa")
    assert datos["segundosOral"] == 120 and len(datos["tarjetas"]) == 7
    assert "Simulacro oral (2 min/pregunta)" in pagina.data.decode()
    r = client.post("/practica/P2/defensa/calificar", json={"indice": 0, "nivel": "dominado"})
    assert r.get_json()["ok"] and r.get_json()["dominio"] == round(100 / 7, 1)
    client.post("/practica/P2/defensa/calificar", json={"indice": 1, "nivel": "parcial"})
    assert client.post("/practica/P2/defensa/calificar", json={"indice": 99, "nivel": "dominado"}).status_code == 400
    assert client.post("/practica/P2/defensa/calificar", json={"indice": 0, "nivel": "experto"}).status_code == 400
    assert en_bd(app, lambda: RepasoDefensa.query.count()) == 2
    assert datos_json(client.get("/practica/P2/defensa"), "datos-defensa")["tarjetas"][0]["nivel"] == "dominado"


# ---------------------------------------------------------------------------
# 10. Plan de estudio
# ---------------------------------------------------------------------------
def test_10a_plan_30_dias_2h_todas_las_fases(app, client):
    registrar(client)
    r = crear_plan(client, dias=30, horas=2)
    assert r.status_code == 302
    lista = sesiones(app, plan_activo(app))
    assert {s["fase"] for s in lista} == {"diagnostico", "cobertura", "refuerzo", "simulacro", "repaso_final"}
    diag = [s for s in lista if s["fase"] == "diagnostico"]
    assert sum(s["tipo"] == "simulacro_nucleo" for s in diag) == 4
    assert sorted(s["caso_codigo"] for s in diag if s["tipo"] == "intento_practico") == ["P1", "P2", "P3", "P4"]
    por_dia = {}
    for s in lista:
        por_dia[s["fecha"]] = por_dia.get(s["fecha"], 0) + s["minutos"]
    assert max(por_dia.values()) <= 120
    pagina = client.get("/plan/").data.decode()
    assert "Faltan 30" in pagina and "Hoy toca" in pagina
    assert client.get("/plan/semana").status_code == 200 and client.get("/plan/semana?vista=mes").status_code == 200


def test_10b_examen_en_2_dias_modo_intensivo(app, client):
    registrar(client)
    r = crear_plan(client, dias=2, horas=2)
    assert r.status_code == 302
    avisos = en_bd(app, lambda: db.session.get(PlanEstudio, plan_activo(app)).advertencias)
    assert any("Modo intensivo" in a["texto"] for a in avisos)
    assert "Modo intensivo" in client.get("/plan/").data.decode()


def test_10c_tiempo_insuficiente_advierte_en_rojo(app, client):
    registrar(client)
    crear_plan(client, dias=6, horas=1)
    avisos = en_bd(app, lambda: db.session.get(PlanEstudio, plan_activo(app)).advertencias)
    textos = " ".join(a["texto"] for a in avisos)
    assert "Tiempo insuficiente" in textos and "faltan aprox." in textos and "Sin cubrir" in textos
    pagina = client.get("/plan/").data.decode()
    assert 'alert alert-danger py-2 mb-1 fw-semibold">Tiempo insuficiente' in pagina


@pytest.mark.parametrize("dias", [0, -1])
def test_10d_examen_hoy_o_pasado_sin_plan(app, client, dias):
    registrar(client)
    r = crear_plan(client, dias=dias, inicio=date.today() - timedelta(days=5))
    assert r.status_code == 200 and "El examen es hoy o ya pasó" in r.data.decode()
    assert en_bd(app, lambda: PlanEstudio.query.count()) == 0


def test_10e_cero_horas_error_de_validacion(app, client):
    registrar(client)
    r = crear_plan(client, horas=0)
    assert r.status_code == 200 and "Asigna horas de estudio al menos a un día" in r.data.decode()
    assert en_bd(app, lambda: PlanEstudio.query.count()) == 0
    r = crear_plan(client, peso_teoria="60", peso_practica="60")
    assert "deben sumar 100" in r.data.decode()


def test_10f_ultimo_dia_solo_repaso_ligero(app, client):
    registrar(client)
    crear_plan(client, dias=15, horas=3)
    lista = sesiones(app, plan_activo(app))
    ultimo = max(s["fecha"] for s in lista)
    del_ultimo = [s for s in lista if s["fecha"] == ultimo]
    assert ultimo == date.today() + timedelta(days=14)
    assert [s["tipo"] for s in del_ultimo] == ["repaso_ligero"] and del_ultimo[0]["minutos"] <= 60


def test_10g_porcentaje_practica_cambia_reparto(app, client):
    registrar(client)
    practica = lambda lista: sum(s["minutos"] for s in lista if s["tipo"] in ("practica_caso", "intento_practico", "defensa"))  # noqa: E731
    crear_plan(client, pct=20)
    poco = practica(sesiones(app, plan_activo(app)))
    crear_plan(client, pct=80)
    mucho = practica(sesiones(app, plan_activo(app)))
    assert mucho > poco
    assert en_bd(app, lambda: PlanEstudio.query.filter_by(activo=True).count()) == 1
    assert en_bd(app, lambda: PlanEstudio.query.count()) == 2          # el anterior se conserva inactivo


# ---------------------------------------------------------------------------
# 11. Recálculo dinámico
# ---------------------------------------------------------------------------
def test_11_recalculo(app, client):
    registrar(client)
    crear_plan(client, dias=30, horas=3)
    plan_id = plan_activo(app)
    tema = "n2-triggers-en-mysql"

    # Todo correcto en un simulacro completo: ningún tema necesita cobertura.
    completo = nuevo_examen(client)
    for pid in orden(app, completo):
        responder(client, completo, pid, posicion(app, completo, pid))
    client.post(f"/examen/{completo}/finalizar")
    antes = [s for s in sesiones(app, plan_id) if s["fase"] == "cobertura" and s["tema_slug"] == tema]
    assert not antes

    # Muchos fallos en un tema: sube de prioridad (vuelve a la cobertura, la primera de teoría).
    fallos = nuevo_examen(client, modo="tema", tema=tema)
    for pid in orden(app, fallos):
        responder(client, fallos, pid, posicion(app, fallos, pid, correcta=False))
    client.post(f"/examen/{fallos}/finalizar")
    cobertura_teoria = [s for s in sesiones(app, plan_id) if s["fase"] == "cobertura" and s["tema_slug"]
                        and s["estado"] == "pendiente"]
    assert cobertura_teoria and cobertura_teoria[0]["tema_slug"] == tema

    # Intento práctico con un criterio bajo: se agenda practica_caso sobre ese criterio.
    ip = intento_practico(client, "P1")
    client.post(f"/practica/intento/{ip}/terminar")
    autoevaluar(client, app, ip, fraccion=1.0, valores={"P1-R2": 0})
    criterios = {s["criterio_id"] for s in sesiones(app, plan_id) if s["tipo"] == "practica_caso" and s["estado"] == "pendiente"}
    assert "P1-R2" in criterios and "P1-R4" not in criterios

    # Una sesión completada no cambia; una atrasada se reprograma.
    lista = sesiones(app, plan_id)
    tarjetas = next(s for s in lista if s["tipo"] in ("tarjetas", "defensa", "practica_caso") and s["estado"] == "pendiente")
    assert client.post(f"/plan/sesion/{tarjetas['id']}/terminar", json={"minutos_reales": 15}).get_json()["ok"]
    pendiente = next(s for s in sesiones(app, plan_id) if s["estado"] == "pendiente"
                     and s["tipo"] in ("tarjetas", "practica_caso", "fallidas", "practica_tema"))

    def atrasar():
        s = db.session.get(SesionEstudio, pendiente["id"])
        s.fecha = date.today() - timedelta(days=2)
        db.session.commit()
    en_bd(app, atrasar)
    assert "atrasada" in client.get("/plan/").data.decode()
    assert client.post("/plan/recalcular").status_code == 302
    despues = {s["id"]: s for s in sesiones(app, plan_id)}
    assert despues[tarjetas["id"]]["estado"] == "completada" and despues[tarjetas["id"]]["fecha"] == tarjetas["fecha"]
    assert pendiente["id"] in despues and despues[pendiente["id"]]["fecha"] >= date.today()
    assert en_bd(app, lambda: db.session.get(PlanEstudio, plan_id).ultima_recalculacion) is not None


def test_11b_omitir_reprograma(app, client):
    registrar(client)
    crear_plan(client, dias=20, horas=2)
    plan_id = plan_activo(app)
    primera = sesiones(app, plan_id)[0]
    assert client.post(f"/plan/sesion/{primera['id']}/omitir").status_code == 302
    assert {s["id"]: s for s in sesiones(app, plan_id)}[primera["id"]]["estado"] == "omitida"


def test_11c_sesion_de_plan_se_completa_al_finalizar_intento(app, client):
    registrar(client)
    crear_plan(client, dias=20, horas=2)
    plan_id = plan_activo(app)
    diag = next(s for s in sesiones(app, plan_id) if s["tipo"] == "simulacro_nucleo")
    r = client.get(f"/plan/sesion/{diag['id']}/iniciar")
    assert "modo=nucleo" in r.headers["Location"] and f"sesion={diag['id']}" in r.headers["Location"]
    intento_id = nuevo_examen(client, modo="nucleo", nucleo="1", sesion=str(diag["id"]))
    pid = orden(app, intento_id)[0]
    responder(client, intento_id, pid, posicion(app, intento_id, pid))
    client.post(f"/examen/{intento_id}/finalizar")
    fila = en_bd(app, lambda: db.session.get(SesionEstudio, diag["id"]))
    assert fila.estado == "completada" and fila.resultado_aciertos == 1 and fila.resultado_total == 30


# ---------------------------------------------------------------------------
# 12. Veredicto (casos de datos en tests/test_veredicto.py)
# ---------------------------------------------------------------------------
def test_12_veredicto_sin_datos_en_la_web(app, client):
    registrar(client)
    pagina = client.get("/plan/veredicto").data.decode()
    assert "SIN DATOS" in pagina and "Faltan datos para emitir el veredicto" in pagina
    assert "Haz al menos un simulacro válido" in pagina
    for codigo in ("P1", "P2", "P3", "P4"):
        assert f"Haz un intento cronometrado y autoevaluado del caso {codigo}" in pagina
    assert pagina.count("Hacerlo ahora") == 5
    assert "no garantiza el resultado del examen real" in pagina
    for codigo in ("T1", "T2", "T3", "T4", "T5", "T6", "P1", "P2", "P3", "P4", "C1"):
        assert f"<strong>{codigo}</strong>" in pagina
    assert en_bd(app, lambda: VeredictoDiario.query.count()) == 1


def test_12b_simulacro_afortunado_en_la_web_no_da_apto(app, client):
    registrar(client)
    completo = nuevo_examen(client)
    for pid in orden(app, completo):
        responder(client, completo, pid, posicion(app, completo, pid))
    client.post(f"/examen/{completo}/finalizar")
    for codigo in ("P1", "P2", "P3", "P4"):
        ip = intento_practico(client, codigo)
        client.post(f"/practica/intento/{ip}/terminar")
        autoevaluar(client, app, ip, fraccion=1.0)
    for i in range(7):
        client.post("/practica/P2/defensa/calificar", json={"indice": i, "nivel": "dominado"})
    pagina = client.get("/plan/veredicto").data.decode()
    assert "EN RIESGO" in pagina and ">APTO<" not in pagina             # 1 simulacro 10/10: T5 y T6 fallan
    assert "9.50" in pagina                                             # práctica 10 ajustada a 9.5


# ---------------------------------------------------------------------------
# 13. Tarjetas
# ---------------------------------------------------------------------------
def test_13_tarjetas_no_sabia_primero_y_sin_efecto_en_notas(app, client):
    registrar(client)
    slug = "n1-patron-mvc"
    tarjetas = datos_json(client.get(f"/estudio/tema/{slug}"), "datos-tarjetas")
    ultima = tarjetas[-1]["id"]
    primera = tarjetas[0]["id"]
    assert client.post("/estudio/tarjeta", json={"pregunta_id": primera, "sabia": True}).get_json()["ok"]
    assert client.post("/estudio/tarjeta", json={"pregunta_id": ultima, "sabia": False}).get_json()["ok"]
    nuevas = datos_json(client.get(f"/estudio/tema/{slug}"), "datos-tarjetas")
    assert nuevas[0]["id"] == ultima and nuevas[0]["previo"] == "no_sabia"
    assert nuevas[-1]["id"] == primera
    uid = en_bd(app, lambda: Usuario.query.first().id)

    def efecto():
        r = estadisticas.resumen_teoria(uid)
        return r.respondidas_unicas, r.dominadas, Intento.query.count(), RepasoTarjeta.query.count()
    assert en_bd(app, efecto) == (0, 0, 0, 2)
    assert "SIN DATOS" in client.get("/plan/veredicto").data.decode()


# ---------------------------------------------------------------------------
# 15. Puntos por confirmar con el docente
# ---------------------------------------------------------------------------
def test_15_pendientes_docente_y_enlaces(client):
    registrar(client)
    pagina = client.get("/plan/pendientes-docente").data.decode()
    for texto in ("Nota mínima de aprobación", "Ponderación teoría / práctica", "Duración del examen práctico",
                  "Motor de base de datos del caso N2", "Formato de la defensa oral", "Requisitos 19–22 y 24",
                  "duración en la API del caso N4", "dos sistemas de navegación", "localStorage"):
        assert texto in pagina, texto
    enlace = 'href="/plan/pendientes-docente"'
    assert enlace in client.get("/plan/").data.decode()
    assert enlace in client.get("/plan/veredicto").data.decode()
    crear_plan(client)
    assert enlace in client.get("/plan/").data.decode()
