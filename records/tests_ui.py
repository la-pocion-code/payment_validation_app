# -*- coding: utf-8 -*-
"""
Pruebas de las pantallas rediseñadas: buscador global, lista y detalle de recibos,
aviso previo de duplicado y el segundo chequeo de reenvío con varios workers.
"""

import uuid
from html.parser import HTMLParser
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from . import alerts
from . import tests as base
from . import views
from .idempotency import SUBMIT_TOKEN_FIELD, already_submitted
from .models import DuplicateAlertTemplate, DuplicateRecordAttempt, FinancialRecord, Transaction


class ConRecibos(base.DatosBase):
    """Una transacción con un recibo y un abono suelto."""

    def setUp(self):
        super().setUp()
        self.hoy = timezone.now().date()
        self.transaccion = Transaction.objects.create(
            date=self.hoy, cliente=self.cliente, vendedor=self.vendedor,
            transaction_type=self.tipo, expected_amount=Decimal('150000.00'),
            numero_factura='FV-900', created_by=self.user,
        )
        self.recibo = FinancialRecord.objects.create(
            fecha=self.hoy, hora='09:00:00', comprobante='M0320-AAA',
            banco_llegada=self.banco, origen_transaccion=self.origen,
            valor=Decimal('150000.00'), transaction=self.transaccion, uploaded_by=self.user,
        )
        self.abono = FinancialRecord.objects.create(
            fecha=self.hoy, hora='11:00:00', comprobante='ABONO-77',
            banco_llegada=self.banco, origen_transaccion=self.origen,
            valor=Decimal('20000.00'), cliente=self.cliente, uploaded_by=self.user,
        )

    def entrar_como(self, grupo):
        usuario = User.objects.create_user(f'u-{grupo.lower()}', password='clave-larga-123')
        if grupo:
            usuario.groups.add(Group.objects.get_or_create(name=grupo)[0])
        self.client.force_login(usuario)
        return usuario


class BuscadorGlobalTests(ConRecibos):

    def buscar(self, texto):
        respuesta = self.client.get(reverse('global_search'), {'q': texto})
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_encuentra_recibo_por_comprobante(self):
        respuesta = self.buscar('0320-aa')
        self.assertEqual([r.pk for r in respuesta.context['receipts']], [self.recibo.pk])
        self.assertContains(respuesta, reverse('credit_detail', args=[self.recibo.pk]))

    def test_encuentra_transaccion_por_factura_y_por_cliente(self):
        self.assertEqual(self.buscar('FV-900').context['transactions'], [self.transaccion])
        respuesta = self.buscar('cliente prueba')
        self.assertEqual(respuesta.context['transactions'], [self.transaccion])
        self.assertEqual(respuesta.context['clients'], [self.cliente])

    def test_encuentra_recibo_por_valor_con_o_sin_puntos(self):
        for texto in ('150000', '150.000', '$150.000,00'):
            with self.subTest(texto=texto):
                self.assertIn(self.recibo, self.buscar(texto).context['receipts'])

    def test_un_numero_corto_no_se_toma_como_valor(self):
        self.assertIsNone(views._search_amount('77'))
        self.assertEqual(views._search_amount('1.055.635,50'), Decimal('1055635.50'))

    def test_menos_de_dos_caracteres_no_consulta(self):
        respuesta = self.buscar('a')
        self.assertFalse(respuesta.context['searched'])

    def test_sin_resultados_lo_dice(self):
        self.assertContains(self.buscar('zzzz-no-existe'), 'Sin resultados')

    def test_usuario_sin_rol_no_llega_al_buscador(self):
        self.entrar_como('')
        respuesta = self.client.get(reverse('global_search'), {'q': 'M0320'})
        self.assertRedirects(respuesta, reverse('request_access'))

    def test_facturador_va_a_la_lista_porque_no_abre_el_detalle(self):
        self.entrar_como('Facturador')
        respuesta = self.buscar('M0320')
        self.assertNotContains(respuesta, reverse('credit_detail', args=[self.recibo.pk]))
        self.assertContains(respuesta, reverse('credit_list') + '?comprobante=M0320-AAA')

    def test_la_barra_esta_en_el_marco_con_logo_y_favicon(self):
        html = self.client.get(reverse('record_list')).content.decode()
        self.assertIn('id="pv-search-input"', html)
        self.assertIn('images/pocion-logo', html)
        self.assertIn('images/favicon', html)


