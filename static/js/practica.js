/* Módulo de práctica:
   - Intento en curso: cronómetro regresivo anclado al servidor (re-sincroniza), autoguardado
     AJAX de la checklist y las notas, puntaje sugerido en vivo y autoterminación al expirar.
   - Defensa: autocalificación y simulacro oral (2 min por pregunta, prioriza no dominadas).
   - Página del caso: copiar código de referencia, atajo de minutos y pestaña de historial. */
(function () {
  'use strict';

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute('content') : '';

  function postJSON(url, cuerpo) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
      body: JSON.stringify(cuerpo)
    }).then(function (r) { return r.json(); });
  }

  function mmss(s) {
    var m = Math.floor(s / 60);
    var r = s % 60;
    return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }

  // =========================================================================
  // Página del caso
  // =========================================================================
  document.querySelectorAll('[data-copiar]').forEach(function (boton) {
    boton.addEventListener('click', function () {
      var nodo = document.querySelector(boton.dataset.copiar);
      if (!nodo) { return; }
      var texto = nodo.textContent;
      var ok = function () {
        var original = boton.innerHTML;
        boton.textContent = '¡Copiado!';
        setTimeout(function () { boton.innerHTML = original; }, 1500);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(texto).then(ok);
      } else {
        var area = document.createElement('textarea');
        area.value = texto;
        document.body.appendChild(area);
        area.select();
        try { document.execCommand('copy'); ok(); } catch (e) { /* sin portapapeles */ }
        document.body.removeChild(area);
      }
    });
  });

  document.querySelectorAll('.usar-minutos').forEach(function (enlace) {
    enlace.addEventListener('click', function (e) {
      e.preventDefault();
      var campo = document.getElementById('minutos');
      if (campo) { campo.value = enlace.dataset.minutos; }
    });
  });

  document.querySelectorAll('[data-abrir-pestana]').forEach(function (enlace) {
    enlace.addEventListener('click', function (e) {
      var boton = document.getElementById(enlace.dataset.abrirPestana);
      if (boton && window.bootstrap) {
        e.preventDefault();
        bootstrap.Tab.getOrCreateInstance(boton).show();
        boton.scrollIntoView({ behavior: 'smooth' });
      }
    });
  });

  // =========================================================================
  // Intento práctico en curso
  // =========================================================================
  var nodoIntento = document.getElementById('datos-intento-practico');
  if (nodoIntento) {
    var d = JSON.parse(nodoIntento.textContent);
    var reloj = document.getElementById('temporizador');
    var estado = document.getElementById('estado-guardado');
    var notas = document.getElementById('notas');
    var formTerminar = document.getElementById('form-terminar');
    var finTs = Date.now() + d.restante * 1000;
    var terminando = false;
    var temporizadorNotas = null;

    var tareasMarcadas = function () {
      return Array.prototype.map.call(document.querySelectorAll('.tarea-check:checked'), function (c) { return c.value; });
    };

    var actualizarSugeridos = function () {
      var marcadas = new Set(tareasMarcadas());
      var total = 0;
      d.criterios.forEach(function (c) {
        var hechas = c.tareas.filter(function (t) { return marcadas.has(t); }).length;
        var sugerido = c.tareas.length ? c.puntaje * hechas / c.tareas.length : 0;
        total += sugerido;
        var nodo = document.querySelector('.sugerido[data-criterio="' + c.id + '"]');
        if (nodo) { nodo.textContent = sugerido.toFixed(2); }
      });
      document.getElementById('nota-sugerida').textContent = total.toFixed(2);
    };

    var terminar = function (auto) {
      if (terminando) { return; }
      terminando = true;
      if (auto) { estado.textContent = 'Tiempo agotado: terminando...'; }
      guardar().then(function () { formTerminar.submit(); }, function () { formTerminar.submit(); });
    };

    var guardar = function () {
      estado.textContent = 'Guardando...';
      return postJSON(d.urls.guardar, { tareas_ok: tareasMarcadas(), notas: notas.value })
        .then(function (j) {
          if (j.ok) {
            estado.textContent = 'Guardado ✓';
          } else if (j.terminado || j.expirado) {
            window.location.href = j.redirect || d.urls.autoevaluar;
          } else {
            estado.textContent = j.error || 'No se pudo guardar';
          }
        })
        .catch(function () { estado.textContent = 'Sin conexión: se reintentará'; });
    };

    document.querySelectorAll('.tarea-check').forEach(function (c) {
      c.addEventListener('change', function () { actualizarSugeridos(); guardar(); });
    });
    notas.addEventListener('input', function () {
      estado.textContent = 'Cambios sin guardar...';
      clearTimeout(temporizadorNotas);
      temporizadorNotas = setTimeout(guardar, 1000);
    });
    document.getElementById('btn-terminar').addEventListener('click', function () { terminar(false); });

    var tick = function () {
      var rest = Math.max(0, Math.ceil((finTs - Date.now()) / 1000));
      reloj.textContent = mmss(rest);
      var clase = 'badge fs-5 font-monospace ';
      if (rest < 60) {
        clase += 'text-bg-danger parpadeo';
      } else if (rest <= d.limite * 0.25) {
        clase += 'text-bg-warning';
      } else {
        clase += 'text-bg-dark';
      }
      reloj.className = clase;
      if (rest <= 0) { terminar(true); }
    };

    var resincronizar = function () {
      fetch(d.urls.tiempo, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.terminado) { window.location.href = d.urls.autoevaluar; return; }
          finTs = Date.now() + j.restante * 1000;
          if (estado.textContent.indexOf('Sin conexión') === 0) { guardar(); }
        })
        .catch(function () { /* se reintenta en el siguiente ciclo */ });
    };

    actualizarSugeridos();
    tick();
    setInterval(tick, 500);
    setInterval(resincronizar, d.resync * 1000);
  }

  // =========================================================================
  // Defensa
  // =========================================================================
  var nodoDefensa = document.getElementById('datos-defensa');
  if (nodoDefensa) {
    var def = JSON.parse(nodoDefensa.textContent);
    var ETIQUETAS = { no_se: 'No sé', parcial: 'Parcial', dominado: 'Dominado' };
    var CLASES = { no_se: 'text-bg-danger', parcial: 'text-bg-warning', dominado: 'text-bg-success' };
    var PRIORIDAD = { no_se: 0, parcial: 1, dominado: 3 };

    var actualizarBarra = function (dominio) {
      var barra = document.querySelector('#barra-dominio .progress-bar');
      if (!barra) { return; }
      barra.style.width = dominio + '%';
      barra.textContent = Math.round(dominio) + '%';
      barra.className = 'progress-bar bg-' + (dominio >= 70 ? 'success' : (dominio >= 50 ? 'warning' : 'danger'));
    };

    var calificar = function (indice, nivel) {
      def.tarjetas.forEach(function (t) { if (t.indice === indice) { t.nivel = nivel; } });
      var insignia = document.querySelector('.tarjeta-defensa[data-indice="' + indice + '"] .nivel-defensa');
      if (insignia) {
        insignia.className = 'badge nivel-defensa align-self-start ' + CLASES[nivel];
        insignia.textContent = ETIQUETAS[nivel];
      }
      return postJSON(def.urlCalificar, { indice: indice, nivel: nivel })
        .then(function (j) { if (j.ok) { actualizarBarra(j.dominio); } })
        .catch(function () { alert('No se pudo guardar la calificación.'); });
    };

    document.querySelectorAll('.calificar').forEach(function (b) {
      b.addEventListener('click', function () {
        calificar(parseInt(b.dataset.indice, 10), b.dataset.nivel);
        b.parentElement.querySelectorAll('.calificar').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
      });
    });

    // ----- Simulacro oral -----
    var cola = [];
    var pos = 0;
    var finOral = 0;
    var intervaloOral = null;
    var $ = function (id) { return document.getElementById(id); };

    var ordenarCola = function () {
      var copia = def.tarjetas.slice();
      for (var i = copia.length - 1; i > 0; i--) {          // barajado Fisher-Yates
        var j = Math.floor(Math.random() * (i + 1));
        var tmp = copia[i]; copia[i] = copia[j]; copia[j] = tmp;
      }
      copia.sort(function (a, b) {                            // estable: prioriza no dominadas
        var pa = a.nivel ? PRIORIDAD[a.nivel] : 0;
        var pb = b.nivel ? PRIORIDAD[b.nivel] : 0;
        return pa - pb;
      });
      return copia;
    };

    var mostrarClave = function (porTiempo) {
      clearInterval(intervaloOral);
      $('oral-clave').textContent = (porTiempo ? '⏰ Tiempo agotado. ' : '') + 'Respuesta clave: ' + cola[pos].clave;
      $('oral-clave').classList.remove('d-none');
      $('oral-calificar').classList.remove('d-none');
      $('oral-ver').classList.add('d-none');
    };

    var tickOral = function () {
      var rest = Math.max(0, Math.ceil((finOral - Date.now()) / 1000));
      $('oral-reloj').textContent = mmss(rest);
      $('oral-reloj').className = 'badge fs-5 font-monospace ' + (rest <= 20 ? 'text-bg-danger parpadeo' : 'text-bg-dark');
      if (rest <= 0) { mostrarClave(true); }
    };

    var mostrarPregunta = function () {
      var t = cola[pos];
      $('oral-num').textContent = pos + 1;
      $('oral-pregunta').textContent = t.pregunta;
      $('oral-clave').classList.add('d-none');
      $('oral-calificar').classList.add('d-none');
      $('oral-ver').classList.remove('d-none');
      finOral = Date.now() + def.segundosOral * 1000;
      clearInterval(intervaloOral);
      tickOral();
      intervaloOral = setInterval(tickOral, 250);
    };

    if ($('oral-empezar')) {
      $('oral-empezar').addEventListener('click', function () {
        cola = ordenarCola();
        pos = 0;
        $('oral-total').textContent = cola.length;
        $('oral-inicio').classList.add('d-none');
        $('oral-fin').classList.add('d-none');
        $('oral-panel').classList.remove('d-none');
        mostrarPregunta();
      });
      $('oral-ver').addEventListener('click', function () { mostrarClave(false); });
      $('oral-calificar').querySelectorAll('button').forEach(function (b) {
        b.addEventListener('click', function () {
          calificar(cola[pos].indice, b.dataset.nivel);
          pos++;
          if (pos >= cola.length) {
            clearInterval(intervaloOral);
            $('oral-panel').classList.add('d-none');
            $('oral-fin').classList.remove('d-none');
            $('oral-inicio').classList.remove('d-none');
            $('oral-empezar').innerHTML = '<i class="bi bi-arrow-repeat"></i> Repetir simulacro oral';
          } else {
            mostrarPregunta();
          }
        });
      });
    }
  }
})();
