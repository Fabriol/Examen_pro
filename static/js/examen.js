/* Examen teórico: navegación, guardado AJAX (con CSRF), marcas en localStorage
   y temporizador regresivo anclado al servidor (re-sincroniza cada 20 s). */
(function () {
  'use strict';

  var datos = JSON.parse(document.getElementById('datos-examen').textContent);
  var preguntas = datos.preguntas;
  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
  var claveMarcas = 'examen-' + datos.intentoId + '-marcadas';

  function porId(id) { return document.getElementById(id); }
  var el = {
    enunciado: porId('enunciado'),
    opciones: porId('opciones'),
    numActual: porId('num-actual'),
    meta: porId('meta-pregunta'),
    grilla: porId('grilla'),
    anterior: porId('btn-anterior'),
    siguiente: porId('btn-siguiente'),
    marcar: porId('btn-marcar'),
    borrar: porId('btn-borrar'),
    temporizador: porId('temporizador'),
    contador: porId('contador-respondidas'),
    aviso: porId('aviso-guardado'),
    textoSinResponder: porId('texto-sin-responder'),
    confirmar: porId('btn-confirmar-finalizar'),
    formFinalizar: porId('form-finalizar'),
    modal: porId('modal-finalizar')
  };

  var actual = 0;
  var entrada = Date.now();          // cuándo se mostró la pregunta actual
  var finalizando = false;
  var finTs = Date.now() + datos.restante * 1000;
  var pendientes = {};               // respuestas que fallaron por red: {pregunta_id: cuerpo}
  var marcadas = new Set(leerMarcas());

  // ----- Marcas (localStorage) -----
  function leerMarcas() {
    try { return JSON.parse(localStorage.getItem(claveMarcas) || '[]'); } catch (e) { return []; }
  }
  function guardarMarcas() {
    try { localStorage.setItem(claveMarcas, JSON.stringify(Array.from(marcadas))); } catch (e) { /* sin almacenamiento */ }
  }
  function limpiarMarcas() {
    try { localStorage.removeItem(claveMarcas); } catch (e) { /* sin almacenamiento */ }
  }

  // ----- Guardado -----
  function segundosEnPregunta() {
    var s = Math.round((Date.now() - entrada) / 1000);
    entrada = Date.now();
    return s;
  }

  function mostrarAviso(texto) {
    el.aviso.textContent = texto;
    el.aviso.classList.remove('d-none');
  }
  function ocultarAviso() { el.aviso.classList.add('d-none'); }

  function enviar(cuerpo) {
    return fetch(datos.urls.responder, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
      body: JSON.stringify(cuerpo)
    })
      .then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
      .then(function (j) {
        if (j.ok) {
          delete pendientes[cuerpo.pregunta_id];
          ocultarAviso();
          return j;
        }
        if (j.completado) {
          limpiarMarcas();
          window.location.href = j.redirect || datos.urls.resultado;
        } else if (j.expirado) {
          finalizar(true);
        } else {
          mostrarAviso(j.error || 'No se pudo guardar la respuesta.');
        }
        return j;
      })
      .catch(function () {
        if (cuerpo.accion !== 'tiempo') { pendientes[cuerpo.pregunta_id] = cuerpo; }
        mostrarAviso('Sin conexión: se reintentará guardar tus respuestas automáticamente.');
      });
  }

  function reintentarPendientes() {
    Object.keys(pendientes).forEach(function (id) { enviar(pendientes[id]); });
  }

  // ----- Render -----
  function respondidas() {
    return preguntas.filter(function (p) { return p.seleccion !== null && p.seleccion !== undefined; }).length;
  }

  function render() {
    var p = preguntas[actual];
    el.numActual.textContent = actual + 1;
    el.meta.textContent = p.codigo + ' · ' + p.tema + ' · ' + p.nivel;
    el.enunciado.textContent = p.enunciado;

    el.opciones.innerHTML = '';
    p.opciones.forEach(function (texto, pos) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'list-group-item list-group-item-action opcion-examen' + (p.seleccion === pos ? ' active' : '');
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', p.seleccion === pos ? 'true' : 'false');
      var letra = document.createElement('span');
      letra.className = 'letra-opcion';
      letra.textContent = 'ABCD'.charAt(pos) + '.';
      var cuerpo = document.createElement('span');
      cuerpo.className = 'texto-opcion';
      cuerpo.textContent = texto;
      b.appendChild(letra);
      b.appendChild(cuerpo);
      b.addEventListener('click', function () { seleccionar(pos); });
      el.opciones.appendChild(b);
    });

    el.anterior.disabled = actual === 0;
    el.siguiente.disabled = actual === preguntas.length - 1;
    var marcada = marcadas.has(p.id);
    el.marcar.classList.toggle('btn-warning', marcada);
    el.marcar.classList.toggle('btn-outline-warning', !marcada);
    el.marcar.querySelector('span').textContent = marcada ? 'Desmarcar' : 'Marcar';
    el.borrar.disabled = p.seleccion === null || p.seleccion === undefined;
    el.contador.textContent = respondidas();
    renderGrilla();
  }

  function renderGrilla() {
    el.grilla.innerHTML = '';
    preguntas.forEach(function (p, i) {
      var b = document.createElement('button');
      b.type = 'button';
      var respondida = p.seleccion !== null && p.seleccion !== undefined;
      var clase = 'btn btn-sm celda-grilla ';
      if (marcadas.has(p.id)) {
        clase += 'btn-warning';
      } else if (respondida) {
        clase += 'btn-primary';
      } else {
        clase += 'btn-outline-secondary';
      }
      if (respondida) { clase += ' respondida'; }
      if (i === actual) { clase += ' actual'; }
      b.className = clase;
      b.textContent = i + 1;
      b.title = 'Pregunta ' + (i + 1) + (respondida ? ' (respondida)' : ' (sin responder)') +
        (marcadas.has(p.id) ? ' · marcada' : '');
      b.addEventListener('click', function () { ir(i); });
      el.grilla.appendChild(b);
    });
  }

  // ----- Acciones -----
  function ir(i) {
    if (i < 0 || i >= preguntas.length || i === actual) { return; }
    var s = segundosEnPregunta();
    if (s > 0) { enviar({ pregunta_id: preguntas[actual].id, accion: 'tiempo', segundos: s }); }
    actual = i;
    render();
  }

  function seleccionar(pos) {
    if (finalizando) { return; }
    var p = preguntas[actual];
    p.seleccion = pos;
    render();
    enviar({ pregunta_id: p.id, posicion: pos, segundos: segundosEnPregunta() });
  }

  function borrar() {
    var p = preguntas[actual];
    if (p.seleccion === null || p.seleccion === undefined) { return; }
    p.seleccion = null;
    render();
    enviar({ pregunta_id: p.id, posicion: null, segundos: segundosEnPregunta() });
  }

  function alternarMarca() {
    var id = preguntas[actual].id;
    if (marcadas.has(id)) { marcadas.delete(id); } else { marcadas.add(id); }
    guardarMarcas();
    render();
  }

  function finalizar(auto) {
    if (finalizando) { return; }
    finalizando = true;
    var s = segundosEnPregunta();
    var envio = (!auto && s > 0)
      ? enviar({ pregunta_id: preguntas[actual].id, accion: 'tiempo', segundos: s })
      : Promise.resolve();
    limpiarMarcas();
    if (auto) { mostrarAviso('Tiempo agotado: finalizando el examen...'); }
    envio.then(function () { el.formFinalizar.submit(); }, function () { el.formFinalizar.submit(); });
  }

  // ----- Temporizador -----
  function formatear(s) {
    var m = Math.floor(s / 60);
    var r = s % 60;
    return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }

  function tick() {
    var rest = Math.max(0, Math.ceil((finTs - Date.now()) / 1000));
    el.temporizador.textContent = formatear(rest);
    var clase = 'badge fs-5 font-monospace ';
    if (rest < 60) {
      clase += 'text-bg-danger parpadeo';
    } else if (rest <= datos.limite * 0.25) {
      clase += 'text-bg-warning';
    } else {
      clase += 'text-bg-dark';
    }
    el.temporizador.className = clase;
    if (rest <= 0) { finalizar(true); }
  }

  function resincronizar() {
    fetch(datos.urls.tiempo, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.completado) {
          limpiarMarcas();
          window.location.href = datos.urls.resultado;
          return;
        }
        finTs = Date.now() + j.restante * 1000;
        reintentarPendientes();
      })
      .catch(function () { /* se reintenta en el siguiente ciclo */ });
  }

  // ----- Eventos -----
  el.anterior.addEventListener('click', function () { ir(actual - 1); });
  el.siguiente.addEventListener('click', function () { ir(actual + 1); });
  el.marcar.addEventListener('click', alternarMarca);
  el.borrar.addEventListener('click', borrar);
  el.confirmar.addEventListener('click', function () { finalizar(false); });

  el.modal.addEventListener('show.bs.modal', function () {
    var sin = preguntas.length - respondidas();
    var marcas = marcadas.size;
    var texto = sin === 0
      ? 'Has respondido todas las preguntas.'
      : 'Te quedan ' + sin + ' pregunta' + (sin === 1 ? '' : 's') + ' sin responder: quedarán en blanco y no suman.';
    if (marcas) { texto += ' Tienes ' + marcas + ' marcada' + (marcas === 1 ? '' : 's') + ' para revisar.'; }
    el.textoSinResponder.textContent = texto;
  });

  document.addEventListener('keydown', function (e) {
    if (finalizando || e.ctrlKey || e.metaKey || e.altKey) { return; }
    if (document.querySelector('.modal.show')) { return; }
    var etiqueta = (e.target && e.target.tagName) || '';
    if (etiqueta === 'INPUT' || etiqueta === 'TEXTAREA' || etiqueta === 'SELECT') { return; }
    var mapa = { '1': 0, '2': 1, '3': 2, '4': 3, 'a': 0, 'b': 1, 'c': 2, 'd': 3 };
    var tecla = e.key.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(mapa, tecla)) {
      seleccionar(mapa[tecla]);
      e.preventDefault();
    } else if (e.key === 'ArrowRight') {
      ir(actual + 1);
    } else if (e.key === 'ArrowLeft') {
      ir(actual - 1);
    }
  });

  // Al salir de la página, guarda el tiempo de la pregunta actual (sin bloquear la navegación).
  window.addEventListener('pagehide', function () {
    if (finalizando || !navigator.sendBeacon) { return; }
    var s = Math.round((Date.now() - entrada) / 1000);
    if (s <= 0) { return; }
    var fd = new FormData();
    fd.append('csrf_token', csrf);
    fd.append('pregunta_id', preguntas[actual].id);
    fd.append('accion', 'tiempo');
    fd.append('segundos', s);
    navigator.sendBeacon(datos.urls.responder, fd);
  });

  render();
  tick();
  setInterval(tick, 500);
  setInterval(resincronizar, datos.resync * 1000);
})();