class AvisoPrevioDeDuplicadoTests(ConRecibos):

    def consultar(self, **cambios):
        datos = {
            'fecha': self.hoy.isoformat(), 'hora': '09:00:00', 'comprobante': 'M0320-AAA',
            'banco_llegada': self.banco.pk, 'valor': '150000.00',
        }
        datos.update(cambios)
        return self.client.get(reverse('check_receipt_duplicate'), datos)

    def test_duplicado_exacto(self):
        datos = self.consultar().json()
        self.assertEqual(datos['status'], 'exact')
        self.assertIn(self.transaccion.unique_transaction_id, datos['message'])

    def test_posible_duplicado_con_otro_comprobante(self):
        datos = self.consultar(comprobante='OTRO').json()
        self.assertEqual(datos['status'], 'similar')
        self.assertIn('M0320-AAA', datos['message'])

    def test_recibo_nuevo(self):
        self.assertEqual(self.consultar(hora='09:00:01').json()['status'], 'none')

    def test_datos_incompletos(self):
        self.assertEqual(self.consultar(hora='').json()['status'], 'incomplete')

    def test_es_de_solo_lectura_no_ensucia_la_bandeja(self):
        self.consultar()
        self.consultar(comprobante='OTRO')
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 0)

    def test_solo_para_quien_digita(self):
        self.entrar_como('Validador')
        self.assertEqual(self.consultar().status_code, 302)


class ListaDeRecibosTests(ConRecibos):

    def test_pagina_completa_y_parcial_htmx(self):
        completa = self.client.get(reverse('credit_list')).content.decode()
        self.assertIn('<html', completa)
        self.assertIn('id="pv-results"', completa)
        parcial = self.client.get(reverse('credit_list'), HTTP_HX_REQUEST='true').content.decode()
        self.assertNotIn('<html', parcial)
        self.assertTrue(parcial.lstrip().startswith('<div id="pv-results"'))

    def test_suma_lo_filtrado(self):
        respuesta = self.client.get(reverse('credit_list'))
        self.assertEqual(respuesta.context['total_valor'], Decimal('170000.00'))
        respuesta = self.client.get(reverse('credit_list'), {'transaccion_presencia': 'sin'})
        self.assertEqual(respuesta.context['total_valor'], Decimal('20000.00'))
        self.assertTrue(respuesta.context['has_advanced_filters'])

    def test_solo_el_validador_ve_el_selector_de_estado(self):
        self.assertNotContains(self.client.get(reverse('credit_list')), 'data-pv-status')
        self.entrar_como('Validador')
        respuesta = self.client.get(reverse('credit_list'))
        self.assertContains(respuesta, 'data-pv-status')
        self.assertContains(respuesta, reverse('update_credit_status', args=[self.recibo.pk]))

    def test_el_validador_cambia_estado_y_marca_revisado(self):
        self.entrar_como('Validador')
        respuesta = self.client.post(reverse('update_credit_status', args=[self.recibo.pk]),
                                     {'payment_status': 'Aprobado'})
        self.assertTrue(respuesta.json()['success'])
        respuesta = self.client.post(reverse('toggle_credit_revisado', args=[self.recibo.pk]),
                                     {'revisado': 'true'})
        self.assertTrue(respuesta.json()['revisado'])
        self.recibo.refresh_from_db()
        self.assertEqual((self.recibo.payment_status, self.recibo.revisado), ('Aprobado', True))

    def test_las_consultas_no_crecen_con_las_filas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def contar():
            with CaptureQueriesContext(connection) as consultas:
                self.client.get(reverse('credit_list'))
            return len(consultas)

        antes = contar()
        for i in range(12):
            FinancialRecord.objects.create(
                fecha=self.hoy, hora='12:00:00', comprobante=f'EXTRA-{i}',
                banco_llegada=self.banco, origen_transaccion=self.origen,
                valor=Decimal('1000.00'), transaction=self.transaccion, uploaded_by=self.user,
            )
        self.assertEqual(contar(), antes)


class DetalleYEdicionTests(ConRecibos):

    def test_detalle_marca_el_banco_y_el_origen_reales(self):
        from .models import Bank
        Bank.objects.create(name='ZZ ULTIMO BANCO')
        admin = User.objects.create_superuser('jefe', password='clave-larga-123')
        self.client.force_login(admin)
        html = self.client.get(reverse('credit_detail', args=[self.recibo.pk])).content.decode()
        self.assertIn(f'<option value="{self.banco.pk}" selected>BANCOLOMBIA</option>', html)
        self.assertNotIn('selected>ZZ ULTIMO BANCO', html)
        self.assertEqual(html.count(' selected>'), 3)   # estado, banco y origen

    def test_formularios_de_captura_cargan_sus_ayudas(self):
        for url in (reverse('record_create'), reverse('transaction_update', args=[self.transaccion.pk])):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'data-pv-capture')
                self.assertContains(respuesta, 'data-pv-summary')
                self.assertContains(respuesta, 'js/capture')
                self.assertContains(respuesta, f'name="{SUBMIT_TOKEN_FIELD}"')

    def test_un_rol_de_solo_lectura_conserva_el_documento_de_pago_al_guardar(self):
        """El campo oculto enviaba vacío y el guardado de otro rol podía borrarlo."""
        self.recibo.payment_document = 'BAN-25154'
        self.recibo.save()
        self.entrar_como('Validador')
        html = self.client.get(reverse('transaction_update', args=[self.transaccion.pk])).content.decode()
        self.assertIn('name="receipts-0-payment_document"', html)
        self.assertIn('value="BAN-25154"', html)


