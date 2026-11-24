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
        // Aviso que dejó una acción justo antes de recargar (catalog.js). Si el servidor
        // ya trae su propio mensaje, ese manda y este se descarta.
        try {
            var flash = sessionStorage.getItem('pv-flash');
            if (flash) {
                sessionStorage.removeItem('pv-flash');
                if (!toasts.querySelector('[data-pv-toast]')) window.pvToast(flash, 'success');
            }
        } catch (e) {}
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
    // (El buscador tiene su propio indicador: no mueve la barra con cada tecla.)
    function isSearch(event) { return event.target && event.target.id === 'pv-search-input'; }
    document.body.addEventListener('htmx:beforeRequest', function (event) { if (!isSearch(event)) progressStart(); });
    document.body.addEventListener('htmx:afterRequest', function (event) { if (!isSearch(event)) progressDone(); });
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

    // ── Confirmación ───────────────────────────────────────────────────────
    /**
     * Diálogo de confirmación propio (reemplaza a confirm()). Devuelve una promesa
     * que resuelve a true/false. opts: { title, message, confirmLabel, danger }
     */
    window.pvConfirm = function (opts) {
        opts = opts || {};
        if (typeof HTMLDialogElement === 'undefined') {
            return Promise.resolve(window.confirm((opts.title ? opts.title + '\n\n' : '') + (opts.message || '')));
        }
        return new Promise(function (resolve) {
            var dialog = document.createElement('dialog');
            dialog.className = 'pv-dialog';
            var title = document.createElement('h3');
            title.textContent = opts.title || '¿Confirmas?';
            var text = document.createElement('p');
            text.textContent = opts.message || '';
            var actions = document.createElement('div');
            actions.className = 'pv-dialog__actions';
            var cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'pv-btn pv-btn--ghost';
            cancel.textContent = 'Cancelar';
            var accept = document.createElement('button');
            accept.type = 'button';
            accept.className = 'pv-btn ' + (opts.danger ? 'pv-btn--solid-danger' : 'pv-btn--primary');
            accept.textContent = opts.confirmLabel || 'Confirmar';
            actions.appendChild(cancel);
            actions.appendChild(accept);
            dialog.appendChild(title);
            dialog.appendChild(text);
            dialog.appendChild(actions);
            document.body.appendChild(dialog);
            var answer = false;
            cancel.addEventListener('click', function () { dialog.close(); });
            accept.addEventListener('click', function () { answer = true; dialog.close(); });
            dialog.addEventListener('click', function (event) { if (event.target === dialog) dialog.close(); });
            dialog.addEventListener('close', function () { dialog.remove(); resolve(answer); });
            dialog.showModal();
            accept.focus();
        });
    };

    function csrfToken() {
        var field = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return field ? field.value : '';
    }

    function postForm(url, fields) {
        var body = new FormData();
        Object.keys(fields).forEach(function (key) { body.append(key, fields[key]); });
        return fetch(url, {
            method: 'POST', credentials: 'same-origin', body: body,
            headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (data) {
                if (!response.ok || !data.success) {
                    throw new Error(data.message || (response.status === 403
                        ? 'No tienes permiso para esa acción.'
                        : 'No se pudo guardar (error ' + response.status + ').'));
                }
                return data;
            });
        }, function () {
            throw new Error('Sin conexión con el servidor. El cambio no se guardó.');
        });
    }

    // ── Recibos: estado del pago y «Revisado» sin salir de la lista ────────
    document.addEventListener('focusin', function (event) {
        var select = event.target.closest && event.target.closest('[data-pv-status]');
        if (select) select.dataset.previous = select.value;
    });
    document.addEventListener('change', function (event) {
        var select = event.target.closest('[data-pv-status]');
        if (select) {
            var previous = select.dataset.previous || select.getAttribute('data-state');
            var next = select.value;
            var label = select.options[select.selectedIndex].text;
            window.pvConfirm({
                title: 'Cambiar el estado a «' + label + '»',
                message: 'Se actualizará el ' + (select.getAttribute('data-label') || 'recibo') + '.',
                confirmLabel: 'Sí, cambiar',
                danger: next === 'Rechazado'
            }).then(function (ok) {
                if (!ok) { select.value = previous; return; }
                select.disabled = true;
                postForm(select.getAttribute('data-url'), { payment_status: next })
                    .then(function () {
                        select.setAttribute('data-state', next);
                        select.dataset.previous = next;
                        window.pvToast('Estado cambiado a ' + label + '.', 'success');
                    })
                    .catch(function (error) {
                        select.value = previous;
                        window.pvToast(error.message, 'error');
                    })
                    .then(function () { select.disabled = false; });
            });
            return;
        }
        var review = event.target.closest('[data-pv-review]');
        if (review) {
            var checked = review.checked;
            var row = review.closest('tr');
            if (row) row.classList.toggle('is-reviewed', checked);
            postForm(review.getAttribute('data-url'), { revisado: checked ? 'true' : 'false' })
                .catch(function (error) {
                    review.checked = !checked;
                    if (row) row.classList.toggle('is-reviewed', !checked);
                    window.pvToast(error.message, 'error');
                });
        }
    });

    // ── Buscador global ────────────────────────────────────────────────────
    var searchForm = document.getElementById('pv-search');
    if (searchForm) {
        var searchInput = document.getElementById('pv-search-input');
        var searchPanel = document.getElementById('pv-search-results');
        var searchItems = function () { return Array.prototype.slice.call(searchPanel.querySelectorAll('a.pv-search__item')); };
        var openSearch = function () {
            if (searchPanel.innerHTML.trim() === '') return;
            searchPanel.hidden = false;
            searchInput.setAttribute('aria-expanded', 'true');
        };
        var closeSearch = function () {
            searchPanel.hidden = true;
            searchInput.setAttribute('aria-expanded', 'false');
        };
        var moveSearch = function (step) {
            var items = searchItems();
            if (!items.length) return;
            var index = items.findIndex(function (item) { return item.classList.contains('is-active'); });
            if (index >= 0) items[index].classList.remove('is-active');
            index = (index + step + items.length) % items.length;
            if (index < 0) index = 0;
            items[index].classList.add('is-active');
            items[index].scrollIntoView({ block: 'nearest' });
        };

        searchPanel.addEventListener('htmx:afterSwap', function () {
            var first = searchItems()[0];
            if (first) first.classList.add('is-active');
            if (document.activeElement === searchInput) openSearch();
        });
        searchInput.addEventListener('focus', openSearch);
        searchInput.addEventListener('keydown', function (event) {
            if (event.key === 'ArrowDown') { event.preventDefault(); openSearch(); moveSearch(1); }
            else if (event.key === 'ArrowUp') { event.preventDefault(); moveSearch(-1); }
            else if (event.key === 'Escape') { closeSearch(); searchInput.blur(); }
        });
        searchForm.addEventListener('submit', function (event) {
            event.preventDefault();
            var active = searchPanel.querySelector('a.pv-search__item.is-active') || searchItems()[0];
            if (active && !searchPanel.hidden) { progressStart(); window.location = active.href; }
        });
        document.addEventListener('click', function (event) {
            if (!searchForm.contains(event.target)) closeSearch();
        });
        // Atajos: «/» o Ctrl+K llevan al buscador desde cualquier parte.
        document.addEventListener('keydown', function (event) {
            var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable;
            var slash = event.key === '/' && !typing && !event.ctrlKey && !event.metaKey && !event.altKey;
            var ctrlK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k';
            if (slash || ctrlK) {
                event.preventDefault();
                searchInput.focus();
                searchInput.select();
            }
        });
    }

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
