/*
 * Ayudas comunes de los formularios de captura (nuevo registro y editar transacción):
 *
 *   - window.pvCaptureSummary(venta, recibos): pinta el resumen fijo (venta, recibos, diferencia).
 *   - Aviso previo de duplicado mientras se digita un recibo nuevo (solo informa; la
 *     validación que decide sigue en el servidor, FinancialRecordForm.clean()).
 *   - Atajos: Alt+N añade un recibo, Ctrl+Enter guarda.
 *   - Aviso del navegador si se intenta salir con cambios sin guardar.
 *
 * Se activa sobre <form data-pv-capture data-dup-url="…">.
 */
(function () {
    'use strict';

    var money = new Intl.NumberFormat('es-CO', {
        style: 'currency', currency: 'COP', minimumFractionDigits: 0, maximumFractionDigits: 2
    });

    window.pvCaptureSummary = function (expected, receipts) {
        var box = document.querySelector('[data-pv-summary]');
        if (!box) return;
        expected = Number(expected) || 0;
        receipts = Number(receipts) || 0;
        var difference = expected - receipts;
        var state = (expected === 0 && receipts === 0) ? 'empty'
            : Math.abs(difference) < 0.005 ? 'ok'
            : difference > 0 ? 'short' : 'over';
        var texts = {
            empty: ['Diferencia', 'Sin valores', 'pv-badge--muted'],
            ok: ['Diferencia', 'Cuadra', 'pv-badge--ok'],
            short: ['Falta por recibir', 'Falta dinero', 'pv-badge--bad'],
            over: ['Excedente', 'Se recibió de más', 'pv-badge--warn']
        }[state];
        var set = function (name, text) {
            var node = box.querySelector('[data-pv-sum="' + name + '"]');
            if (node) node.textContent = text;
        };
        box.setAttribute('data-state', state);
        set('expected', money.format(expected));
        set('receipts', money.format(receipts));
        set('difference', money.format(Math.abs(difference)));
        set('difference-label', texts[0]);
        var badge = box.querySelector('[data-pv-sum="state"]');
        if (badge) {
            badge.textContent = texts[1];
            badge.className = 'pv-badge pv-summary__state ' + texts[2];
        }
    };

    var form = document.querySelector('form[data-pv-capture]');
    if (!form) return;

    // ── Aviso previo de duplicado ──────────────────────────────────────────
    var dupUrl = form.getAttribute('data-dup-url');
    var WATCHED = /-(fecha|hora|comprobante|banco_llegada|valor)$/;

    function fieldOf(instance, name) {
        return instance.querySelector('[name$="-' + name + '"]');
    }

    function hintOf(instance) {
        var hint = instance.querySelector('[data-dup-hint]');
        if (!hint) {
            hint = document.createElement('div');
            hint.setAttribute('data-dup-hint', '');
            hint.setAttribute('role', 'status');
            hint.hidden = true;
            instance.appendChild(hint);
        }
        return hint;
    }

    function checkDuplicate(instance) {
        if (!dupUrl) return;
        var id = fieldOf(instance, 'id');
        if (id && id.value) return;                       // recibo ya guardado: no aplica
        var hint = hintOf(instance);
        var values = {};
        ['fecha', 'hora', 'comprobante', 'banco_llegada', 'valor'].forEach(function (name) {
            var field = fieldOf(instance, name);
            values[name] = field ? field.value.trim() : '';
        });
        values.valor = values.valor.replace(/,/g, '');
        if (!values.fecha || !values.banco_llegada || !values.valor || !/^\d{2}:\d{2}(:\d{2})?$/.test(values.hora)) {
            hint.hidden = true;
            return;
        }
        var key = JSON.stringify(values);
        instance.dataset.dupKey = key;
        fetch(dupUrl + '?' + new URLSearchParams(values).toString(), {
            credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
            .then(function (response) { return response.ok ? response.json() : { status: 'none' }; })
            .then(function (data) {
                if (instance.dataset.dupKey !== key) return;   // el usuario siguió escribiendo
                if (data.status === 'exact' || data.status === 'similar') {
                    hint.className = 'pv-callout' + (data.status === 'exact' ? ' pv-callout--bad' : '');
                    hint.textContent = (data.status === 'exact' ? 'Duplicado: ' : 'Posible duplicado: ') + data.message;
                    hint.hidden = false;
                } else {
                    hint.hidden = true;
                }
            })
            .catch(function () { hint.hidden = true; });   // sin red: el servidor valida al guardar
    }

    form.addEventListener('change', function (event) {
        if (!event.target.name || !WATCHED.test(event.target.name)) return;
        var instance = event.target.closest('.receipt-form-instance');
        if (instance) checkDuplicate(instance);
    });

    // ── Foco en el recibo recién añadido ───────────────────────────────────
    var container = form.querySelector('#receipt-forms-container, #formset-container');
    if (container && window.MutationObserver) {
        new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                Array.prototype.forEach.call(mutation.addedNodes, function (node) {
                    if (node.nodeType !== 1 || !node.classList.contains('receipt-form-instance')) return;
                    var first = node.querySelector('select, input:not([type="hidden"]):not([type="checkbox"])');
                    if (first) first.focus();
                    node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                });
            });
        }).observe(container, { childList: true });
    }

    // ── Atajos de teclado ──────────────────────────────────────────────────
    document.addEventListener('keydown', function (event) {
        if (event.altKey && !event.ctrlKey && event.key.toLowerCase() === 'n') {
            var add = document.querySelector('#add-form, #add-receipt-btn');
            if (add) { event.preventDefault(); add.click(); }
        } else if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            event.preventDefault();
            if (form.requestSubmit) form.requestSubmit(); else form.submit();
        }
    });

    // ── Cambios sin guardar ────────────────────────────────────────────────
    var dirty = false;
    form.addEventListener('input', function () { dirty = true; });
    form.addEventListener('submit', function () { dirty = false; });
    window.addEventListener('beforeunload', function (event) {
        if (!dirty) return;
        event.preventDefault();
        event.returnValue = '';
    });
})();