class ReenvioCruzadoTests(base.DatosBase):
    """
    Con varios workers dos POST del mismo formulario pueden cruzarse: el segundo pasa
    la fase 1 antes de que el primero confirme y su clean() ya ve el recibo guardado.
    Debe responder «ya fue guardado», no «duplicado», y no dejar rastro en la bandeja.
    """

    def _payload(self, token):
        hoy = timezone.now().date().isoformat()
        return {
            SUBMIT_TOKEN_FIELD: str(token),
            'date': hoy, 'client_search': str(self.cliente), 'cliente_id': self.cliente.pk,
            'seller_search': self.vendedor.name, 'vendedor_id': self.vendedor.pk,
            'transaction_type': self.tipo.pk, 'expected_amount': '150000.00',
            'description': 'Prueba', 'status': 'Pendiente', 'numero_factura': '', 'facturador': '',
            'receipts-TOTAL_FORMS': '1', 'receipts-INITIAL_FORMS': '0',
            'receipts-MIN_NUM_FORMS': '0', 'receipts-MAX_NUM_FORMS': '1000',
            'receipts-0-id': '', 'receipts-0-origen_transaccion': self.origen.pk,
            'receipts-0-fecha': hoy, 'receipts-0-hora': '10:30:00',
            'receipts-0-comprobante': 'CRUCE-1', 'receipts-0-banco_llegada': self.banco.pk,
            'receipts-0-valor': '150000.00', 'receipts-0-payment_status': 'Pendiente',
            'receipts-0-payment_document': '',
        }

    def test_el_segundo_post_que_se_cruzo_no_genera_alerta_de_duplicado(self):
        token = uuid.uuid4()
        primero = self.client.post(reverse('record_create'), self._payload(token))
        self.assertEqual(primero.status_code, 302)

        # Simula el cruce: la fase 1 del segundo POST todavía no ve el token.
        llamadas = {'n': 0}

        def fase_1_ciega(request):
            llamadas['n'] += 1
            return None if llamadas['n'] == 1 else already_submitted(request)

        with mock.patch.object(views, 'already_submitted', side_effect=fase_1_ciega):
            segundo = self.client.post(reverse('record_create'), self._payload(token))

        self.assertEqual(llamadas['n'], 2)
        self.assertEqual(segundo.status_code, 302)
        self.assertEqual(segundo.url, reverse('transaction_update', args=[Transaction.objects.get().pk]))
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(FinancialRecord.objects.count(), 1)
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 0)
        avisos = [str(m) for m in get_messages(segundo.wsgi_request)]
        self.assertTrue(any('ya fue guardado' in aviso for aviso in avisos), avisos)

    def test_un_duplicado_real_con_otro_token_si_se_registra(self):
        self.client.post(reverse('record_create'), self._payload(uuid.uuid4()))
        respuesta = self.client.post(reverse('record_create'), self._payload(uuid.uuid4()))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 1)


