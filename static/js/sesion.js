/* Cronómetro de una sesión del plan de estudio (tarjetas, práctica de caso, defensa, repaso).
   Cuenta atrás desde minutos_planificados; el inicio se guarda en localStorage para que
   recargar la página no reinicie el reloj. "Terminar sesión" guarda minutos_reales. */
(function () {
  'use strict';

  var caja = document.getElementById('sesion-estudio');
  if (!caja) { return; }

  var id = caja.dataset.sesionId;
  var minutos = parseInt(caja.dataset.minutos, 10) || 0;
  var pendiente = caja.dataset.estado === 'pendiente';
  var reloj = document.getElementById('sesion-reloj');
  var boton = document.getElementById('sesion-terminar');
  var pausa = document.getElementById('sesion-pausa');
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute('content') : '';
  var clave = 'sesion-' + id + '-inicio';

  function leerInicio() {
    try {
      var guardado = parseInt(localStorage.getItem(clave), 10);
      if (guardado) { return guardado; }
      var ahora = Date.now();
      localStorage.setItem(clave, String(ahora));
      return ahora;
    } catch (e) {
      return Date.now();
    }
  }

  function formatear(s) {
    var neg = s < 0;
    s = Math.abs(s);
    var m = Math.floor(s / 60);
    var r = s % 60;
    return (neg ? '+' : '') + (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }

  if (!pendiente) {
    reloj.textContent = formatear(minutos * 60);
    reloj.className = 'badge text-bg-secondary fs-5 font-monospace';
    return;
  }

  var inicio = leerInicio();
  var avisoPausaMostrado = 0;

  function transcurridos() { return Math.floor((Date.now() - inicio) / 1000); }

  function tick() {
    var trans = transcurridos();
    var rest = minutos * 60 - trans;
    reloj.textContent = formatear(rest);
    var clase = 'badge fs-5 font-monospace ';
    if (rest <= 0) {
      clase += 'text-bg-success';
      reloj.title = 'Tiempo planificado cumplido (tiempo extra en curso)';
    } else if (rest < 60) {
      clase += 'text-bg-danger parpadeo';
    } else if (rest <= minutos * 60 * 0.25) {
      clase += 'text-bg-warning';
    } else {
      clase += 'text-bg-info';
    }
    reloj.className = clase;
    var bloques = Math.floor(trans / (50 * 60));
    if (pausa && bloques > avisoPausaMostrado) {
      avisoPausaMostrado = bloques;
      pausa.classList.remove('d-none');
      setTimeout(function () { pausa.classList.add('d-none'); }, 60000);
    }
  }

  function terminar() {
    boton.disabled = true;
    var minutosReales = Math.max(1, Math.ceil(transcurridos() / 60));
    fetch(caja.dataset.urlTerminar, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
      body: JSON.stringify({ minutos_reales: minutosReales })
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) { throw new Error(j.error || 'error'); }
        try { localStorage.removeItem(clave); } catch (e) { /* sin almacenamiento */ }
        window.location.href = j.redirect || caja.dataset.urlPlan;
      })
      .catch(function () {
        boton.disabled = false;
        alert('No se pudo guardar la sesión. Revisa tu conexión e inténtalo de nuevo.');
      });
  }

  if (boton) { boton.addEventListener('click', terminar); }
  tick();
  setInterval(tick, 1000);
})();
