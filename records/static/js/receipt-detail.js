/*
 * Detalle de un recibo (solo administradores): edición en línea de los campos y
 * reasignación del cliente. Cada campo se guarda al salir de él, contra
 * update_credit_field / update_credit_client.
 */
(function () {
    'use strict';

    var csrf = (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
    var LABELS = {
        fecha: 'Fecha', hora: 'Hora', comprobante: 'Comprobante', valor: 'Valor',
        banco_llegada: 'Banco', origen_transaccion: 'Origen'
    };

    function postJson(url, payload) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (data) {
                if (!response.ok || !data.success) {
                    throw new Error(data.message || 'No se pudo guardar (error ' + response.status + ').');
                }
                return data;
            });
        });
    }

    // La vista espera fecha dd/mm/aaaa, hora HH:MM:SS y valor con coma decimal.
    function toServer(field) {
        var value = field.value.trim();
        var format = field.getAttribute('data-format');
        if (format === 'date') {
            var parts = value.split('-');
            return parts.length === 3 ? parts[2] + '/' + parts[1] + '/' + parts[0] : null;
        }
        if (format === 'time') {
            if (/^\d{2}:\d{2}$/.test(value)) value += ':00';
            return /^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$/.test(value) ? value : null;
        }
        if (format === 'money') {
            value = value.replace(/[$\s]/g, '');
            if (/^\d+(\.\d{1,2})?$/.test(value)) return value.replace('.', ',');      // 150000.50
            if (/^\d{1,3}(\.\d{3})*(,\d{1,2})?$/.test(value) || /^\d+(,\d{1,2})?$/.test(value)) return value;  // 150.000,50
            return null;
        }
        return value === '' ? null : value;
    }

    var grid = document.querySelector('[data-pv-inline-edit]');
    if (grid) {
        var url = grid.getAttribute('data-url');
        grid.querySelectorAll('[data-field]').forEach(function (field) {
            field.dataset.saved = field.value;
            if (field.getAttribute('data-format') === 'time') {
                field.addEventListener('input', function () {
                    var d = field.value.replace(/\D/g, '').slice(0, 6);
                    field.value = d.length > 4 ? d.slice(0, 2) + ':' + d.slice(2, 4) + ':' + d.slice(4)
                        : d.length > 2 ? d.slice(0, 2) + ':' + d.slice(2) : d;
                });
            }
            field.addEventListener('change', function () {
                if (field.value === field.dataset.saved) return;
                var name = field.getAttribute('data-field');
                var value = toServer(field);
                if (value === null) {
                    field.classList.add('is-invalid');
                    window.pvToast(LABELS[name] + ': el valor no es válido. No se guardó.', 'error');
                    return;
                }
                field.classList.remove('is-invalid');
                field.disabled = true;
                postJson(url, { field: name, value: value })
                    .then(function () {
                        field.dataset.saved = field.value;
                        field.classList.add('is-saved');
                        setTimeout(function () { field.classList.remove('is-saved'); }, 1600);
                        window.pvToast(LABELS[name] + ' actualizado.', 'success');
                    })
                    .catch(function (error) {
                        field.value = field.dataset.saved;
                        window.pvToast(error.message, 'error');
                    })
                    .then(function () { field.disabled = false; });
            });
        });
    }

    // Reasignar cliente (autocompletado de jQuery UI, que sigue cargado en base.html).
    var search = document.getElementById('client-autocomplete');
    if (search && window.jQuery && window.jQuery.fn.autocomplete) {
        window.jQuery(search).autocomplete({
            source: search.getAttribute('data-search-url'),
            minLength: 2,
            select: function (event, ui) {
                event.preventDefault();
                search.value = '';
                window.pvConfirm({
                    title: 'Reasignar el recibo',
                    message: 'El recibo pasará a ' + ui.item.label + '. Su saldo a favor cambia de cliente.',
                    confirmLabel: 'Reasignar'
                }).then(function (ok) {
                    if (!ok) return;
                    postJson(search.getAttribute('data-update-url'), { client_id: ui.item.id })
                        .then(function (data) {
                            window.pvToast(data.message, 'success');
                            setTimeout(function () { window.location.reload(); }, 700);
                        })
                        .catch(function (error) { window.pvToast(error.message, 'error'); });
                });
            }
        });
    }
})();