@override_settings(DUPLICATE_ALERTS_ASYNC=False, SITE_URL='https://pagos.example.com')
class AlertasPorCorreoTests(ReenvioCruzadoTests):
    """Avisos por correo de duplicados: los decide la plantilla (activa + destinatarios)."""

    # Hereda _payload; las pruebas de la clase base se repiten aquí con las alertas activas.

    def activar(self, key='DUPLICATE', recipients='auditor@lapocion.com', cc=''):
        plantilla = DuplicateAlertTemplate.objects.get(key=key)
        plantilla.is_active = True
        plantilla.recipients = recipients
        plantilla.cc = cc
        plantilla.save()
        return plantilla

    def duplicar(self):
        """Guarda un recibo y vuelve a enviarlo desde otro formulario (duplicado real)."""
        self.client.post(reverse('record_create'), self._payload(uuid.uuid4()))
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('record_create'), self._payload(uuid.uuid4()))

    def test_la_migracion_deja_las_dos_plantillas_apagadas(self):
        self.assertEqual(
            list(DuplicateAlertTemplate.objects.values_list('key', 'is_active')),
            [('DUPLICATE', False), ('SIMILAR', False)])

    def test_apagada_no_envia(self):
        self.duplicar()
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 1)
        self.assertEqual(mail.outbox, [])

    def test_duplicado_exacto_avisa_a_los_destinatarios(self):
        self.activar(recipients='auditor@lapocion.com; conta@lapocion.com', cc='jefe@lapocion.com')
        self.duplicar()

        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ['auditor@lapocion.com', 'conta@lapocion.com'])
        self.assertEqual(correo.cc, ['jefe@lapocion.com'])
        self.assertEqual(correo.subject, 'Intento de recibo duplicado: CRUCE-1')
        self.assertIn('Banco: BANCOLOMBIA', correo.body)
        self.assertIn('Valor: $150.000', correo.body)
        existente = FinancialRecord.objects.get()
        self.assertIn(f'https://pagos.example.com/credits/{existente.pk}/', correo.body)
        self.assertIn('https://pagos.example.com/duplicates/', correo.body)

        html, tipo = correo.alternatives[0]
        self.assertEqual(tipo, 'text/html')
        self.assertIn('cid:logo-pocion', html)
        self.assertIn('Revisar la bandeja de duplicados</a>', html)   # «Etiqueta: URL» → botón
        self.assertEqual(correo.mixed_subtype, 'related')

    def test_el_reenvio_del_mismo_formulario_no_avisa(self):
        self.activar()
        token = uuid.uuid4()
        self.client.post(reverse('record_create'), self._payload(token))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('record_create'), self._payload(token))
        self.assertEqual(mail.outbox, [])

    def test_un_fallo_del_servidor_de_correo_no_rompe_el_guardado(self):
        self.activar()
        with mock.patch('django.core.mail.message.EmailMessage.send', side_effect=OSError('smtp caído')):
            with self.assertLogs('records.alerts', level='ERROR'):
                respuesta = self.duplicar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 1)

    def test_texto_se_escapa_y_el_enlace_vacio_no_deja_linea_colgando(self):
        plantilla = DuplicateAlertTemplate.objects.get(key='DUPLICATE')
        contexto = dict(alerts.sample_context(), comprobante='<b>X</b>', enlace_recibo='')
        mensaje = alerts.build_message(plantilla, contexto, to=['a@lapocion.com'])
        self.assertNotIn('Ver el recibo que ya existía', mensaje.body)
        self.assertIn('&lt;b&gt;X&lt;/b&gt;', mensaje.alternatives[0][0])
        self.assertEqual(alerts.render('{desconocida} {valor}', {'valor': '$1'}), '{desconocida} $1')

    def test_la_pantalla_es_solo_para_administradores(self):
        self.assertEqual(self.client.get(reverse('duplicate_alert_settings')).status_code, 302)

    def test_guardar_valida_correos_y_exige_destinatario_para_activar(self):
        admin = User.objects.create_superuser('jefe', email='jefe@lapocion.com', password='clave-larga-123')
        self.client.force_login(admin)
        url = reverse('duplicate_alert_settings')
        base_datos = {'key': 'SIMILAR', 'action': 'save', 'SIMILAR-subject': 'Asunto', 'SIMILAR-body': 'Hola {usuario}'}

        respuesta = self.client.post(url, dict(base_datos, **{'SIMILAR-is_active': 'on', 'SIMILAR-recipients': ''}))
        self.assertContains(respuesta, 'indica al menos un destinatario')
        respuesta = self.client.post(url, dict(base_datos, **{'SIMILAR-recipients': 'no-es-correo'}))
        self.assertContains(respuesta, 'no es un correo válido')
        self.assertFalse(DuplicateAlertTemplate.objects.get(key='SIMILAR').is_active)

        respuesta = self.client.post(url, dict(base_datos, **{
            'SIMILAR-is_active': 'on', 'SIMILAR-recipients': 'a@lapocion.com\nb@lapocion.com'}))
        self.assertRedirects(respuesta, url)
        plantilla = DuplicateAlertTemplate.objects.get(key='SIMILAR')
        self.assertTrue(plantilla.is_active)
        self.assertEqual(plantilla.recipient_list(), ['a@lapocion.com', 'b@lapocion.com'])
        self.assertEqual(plantilla.updated_by, admin)

    def test_la_prueba_llega_solo_a_quien_la_pide_y_no_guarda(self):
        admin = User.objects.create_superuser('jefe', email='jefe@lapocion.com', password='clave-larga-123')
        self.client.force_login(admin)
        respuesta = self.client.post(reverse('duplicate_alert_settings'), {
            'key': 'DUPLICATE', 'action': 'test', 'DUPLICATE-recipients': 'auditor@lapocion.com',
            'DUPLICATE-subject': 'PRUEBA {comprobante}', 'DUPLICATE-body': 'Hola {usuario}',
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jefe@lapocion.com'])
        self.assertEqual(mail.outbox[0].cc, [])
        self.assertEqual(mail.outbox[0].subject, 'PRUEBA M03202292')
        self.assertNotEqual(DuplicateAlertTemplate.objects.get(key='DUPLICATE').subject, 'PRUEBA {comprobante}')

    def test_vista_previa(self):
        admin = User.objects.create_superuser('jefe', password='clave-larga-123')
        self.client.force_login(admin)
        respuesta = self.client.get(reverse('duplicate_alert_preview', args=['SIMILAR']))
        self.assertContains(respuesta, 'Posible duplicado confirmado: M03202292')


class NuevoAbonoYBandejaTests(ConRecibos):

    def datos_abono(self, **cambios):
        datos = {
            SUBMIT_TOKEN_FIELD: str(uuid.uuid4()),
            'client_search': str(self.cliente), 'cliente_id': self.cliente.pk,
            'origen_transaccion': self.origen.pk, 'fecha': self.hoy.isoformat(), 'hora': '13:00:00',
            'comprobante': 'AB-NUEVO', 'banco_llegada': self.banco.pk, 'valor': '5000.00',
            'payment_status': 'Pendiente', 'note': '', 'confirm_duplicate': '',
        }
        datos.update(cambios)
        return datos

    def test_el_formulario_usa_las_ayudas_de_captura(self):
        respuesta = self.client.get(reverse('credit_create'))
        self.assertContains(respuesta, 'data-pv-capture')
        self.assertContains(respuesta, reverse('check_receipt_duplicate'))
        self.assertContains(respuesta, f'name="{SUBMIT_TOKEN_FIELD}"')
        self.assertNotContains(respuesta, 'similar-duplicate-warning-box')

    def test_guarda_un_abono(self):
        respuesta = self.client.post(reverse('credit_create'), self.datos_abono())
        self.assertRedirects(respuesta, reverse('credit_list'))
        abono = FinancialRecord.objects.get(comprobante='AB-NUEVO')
        self.assertEqual((abono.cliente, abono.transaction), (self.cliente, None))

    def test_la_casilla_de_posible_duplicado_solo_sale_cuando_aplica(self):
        # Un error cualquiera (sin cliente) NO debe mostrar el aviso de posible duplicado.
        respuesta = self.client.post(reverse('credit_create'), self.datos_abono(cliente_id='', client_search=''))
        self.assertNotContains(respuesta, 'similar-duplicate-warning-box')
        # Misma fecha, hora, banco y valor que el abono existente, con otro comprobante: sí.
        similar = self.datos_abono(hora='11:00:00', valor='20000.00', comprobante='AB-OTRO')
        respuesta = self.client.post(reverse('credit_create'), similar)
        self.assertContains(respuesta, 'similar-duplicate-warning-box')
        self.assertFalse(FinancialRecord.objects.filter(comprobante='AB-OTRO').exists())
        respuesta = self.client.post(reverse('credit_create'),
                                     dict(similar, confirm_duplicate='true', **{SUBMIT_TOKEN_FIELD: str(uuid.uuid4())}))
        self.assertRedirects(respuesta, reverse('credit_list'))
        self.assertTrue(FinancialRecord.objects.filter(comprobante='AB-OTRO').exists())

    def test_la_bandeja_muestra_el_intento_con_enlace_al_recibo_existente(self):
        admin = User.objects.create_superuser('jefe', password='clave-larga-123')
        DuplicateRecordAttempt.objects.create(user=self.user, attempt_type='DUPLICATE', data={
            'comprobante': 'M0320-AAA', 'fecha': str(self.hoy), 'hora': '09:00:00',
            'banco_llegada': 'BANCOLOMBIA', 'valor': '150000.00',
            '_registro_existente_pk': str(self.recibo.pk)})
        DuplicateRecordAttempt.objects.create(user=self.user, attempt_type='SIMILAR', data={'comprobante': 'X'})
        self.client.force_login(admin)
        respuesta = self.client.get(reverse('duplicate_attempts_list'))
        self.assertContains(respuesta, 'Duplicado exacto')
        self.assertContains(respuesta, 'Posible duplicado')
        self.assertContains(respuesta, reverse('credit_detail', args=[self.recibo.pk]))
        self.assertContains(respuesta, reverse('credit_list') + '?comprobante=X')


class CatalogosClientesYUsuariosTests(ConRecibos):
    """Las pantallas de administración: lista, ventana (parciales AJAX) y eliminaciones protegidas."""

    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('jefe', email='jefe@lapocion.com', password='clave-larga-123')
        self.client.force_login(self.admin)

    def test_todas_las_pantallas_cargan(self):
        from .models import Bank
        paginas = ['bank_list', 'seller_list', 'origen_transaccion_list', 'TransactionType_list',
                   'payment_document_list', 'Client_list', 'access_request_list',
                   'duplicate_attempts_list', 'duplicate_attempts_history_list', 'csv_upload',
                   'client_bulk_upload_page', 'bank_create', 'deleted_receipts_list',
                   'deleted_transactions_list', 'duplicate_alert_settings']
        for nombre in paginas:
            with self.subTest(pagina=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'pv-sidebar')
        detalle = self.client.get(reverse('transaction_detail', args=[self.transaccion.pk]))
        self.assertContains(detalle, 'Cambios de la transacción')
        self.assertContains(detalle, 'M0320-AAA')
        self.assertEqual(Bank.objects.count(), 1)

    def test_cada_catalogo_abre_su_formulario_y_su_confirmacion_en_la_ventana(self):
        from .models import PaymentDocument
        documento = PaymentDocument.objects.create(name='BAN', bank=self.banco)
        casos = [('bank', self.banco), ('seller', self.vendedor), ('origen_transaccion', self.origen),
                 ('TransactionType', self.tipo), ('payment_document', documento), ('Client', self.cliente)]
        for prefijo, objeto in casos:
            with self.subTest(catalogo=prefijo):
                lista = self.client.get(reverse(f'{prefijo}_list'))
                self.assertContains(lista, 'data-pv-modal')
                self.assertContains(lista, reverse(f'{prefijo}_update', args=[objeto.pk]))
                for nombre, args in ((f'{prefijo}_create', []), (f'{prefijo}_update', [objeto.pk])):
                    parcial = self.client.get(reverse(nombre, args=args), **self.AJAX).content.decode()
                    self.assertNotIn('<html', parcial)
                    self.assertIn('pv-modal-form', parcial)
                    self.assertIn('csrfmiddlewaretoken', parcial)
                confirmar = self.client.get(reverse(f'{prefijo}_delete', args=[objeto.pk]), **self.AJAX).content.decode()
                self.assertIn('data-pv-delete', confirmar)
                self.assertIn(reverse(f'{prefijo}_delete', args=[objeto.pk]), confirmar)

    def test_crear_editar_y_error_de_validacion_por_la_ventana(self):
        from .models import Bank
        respuesta = self.client.post(reverse('bank_create'), {'name': 'NEQUI'}, **self.AJAX)
        self.assertTrue(respuesta.json()['success'])
        banco = Bank.objects.get(name='NEQUI')
        respuesta = self.client.post(reverse('bank_update', args=[banco.pk]), {'name': 'NEQUI PCN'}, **self.AJAX)
        self.assertTrue(respuesta.json()['success'])
        respuesta = self.client.post(reverse('bank_create'), {'name': ''}, **self.AJAX)
        datos = respuesta.json()
        self.assertFalse(datos['success'])
        self.assertIn('errorlist', datos['form_html'])

    def test_eliminar_algo_en_uso_responde_un_mensaje_y_no_un_500(self):
        from .models import Bank
        for nombre, objeto in (('bank_delete', self.banco), ('seller_delete', self.vendedor),
                               ('origen_transaccion_delete', self.origen)):
            with self.subTest(vista=nombre):
                respuesta = self.client.post(reverse(nombre, args=[objeto.pk]), **self.AJAX)
                self.assertEqual(respuesta.status_code, 400)
                self.assertFalse(respuesta.json()['success'])
                self.assertIn('ya está en uso', respuesta.json()['message'])
        self.assertTrue(Bank.objects.filter(pk=self.banco.pk).exists())
        # Sin AJAX: aviso y regreso, tampoco un 500.
        respuesta = self.client.post(reverse('bank_delete', args=[self.banco.pk]), HTTP_REFERER='/banks/')
        self.assertRedirects(respuesta, '/banks/', fetch_redirect_response=False)

    def test_usuarios_muestra_solicitudes_y_no_consulta_roles_por_fila(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .models import AccessRequest
        nuevo = User.objects.create_user('nuevo', email='nuevo@lapocion.com', password='clave-larga-123')
        AccessRequest.objects.get_or_create(user=nuevo)

        def contar():
            with CaptureQueriesContext(connection) as consultas:
                respuesta = self.client.get(reverse('access_request_list'))
            return len(consultas), respuesta

        antes, respuesta = contar()
        self.assertContains(respuesta, 'nuevo@lapocion.com')
        self.assertContains(respuesta, reverse('user_update', args=[self.user.pk]))
        grupo = Group.objects.get(name='Digitador')
        for i in range(8):
            User.objects.create_user(f'extra{i}', password='clave-larga-123').groups.add(grupo)
        self.assertEqual(contar()[0], antes)

    def test_editar_usuario_por_la_ventana(self):
        parcial = self.client.get(reverse('user_update', args=[self.user.pk]), **self.AJAX).content.decode()
        self.assertIn('pv-modal-form', parcial)
        self.assertIn('digitador', parcial)
        validador = Group.objects.get_or_create(name='Validador')[0]
        respuesta = self.client.post(reverse('user_update', args=[self.user.pk]),
                                     {'is_active': 'on', 'groups': [validador.pk]}, **self.AJAX)
        self.assertTrue(respuesta.json()['success'])
        self.assertEqual(list(self.user.groups.values_list('name', flat=True)), ['Validador'])


class _Formulario(HTMLParser):
    """Lo que un navegador enviaría de <form id="transaction-form"> (sin el <template>)."""

    def __init__(self):
        super().__init__()
        self.datos = []
        self.dentro = False
        self.plantilla = 0
        self.select = None
        self.textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form' and a.get('id') == 'transaction-form':
            self.dentro = True
        if tag == 'template':
            self.plantilla += 1
        if not self.dentro or self.plantilla:
            return
        if tag == 'input' and a.get('name'):
            if a.get('type') in ('checkbox', 'radio') and 'checked' not in a:
                return
            if a.get('type') != 'submit':
                self.datos.append((a['name'], a.get('value', '')))
        elif tag == 'select' and a.get('name'):
            self.select = [a['name'], None, None]
        elif tag == 'option' and self.select is not None:
            if self.select[2] is None:
                self.select[2] = a.get('value', '')
            if 'selected' in a:
                self.select[1] = a.get('value', '')
        elif tag == 'textarea' and a.get('name'):
            self.textarea = [a['name'], '']

    def handle_data(self, data):
        if self.textarea is not None:
            self.textarea[1] += data

    def handle_endtag(self, tag):
        if tag == 'template':
            self.plantilla -= 1
        elif tag == 'select' and self.select is not None:
            nombre, elegido, primero = self.select
            self.datos.append((nombre, elegido if elegido is not None else (primero or '')))
            self.select = None
        elif tag == 'textarea' and self.textarea is not None:
            self.datos.append((self.textarea[0], self.textarea[1].strip('\n')))
            self.textarea = None
        elif tag == 'form':
            self.dentro = False


class GuardarSinCambiosTests(ConRecibos):
    """
    Abrir una transacción y pulsar «Guardar» sin tocar nada no debe cambiar datos ni dejar
    rastro en el historial. Antes, con un rol de solo lectura, la hora del recibo perdía
    los segundos, «creado por» quedaba vacío y la observación se guardaba como «None».
    """

    def setUp(self):
        super().setUp()
        self.transaccion.numero_factura = 'FV-900'
        self.transaccion.facturador = 'venriquez'
        self.transaccion.status = 'Facturado'
        self.transaccion.description = None
        self.transaccion.save()
        self.recibo.hora = '09:07:37'
        self.recibo.payment_document = 'BAN-25154'
        self.recibo.save()
        self.url = reverse('transaction_update', args=[self.transaccion.pk])

    def enviar_tal_cual(self, **cambios):
        pagina = self.client.get(self.url)
        self.assertEqual(pagina.status_code, 200)
        formulario = _Formulario()
        formulario.feed(pagina.content.decode())
        datos = {}
        for nombre, valor in formulario.datos:
            datos[nombre] = valor
        datos.update(cambios)
        return self.client.post(self.url, datos)

    def historial(self):
        return (Transaction.history.filter(id=self.transaccion.pk).count(),
                FinancialRecord.history.filter(id=self.recibo.pk).count())

    def test_ningun_rol_deja_historial_ni_cambia_datos_al_guardar_sin_tocar(self):
        antes = self.historial()
        roles = ['Digitador', 'Validador', 'Facturador', 'Contabilidad', None]
        for rol in roles:
            with self.subTest(rol=rol or 'superusuario'):
                if rol:
                    self.entrar_como(rol)
                else:
                    self.client.force_login(User.objects.create_superuser('jefe', password='clave-larga-123'))
                respuesta = self.enviar_tal_cual()
                self.assertEqual(respuesta.status_code, 302, getattr(respuesta, 'context', None) and respuesta.context['form'].errors)
                self.assertEqual(self.historial(), antes)
                self.transaccion.refresh_from_db()
                self.recibo.refresh_from_db()
                self.assertEqual(str(self.recibo.hora), '09:07:37')
                self.assertEqual(self.recibo.payment_document, 'BAN-25154')
                self.assertEqual(self.transaccion.created_by, self.user)
                self.assertIsNone(self.transaccion.description)
                self.assertEqual((self.transaccion.numero_factura, self.transaccion.facturador, self.transaccion.status),
                                 ('FV-900', 'venriquez', 'Facturado'))

    def test_un_cambio_real_si_se_guarda_y_queda_a_nombre_de_quien_lo_hizo(self):
        validador = self.entrar_como('Validador')
        respuesta = self.enviar_tal_cual(**{'receipts-0-payment_status': 'Aprobado'})
        self.assertEqual(respuesta.status_code, 302)
        self.recibo.refresh_from_db()
        self.assertEqual(self.recibo.payment_status, 'Aprobado')
        self.assertEqual(str(self.recibo.hora), '09:07:37')
        ultimo = FinancialRecord.history.filter(id=self.recibo.pk).first()
        self.assertEqual([c.field for c in ultimo.diff_against(ultimo.prev_record).changes if c.field != 'modificado'],
                         ['payment_status'])
        self.assertEqual(ultimo.history_user, validador)

    def test_el_facturador_sigue_pudiendo_facturar(self):
        self.transaccion.numero_factura = None
        self.transaccion.facturador = None
        self.transaccion.status = 'Pendiente'
        self.transaccion.save()
        facturador = self.entrar_como('Facturador')
        respuesta = self.enviar_tal_cual(numero_factura='FV-901', status='Facturado')
        self.assertEqual(respuesta.status_code, 302)
        self.transaccion.refresh_from_db()
        self.assertEqual((self.transaccion.numero_factura, self.transaccion.status, self.transaccion.facturador),
                         ('FV-901', 'Facturado', facturador.username))
        self.assertEqual(self.transaccion.created_by, self.user)

    def test_ver_un_recibo_no_escribe_nada(self):
        self.entrar_como('Validador')
        antes = self.historial()
        for url in (reverse('credit_list'), reverse('credit_detail', args=[self.recibo.pk]), self.url,
                    reverse('transaction_detail', args=[self.transaccion.pk]), reverse('record_list')):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.historial(), antes)


class SinRolNoVeNadaTests(ConRecibos):
    """Todo usuario debe tener un rol; sin él solo ve «acceso pendiente» y aparece en Usuarios."""

    ABIERTAS = {'login', 'logout', 'request_access', 'access_denied'}

    def rutas(self):
        from django.urls import get_resolver
        for patron in get_resolver('records.urls').url_patterns:
            nombre = getattr(patron, 'name', None)
            if not nombre or nombre in self.ABIERTAS:
                continue
            kwargs = {k: ('DUPLICATE' if k == 'key' else 1) for k in patron.pattern.converters}
            yield nombre, reverse(nombre, kwargs=kwargs)

    def test_sin_rol_todas_las_rutas_llevan_a_acceso_pendiente(self):
        from .models import AccessRequest
        sin_rol = self.entrar_como('')
        AccessRequest.objects.filter(user=sin_rol).delete()
        for nombre, url in self.rutas():
            with self.subTest(ruta=nombre):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302, nombre)
                self.assertEqual(respuesta.url, reverse('request_access'), nombre)
        # Las que antes se colaban:
        self.assertEqual(self.client.get(reverse('export_credits_csv')).status_code, 302)
        self.assertEqual(self.client.get(reverse('transaction_update', args=[self.transaccion.pk])).status_code, 302)
        ajax = self.client.get(reverse('client_search_ajax'), {'term': 'CLI'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(ajax.status_code, 403)
        self.assertEqual(self.client.get('/api/v1/transactions/').status_code, 403)
        # Puede ver su pantalla de espera y salir.
        self.assertEqual(self.client.get(reverse('request_access')).status_code, 200)
        # Y quedó en la lista para que le asignen rol.
        self.assertTrue(AccessRequest.objects.filter(user=sin_rol, approved=False).exists())

    def test_aparece_en_usuarios_y_al_darle_rol_entra(self):
        sin_rol = self.entrar_como('')
        self.client.get(reverse('record_list'))
        admin = User.objects.create_superuser('jefe', password='clave-larga-123')
        self.client.force_login(admin)
        pagina = self.client.get(reverse('access_request_list'))
        self.assertIn(sin_rol, [r.user for r in pagina.context['requests']])

        sin_rol.groups.add(Group.objects.get_or_create(name='Validador')[0])
        self.client.force_login(sin_rol)
        self.assertEqual(self.client.get(reverse('credit_list')).status_code, 200)

    def test_quitarle_los_roles_a_alguien_lo_devuelve_a_pendientes(self):
        from .models import AccessRequest
        self.user.groups.clear()
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('record_list')), reverse('request_access'))
        self.assertTrue(AccessRequest.objects.filter(user=self.user, approved=False).exists())

    def test_el_administrador_no_necesita_rol(self):
        self.client.force_login(User.objects.create_superuser('jefe', password='clave-larga-123'))
        self.assertEqual(self.client.get(reverse('record_list')).status_code, 200)
