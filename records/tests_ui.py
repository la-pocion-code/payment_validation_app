# -*- coding: utf-8 -*-
"""
Pruebas de las pantallas rediseñadas: buscador global, lista y detalle de recibos,
aviso previo de duplicado y el segundo chequeo de reenvío con varios workers.
"""

import uuid
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from . import tests as base
from . import views
from .idempotency import SUBMIT_TOKEN_FIELD, already_submitted
from .models import DuplicateRecordAttempt, FinancialRecord, Transaction


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

    def test_usuario_sin_rol_no_ve_resultados(self):
        self.entrar_como('')
        respuesta = self.buscar('M0320')
        self.assertFalse(respuesta.context['searched'])

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
