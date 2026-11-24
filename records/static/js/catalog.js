/*
 * Ventana común para crear, editar y eliminar en catálogos, clientes y usuarios.
 *
 * Un botón con `data-pv-modal data-url="…" data-title="…"` abre la ventana y carga en ella
 * el formulario que devuelve esa URL (las vistas responden el parcial a las peticiones
 * AJAX). Al enviar: `{success: true}` → recarga la página con un aviso; `{form_html}` →
 * vuelve a pintar el formulario con sus errores.
 *
 * También filtra en el navegador las tablas con `data-pv-table-filter`.
 */
(function () {
    'use strict';

    var dialog = null;
    var title = null;
    var body = null;

    function ensure() {
        if (dialog) return;
        dialog = document.createElement('dialog');
        dialog.className = 'pv-dialog pv-dialog--form';
        var head = document.createElement('div');
        head.className = 'pv-dialog__head';
        title = document.createElement('h3');
        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'pv-dialog__close';
        close.setAttribute('aria-label', 'Cerrar');
        close.innerHTML = '&times;';
        close.addEventListener('click', function () { dialog.close(); });
        head.appendChild(title);
        head.appendChild(close);
        body = document.createElement('div');
        body.className = 'pv-dialog__body';
        dialog.appendChild(head);
        dialog.appendChild(body);
        document.body.appendChild(dialog);
        dialog.addEventListener('click', function (event) { if (event.target === dialog) dialog.close(); });

        body.addEventListener('click', function (event) {
            if (event.target.closest('.btn-cancel')) { event.preventDefault(); dialog.close(); }
        });
        body.addEventListener('submit', onSubmit);
        // Documento del cliente: solo números y guiones (el servidor también lo valida).
        body.addEventListener('input', function (event) {
            if (event.target.id !== 'id_dni') return;
            var clean = event.target.value.replace(/[^0-9-]/g, '');
            if (clean !== event.target.value) event.target.value = clean;
        });
    }

    function paint(html) {
        body.innerHTML = html;
        var first = body.querySelector('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), select, textarea');
        if (first) { first.focus(); if (first.select) first.select(); }
    }

    function fail(message) {
        window.pvToast(message || 'No se pudo completar la acción. Intenta de nuevo.', 'error');
    }

    function open(url, heading) {
        ensure();
        title.textContent = heading || 'Gestionar';
        body.innerHTML = '<p class="pv-muted" style="margin: 0;">Cargando…</p>';
        if (!dialog.open) dialog.showModal();
        fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (response) {
                if (!response.ok) throw new Error(response.status === 403 ? 'No tienes permiso para esa acción.' : '');
                return response.text();
            })
            .then(paint)
            .catch(function (error) { dialog.close(); fail(error.message); });
    }

    function onSubmit(event) {
        var form = event.target;
        event.preventDefault();
        var button = form.querySelector('button[type="submit"]');
        if (button) { if (button.disabled) return; button.disabled = true; }
        var data = new FormData(form);
        fetch(form.action, {
            method: 'POST', credentials: 'same-origin', body: data,
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': data.get('csrfmiddlewaretoken') }
        })
            .then(function (response) {
                return response.json().catch(function () {
                    // Las vistas responden JSON; otra cosa es un error del servidor
                    // (por ejemplo, eliminar algo que ya está en uso).
                    throw new Error(form.hasAttribute('data-pv-delete')
                        ? 'No se pudo eliminar: probablemente ya está en uso en recibos o transacciones.'
                        : '');
                });
            })
            .then(function (result) {
                if (result.success) {
                    // El aviso se muestra tras recargar (app.js), salvo que el servidor ya traiga el suyo.
                    try { sessionStorage.setItem('pv-flash', result.message || 'Cambios guardados.'); } catch (e) {}
                    window.location.reload();
                } else if (result.form_html) {
                    paint(result.form_html);
                } else {
                    if (button) button.disabled = false;
                    fail(result.message);
                }
            })
            .catch(function (error) {
                if (button) button.disabled = false;
                fail(error.message);
            });
    }

    document.addEventListener('click', function (event) {
        var trigger = event.target.closest('[data-pv-modal]');
        if (!trigger) return;
        event.preventDefault();
        open(trigger.getAttribute('data-url'), trigger.getAttribute('data-title') || trigger.getAttribute('title'));
    });

    // Filtro rápido de las tablas de catálogo (pocas filas: se filtra en el navegador).
    document.addEventListener('input', function (event) {
        if (!event.target.matches('[data-pv-table-filter]')) return;
        var needle = event.target.value.trim().toLowerCase();
        var card = event.target.closest('.pv-card');
        if (!card) return;
        card.querySelectorAll('tbody tr.pv-row').forEach(function (row) {
            row.hidden = needle !== '' && row.textContent.toLowerCase().indexOf(needle) === -1;
        });
    });
})();
