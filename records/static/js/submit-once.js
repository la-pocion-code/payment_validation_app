/*
 * submit-once.js — Evita el doble envío de formularios.
 *
 * Problema que resuelve: con red inestable el digitador pulsa "Guardar" dos veces
 * (o el navegador reenvía el POST), y el segundo envío choca con la validación de
 * duplicados. Este guard bloquea el segundo submit en el cliente; la llave de
 * idempotencia del servidor (records/idempotency.py) cubre lo que el cliente no puede.
 *
 * Uso: opt-in por atributo -> <form method="post" data-submit-once>
 * El opt-in es deliberado: los formularios AJAX de los modales hacen preventDefault
 * y se quedan en la página, así que no deben quedar bloqueados.
 */
(function () {
    'use strict';

    var LATCH_MS = 25000;  // si el servidor no responde, devolvemos el control

    function submitButtons(form) {
        return form.querySelectorAll('button[type="submit"], input[type="submit"]');
    }

    function release(form) {
        if (form.dataset.submitting !== '1') { return; }
        form.dataset.submitting = '';
        Array.prototype.forEach.call(submitButtons(form), function (btn) {
            btn.disabled = false;
            btn.removeAttribute('aria-busy');
            if (btn.dataset.originalHtml) { btn.innerHTML = btn.dataset.originalHtml; }
        });
    }

    function guard(form) {
        if (form.dataset.submitOnceBound === '1') { return; }
        form.dataset.submitOnceBound = '1';

        // Fase de burbujeo y enlazado en DOMContentLoaded: corre DESPUÉS de los
        // handlers inline de las plantillas, que desformatean las comas de los
        // campos de moneda. No interferimos con ellos.
        form.addEventListener('submit', function (event) {
            if (event.defaultPrevented) { return; }   // p.ej. un confirm() cancelado

            if (form.dataset.submitting === '1') {
                event.preventDefault();               // segundo clic: se descarta
                event.stopImmediatePropagation();
                return;
            }
            form.dataset.submitting = '1';

            var buttons = submitButtons(form);

            // CLAVE: el navegador serializa el form-data DESPUÉS de despachar
            // 'submit'. Deshabilitar el botón de forma síncrona puede dejar su par
            // name=value fuera del payload. Con setTimeout(...,0) lo deshabilitamos
            // en el siguiente tick, cuando el envío ya está en curso.
            window.setTimeout(function () {
                Array.prototype.forEach.call(buttons, function (btn) {
                    btn.dataset.originalHtml = btn.innerHTML;
                    btn.disabled = true;
                    btn.setAttribute('aria-busy', 'true');
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"' +
                                    ' role="status" aria-hidden="true"></span>Guardando…';
                });
            }, 0);

            window.setTimeout(function () { release(form); }, LATCH_MS);
        });
    }

    function bindAll() {
        Array.prototype.forEach.call(
            document.querySelectorAll('form[data-submit-once]'), guard);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindAll);
    } else {
        bindAll();
    }

    // bfcache: al volver con "Atrás" el DOM se restaura con el botón deshabilitado.
    window.addEventListener('pageshow', function (e) {
        if (e.persisted) {
            Array.prototype.forEach.call(
                document.querySelectorAll('form[data-submit-once]'), release);
        }
    });
})();
