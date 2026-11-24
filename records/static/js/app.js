/*
 * Comportamiento común de la interfaz: barra lateral, avisos (toasts), barra de
 * progreso, aviso de sesión por vencer y pequeños ayudantes para las listas.
 * Sin dependencias: funciona aunque HTMX o Alpine no carguen.
 */
(function () {
    'use strict';

    var shell = document.getElementById('pv-shell');

    // ── Barra lateral ──────────────────────────────────────────────────────
    if (shell) {
        if (document.documentElement.classList.contains('pv-pre-collapsed')) {
            shell.classList.add('is-collapsed');
        }
        document.addEventListener('click', function (event) {
            if (event.target.closest('[data-pv-sidebar-toggle]')) {
                var collapsed = shell.classList.toggle('is-collapsed');
                try { localStorage.setItem('pv-sidebar', collapsed ? 'collapsed' : 'open'); } catch (e) {}
            } else if (event.target.closest('[data-pv-drawer-open]')) {
                shell.classList.add('is-drawer-open');
            } else if (event.target.closest('[data-pv-drawer-close]')) {
                shell.classList.remove('is-drawer-open');
            }
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') shell.classList.remove('is-drawer-open');
        });
    }

    // ── Avisos ─────────────────────────────────────────────────────────────
    var toasts = document.getElementById('pv-toasts');

    function armToast(toast) {
        // Los errores se quedan hasta que el usuario los cierra.
        if (toast.classList.contains('pv-toast--error')) return;
        setTimeout(function () { dismiss(toast); }, 6000);
    }

    function dismiss(toast) {
        toast.style.transition = 'opacity .2s ease, transform .2s ease';
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(16px)';
        setTimeout(function () { toast.remove(); }, 220);
    }

    /** Muestra un aviso. type: success | error | warning | info */
    window.pvToast = function (message, type) {
        if (!toasts) return;
        var toast = document.createElement('div');
        toast.className = 'pv-toast pv-toast--' + (type || 'info');
        var text = document.createElement('div');
        text.className = 'pv-toast__text';
        text.textContent = message;
        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'pv-toast__close';
        close.setAttribute('aria-label', 'Cerrar aviso');
        close.setAttribute('data-pv-toast-close', '');
        close.innerHTML = '&times;';
        toast.appendChild(text);
        toast.appendChild(close);
        toasts.appendChild(toast);
        armToast(toast);
    };

    if (toasts) {
        toasts.querySelectorAll('[data-pv-toast]').forEach(armToast);
        toasts.addEventListener('click', function (event) {
            var close = event.target.closest('[data-pv-toast-close]');
            if (close) dismiss(close.closest('.pv-toast'));
        });
    }

    // ── Barra de progreso ──────────────────────────────────────────────────
    var progress = document.getElementById('pv-progress');
    var pending = 0;

    function progressStart() {
        if (!progress) return;
        pending += 1;
        progress.classList.remove('is-active');
        void progress.offsetWidth; // reinicia la animación
        progress.classList.add('is-active');
    }

    function progressDone() {
        if (!progress) return;
        pending = Math.max(0, pending - 1);
        if (pending === 0) progress.classList.remove('is-active');
    }

    // Navegación normal: enlaces internos y envío de formularios.
    document.addEventListener('click', function (event) {
        var link = event.target.closest('a[href]');
        if (!link || event.defaultPrevented || event.button !== 0) return;
        if (event.ctrlKey || event.metaKey || event.shiftKey || link.target === '_blank') return;
        if (link.hasAttribute('download') || link.hasAttribute('data-pv-download')) return;
        var href = link.getAttribute('href');
        if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return;
        if (link.origin !== window.location.origin) return;
        progressStart();
    });
    document.addEventListener('submit', function (event) {
        if (!event.defaultPrevented && !event.target.hasAttribute('hx-get')) progressStart();
    });
    window.addEventListener('pageshow', function () { pending = 0; if (progress) progress.classList.remove('is-active'); });

    // Peticiones HTMX.
    document.body.addEventListener('htmx:beforeRequest', progressStart);
    document.body.addEventListener('htmx:afterRequest', progressDone);
    document.body.addEventListener('htmx:responseError', function (event) {
        var status = event.detail.xhr ? event.detail.xhr.status : 0;
        window.pvToast(
            status === 403 ? 'No tienes permiso para esa acción.'
                : 'No se pudo completar la acción (error ' + status + '). Intenta de nuevo.', 'error');
    });
    document.body.addEventListener('htmx:sendError', function () {
        window.pvToast('Sin conexión con el servidor. Revisa tu red e intenta de nuevo.', 'error');
    });

    // ── Descargas (reportes): el botón muestra que se está generando ───────
    document.addEventListener('click', function (event) {
        var link = event.target.closest('[data-pv-download]');
        if (!link || link.classList.contains('is-busy')) return;
        var label = link.querySelector('[data-pv-label]');
        var original = label ? label.textContent : '';
        link.classList.add('is-busy');
        if (label) label.textContent = 'Generando…';
        window.pvToast('Generando el reporte. La descarga empieza en un momento.', 'info');
        setTimeout(function () {
            link.classList.remove('is-busy');
            if (label) label.textContent = original;
        }, 5000);
    });

    // ── Filas desplegables y filas clicables ───────────────────────────────
    document.addEventListener('click', function (event) {
        var toggle = event.target.closest('[data-pv-expand]');
        if (toggle) {
            var detail = document.getElementById(toggle.getAttribute('aria-controls'));
            if (!detail) return;
            var open = toggle.getAttribute('aria-expanded') !== 'true';
            toggle.setAttribute('aria-expanded', String(open));
            detail.hidden = !open;
            var row = toggle.closest('tr');
            if (row) row.classList.toggle('is-open', open);
            return;
        }
        var clickable = event.target.closest('tr[data-href]');
        if (clickable && !event.target.closest('a, button, input, select, label, [data-pv-stop]')) {
            progressStart();
            window.location = clickable.getAttribute('data-href');
        }
    });

    // ── Filtros: resalta los que tienen valor y cuenta los activos ─────────
    function markFilters(root) {
        (root || document).querySelectorAll('[data-pv-filters]').forEach(function (form) {
            var active = 0;
            form.querySelectorAll('.pv-field input, .pv-field select').forEach(function (field) {
                var filled = field.value !== '' && field.value !== null;
                field.classList.toggle('has-value', filled);
                if (filled) active += 1;
            });
            var counter = form.querySelector('[data-pv-filter-count]');
            if (counter) {
                counter.textContent = active ? active + (active === 1 ? ' filtro activo' : ' filtros activos') : '';
            }
        });
    }
    markFilters();
    document.addEventListener('input', function (event) {
        if (event.target.closest('[data-pv-filters]')) markFilters();
    });
    document.addEventListener('change', function (event) {
        if (event.target.closest('[data-pv-filters]')) markFilters();
    });
    document.addEventListener('click', function (event) {
        var more = event.target.closest('[data-pv-more-filters]');
        if (!more) return;
        var panel = document.getElementById(more.getAttribute('aria-controls'));
        if (!panel) return;
        var open = panel.hidden;
        panel.hidden = !open;
        more.setAttribute('aria-expanded', String(open));
        more.querySelector('[data-pv-label]').textContent = open ? 'Menos filtros' : 'Más filtros';
    });

    // ── Chips: fijan el valor de un filtro y refrescan ─────────────────────
    function syncChips(root) {
        (root || document).querySelectorAll('[data-pv-set]').forEach(function (chip) {
            var form = chip.closest('form');
            var field = form && form.elements[chip.getAttribute('data-pv-set')];
            if (field) chip.classList.toggle('is-active', field.value === chip.getAttribute('data-value'));
        });
    }
    syncChips();
    document.addEventListener('click', function (event) {
        var chip = event.target.closest('[data-pv-set]');
        if (!chip) return;
        var form = chip.closest('form');
        var field = form && form.elements[chip.getAttribute('data-pv-set')];
        if (!field) return;
        field.value = chip.getAttribute('data-value');
        field.dispatchEvent(new Event('change', { bubbles: true }));
    });
    document.addEventListener('change', function () { syncChips(); });

    // ── Sesión por vencer ──────────────────────────────────────────────────
    // La sesión dura 1 hora desde la última petición (SESSION_SAVE_EVERY_REQUEST).
    // Se avisa a los 55 min sin actividad de red: perderla a mitad de una captura
    // era la causa de los errores de inicio de sesión.
    var sessionBox = document.getElementById('pv-session');
    if (sessionBox) {
        var WARN_AFTER = 55 * 60 * 1000;
        var timer = null;
        var arm = function () {
            clearTimeout(timer);
            sessionBox.hidden = true;
            timer = setTimeout(function () { sessionBox.hidden = false; }, WARN_AFTER);
        };
        arm();
        document.body.addEventListener('htmx:afterRequest', arm);
        if (window.jQuery) window.jQuery(document).ajaxComplete(arm);
        document.getElementById('pv-session-keep').addEventListener('click', function () {
            // Cualquier petición autenticada renueva la sesión.
            fetch(this.getAttribute('data-ping-url'), { credentials: 'same-origin' })
                .then(function () { arm(); window.pvToast('Sesión renovada.', 'success'); })
                .catch(function () { window.pvToast('No se pudo renovar la sesión. Revisa tu conexión.', 'error'); });
        });
    }
})();
