# -*- coding: utf-8 -*-
"""
Pruebas de la llave de idempotencia de envíos de formulario.

Cubren el problema real que las motivó: con red inestable el mismo POST llega dos
veces (doble clic, F5, reintento del navegador o del proxy) y antes eso producía o
un falso "Registro duplicado exacto", o un duplicado real cuando el digitador
re-digitaba creyendo que nada se había guardado.
"""

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth.models import Group, User
from django.db import connection, connections, transaction
from django.test import Client as DjangoClient
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .idempotency import (
    DuplicateSubmission,
    SUBMIT_TOKEN_FIELD,
    already_submitted,
    claim_submission,
    complete_submission,
    posted_token,
)
from .models import (
    Bank,
    Client,
    DuplicateRecordAttempt,
    FinancialRecord,
    FormSubmission,
    OrigenTransaccion,
    Seller,
    Transaction,
    TransactionType,
)


class IdempotencyHelpersTests(TestCase):
    """Pruebas unitarias del módulo, sin pasar por las vistas."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user('digitador', password='x')

    def _post(self, token):
        data = {SUBMIT_TOKEN_FIELD: str(token)} if token is not None else {}
        request = self.factory.post('/new/', data)
        request.user = self.user
        return request

    def test_claim_dos_veces_con_el_mismo_token_falla(self):
        token = uuid.uuid4()

        with transaction.atomic():
            claim = claim_submission(self._post(token), 'record_create')
        self.assertIsNotNone(claim)
        self.assertEqual(FormSubmission.objects.count(), 1)

        # El atomic es parte del contrato: el IntegrityError deja la transacción
        # abortada, y es el atomic el que la devuelve a un estado usable al salir.
        # Por eso las vistas llaman a claim_submission() dentro de su propio atomic.
        with self.assertRaises(DuplicateSubmission) as ctx:
            with transaction.atomic():
                claim_submission(self._post(token), 'record_create')

        self.assertEqual(ctx.exception.token, token)
        self.assertEqual(FormSubmission.objects.count(), 1)

    def test_tokens_distintos_no_se_estorban(self):
        with transaction.atomic():
            claim_submission(self._post(uuid.uuid4()), 'record_create')
        with transaction.atomic():
            claim_submission(self._post(uuid.uuid4()), 'record_create')
        self.assertEqual(FormSubmission.objects.count(), 2)

    def test_already_submitted_detecta_el_reenvio_y_cuenta_los_reintentos(self):
        token = uuid.uuid4()
        with transaction.atomic():
            claim = claim_submission(self._post(token), 'record_create')
            complete_submission(claim, result_url='/records/', result_pk=7, result_label='ABC')

        prior = already_submitted(self._post(token))
        self.assertIsNotNone(prior)
        self.assertEqual(prior.result_url, '/records/')
        self.assertEqual(prior.result_label, 'ABC')

        # El contador crece con cada reenvío: es la traza medible del problema de red.
        claim.refresh_from_db()
        self.assertEqual(claim.retry_count, 1)

        already_submitted(self._post(token))
        claim.refresh_from_db()
        self.assertEqual(claim.retry_count, 2)

    def test_already_submitted_devuelve_none_en_un_envio_nuevo(self):
        self.assertIsNone(already_submitted(self._post(uuid.uuid4())))

    def test_degradacion_sin_token_o_con_token_invalido(self):
        # Formulario viejo en caché: la vista debe seguir funcionando como antes.
        self.assertIsNone(posted_token(self._post(None)))
        self.assertIsNone(claim_submission(self._post(None), 'record_create'))
        self.assertIsNone(already_submitted(self._post(None)))

        request = self.factory.post('/new/', {SUBMIT_TOKEN_FIELD: 'no-es-un-uuid'})
        request.user = self.user
        self.assertIsNone(posted_token(request))
        self.assertIsNone(claim_submission(request, 'record_create'))

        self.assertEqual(FormSubmission.objects.count(), 0)

    def test_complete_submission_con_claim_nulo_no_revienta(self):
        complete_submission(None, result_url='/records/')  # no debe lanzar


@override_settings(SECURE_SSL_REDIRECT=False)
class DatosBase(TestCase):
    """
    Catálogos y usuario compartidos por las pruebas de vistas.

    SECURE_SSL_REDIRECT se desactiva porque con DEBUG=False (staging y producción)
    el cliente de pruebas, que pide por HTTP, recibiría un 301 a HTTPS. Así la suite
    corre igual en local con SQLite y dentro del contenedor contra PostgreSQL.
    """

    def setUp(self):
        self.user = User.objects.create_user('digitador', password='clave-larga-123')
        grupo, _ = Group.objects.get_or_create(name='Digitador')
        self.user.groups.add(grupo)
        self.client.force_login(self.user)

        self.cliente = Client.objects.create(name='CLIENTE PRUEBA', dni='900123456')
        self.vendedor = Seller.objects.create(name='VENDEDOR PRUEBA')
        # La migración 0025 inserta TransactionType con id=1 explícito, sin avanzar la
        # secuencia, así que en PostgreSQL el primer create() de una BD recién migrada
        # choca con esa fila. Reutilizamos la que ya existe: a estas pruebas les da
        # igual el nombre del tipo.
        self.tipo = TransactionType.objects.first() or TransactionType.objects.create(name='VENTA')
        self.banco = Bank.objects.create(name='BANCOLOMBIA')
        self.origen = OrigenTransaccion.objects.create(name='TRANSFERENCIA')


class CreateBulkReceiptsIdempotenciaTests(DatosBase):
    """El formulario principal de captura: /new/."""

    def _payload(self, token, comprobante='REC-001', valor='150000.00'):
        hoy = timezone.now().date()
        return {
            SUBMIT_TOKEN_FIELD: str(token),
            # --- TransactionForm ---
            'date': hoy.isoformat(),
            'client_search': str(self.cliente),
            'cliente_id': self.cliente.pk,
            'seller_search': self.vendedor.name,
            'vendedor_id': self.vendedor.pk,
            'transaction_type': self.tipo.pk,
            'expected_amount': valor,
            'description': 'Prueba',
            'status': 'Pendiente',
            'numero_factura': '',
            'facturador': '',
            # --- formset de recibos (prefijo 'receipts', no 'form') ---
            'receipts-TOTAL_FORMS': '1',
            'receipts-INITIAL_FORMS': '0',
            'receipts-MIN_NUM_FORMS': '0',
            'receipts-MAX_NUM_FORMS': '1000',
            'receipts-0-id': '',
            'receipts-0-origen_transaccion': self.origen.pk,
            'receipts-0-fecha': hoy.isoformat(),
            'receipts-0-hora': '10:30:00',
            'receipts-0-comprobante': comprobante,
            'receipts-0-banco_llegada': self.banco.pk,
            'receipts-0-valor': valor,
            'receipts-0-payment_status': 'Pendiente',
            'receipts-0-payment_document': '',
        }

    def test_guardado_normal(self):
        respuesta = self.client.post(reverse('record_create'), self._payload(uuid.uuid4()))

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(FinancialRecord.objects.count(), 1)

        token = FormSubmission.objects.get()
        self.assertEqual(token.scope, 'record_create')
        self.assertEqual(token.retry_count, 0)
        self.assertEqual(token.result_pk, Transaction.objects.get().pk)
        self.assertTrue(token.result_url)

    def test_reenvio_con_el_mismo_token_no_duplica_ni_marca_duplicado(self):
        """El caso reportado: el POST se reenvía por red y antes salía 'duplicado'."""
        token = uuid.uuid4()
        payload = self._payload(token)

        self.client.post(reverse('record_create'), payload)
        self.assertEqual(Transaction.objects.count(), 1)

        # Exactamente el mismo cuerpo, byte por byte, como en un reintento de red.
        respuesta = self.client.post(reverse('record_create'), payload, follow=True)

        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(FinancialRecord.objects.count(), 1)

        # No se ensucia la bandeja de duplicados con un falso positivo.
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 0)

        mensajes = [str(m) for m in respuesta.context['messages']]
        self.assertTrue(
            any('ya fue guardado' in m for m in mensajes),
            f'Se esperaba el aviso de reenvío, llegaron: {mensajes}'
        )
        self.assertFalse(
            any('duplicado exacto' in m.lower() for m in mensajes),
            f'No debía aparecer el error de duplicado: {mensajes}'
        )

        FormSubmission.objects.get()  # sigue habiendo un solo token
        self.assertEqual(FormSubmission.objects.get().retry_count, 1)

    def test_duplicado_genuino_sigue_detectandose(self):
        """No-regresión: re-digitar el mismo recibo con un token nuevo SÍ es duplicado."""
        self.client.post(reverse('record_create'), self._payload(uuid.uuid4()))
        self.assertEqual(FinancialRecord.objects.count(), 1)

        # Formulario nuevo (token distinto) con los mismos cinco campos clave.
        respuesta = self.client.post(reverse('record_create'), self._payload(uuid.uuid4()))

        self.assertEqual(respuesta.status_code, 200)  # re-render, no redirect
        self.assertEqual(FinancialRecord.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)

        # Y el intento sí queda registrado para el administrador.
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 1)
        intento = DuplicateRecordAttempt.objects.get()
        self.assertEqual(intento.attempt_type, 'DUPLICATE')
        self.assertIn('_registro_existente_pk', intento.data)

    def test_error_de_validacion_no_consume_el_token(self):
        """Se corrige el error y se reenvía con el MISMO token: debe guardar."""
        token = uuid.uuid4()
        payload = self._payload(token)
        payload['receipts-0-fecha'] = (timezone.now().date() - timedelta(days=90)).isoformat()

        respuesta = self.client.post(reverse('record_create'), payload)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(FinancialRecord.objects.count(), 0)
        self.assertEqual(FormSubmission.objects.count(), 0)

        # Mismo token, fecha corregida.
        respuesta = self.client.post(reverse('record_create'), self._payload(token))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(FinancialRecord.objects.count(), 1)

    def test_post_sin_token_se_comporta_como_antes(self):
        payload = self._payload(uuid.uuid4())
        del payload[SUBMIT_TOKEN_FIELD]

        respuesta = self.client.post(reverse('record_create'), payload)

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(FormSubmission.objects.count(), 0)

    def test_formulario_trae_token_y_no_se_cachea(self):
        respuesta = self.client.get(reverse('record_create'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(f'name="{SUBMIT_TOKEN_FIELD}"', respuesta.content.decode())
        self.assertIn('no-store', respuesta.headers['Cache-Control'])


class CreditNoteFromSurplusTests(DatosBase):
    """El único camino que producía duplicados reales y silenciosos."""

    def setUp(self):
        super().setUp()
        self.transaccion = Transaction.objects.create(
            date=timezone.now().date(),
            cliente=self.cliente,
            vendedor=self.vendedor,
            transaction_type=self.tipo,
            expected_amount=Decimal('100000.00'),
            created_by=self.user,
        )
        # Recibo por encima de lo esperado -> excedente de 20.000
        FinancialRecord.objects.create(
            fecha=timezone.now().date(),
            hora='09:00:00',
            comprobante='PAGO-EXCESO',
            banco_llegada=self.banco,
            origen_transaccion=self.origen,
            valor=Decimal('120000.00'),
            transaction=self.transaccion,
            uploaded_by=self.user,
        )

    def _url(self):
        return reverse('create_credit_note_from_surplus', args=[self.transaccion.pk])

    def test_genera_el_par_una_sola_vez(self):
        respuesta = self.client.post(self._url(), {SUBMIT_TOKEN_FIELD: str(uuid.uuid4())})
        self.assertEqual(respuesta.status_code, 302)

        sufijo = self.transaccion.unique_transaction_id
        self.assertEqual(
            FinancialRecord.objects.filter(comprobante=f'SF-FAVOR-{sufijo}').count(), 1
        )
        self.assertEqual(
            FinancialRecord.objects.filter(comprobante=f'SF-AJUSTE-{sufijo}').count(), 1
        )

        # La transacción queda balanceada.
        self.transaccion.refresh_from_db()
        self.assertEqual(self.transaccion.difference, Decimal('0.00'))

    def test_el_par_comparte_la_misma_hora(self):
        """Antes se llamaba timezone.now() cuatro veces y podían caer en segundos distintos."""
        self.client.post(self._url(), {SUBMIT_TOKEN_FIELD: str(uuid.uuid4())})

        sufijo = self.transaccion.unique_transaction_id
        favor = FinancialRecord.objects.get(comprobante=f'SF-FAVOR-{sufijo}')
        ajuste = FinancialRecord.objects.get(comprobante=f'SF-AJUSTE-{sufijo}')

        self.assertEqual(favor.hora, ajuste.hora)
        self.assertEqual(favor.fecha, ajuste.fecha)

    def test_reenvio_no_crea_un_segundo_par(self):
        token = str(uuid.uuid4())
        payload = {SUBMIT_TOKEN_FIELD: token}

        self.client.post(self._url(), payload)
        respuesta = self.client.post(self._url(), payload, follow=True)

        sufijo = self.transaccion.unique_transaction_id
        self.assertEqual(
            FinancialRecord.objects.filter(comprobante=f'SF-FAVOR-{sufijo}').count(), 1
        )
        self.assertEqual(
            FinancialRecord.objects.filter(comprobante=f'SF-AJUSTE-{sufijo}').count(), 1
        )

        mensajes = [str(m) for m in respuesta.context['messages']]
        self.assertFalse(
            any('inesperado' in m.lower() for m in mensajes),
            f'El except genérico se tragó la excepción de control: {mensajes}'
        )

    def test_reenvio_con_token_nuevo_tampoco_crea_un_segundo_par(self):
        """Sin token (o con uno nuevo) la guarda determinista del comprobante protege."""
        self.client.post(self._url(), {SUBMIT_TOKEN_FIELD: str(uuid.uuid4())})
        self.client.post(self._url(), {SUBMIT_TOKEN_FIELD: str(uuid.uuid4())})

        sufijo = self.transaccion.unique_transaction_id
        self.assertEqual(
            FinancialRecord.objects.filter(comprobante__startswith=f'SF-FAVOR-{sufijo}').count(), 1
        )
        self.assertEqual(
            FinancialRecord.objects.filter(comprobante__startswith=f'SF-AJUSTE-{sufijo}').count(), 1
        )


class CreditCreateIdempotenciaTests(DatosBase):
    """Registro de abonos: /credit/nuevo/."""

    def _payload(self, token, comprobante='ABONO-001', valor='80000.00'):
        hoy = timezone.now().date()
        return {
            SUBMIT_TOKEN_FIELD: str(token),
            'client_search': str(self.cliente),
            'cliente_id': self.cliente.pk,
            'origen_transaccion': self.origen.pk,
            'fecha': hoy.isoformat(),
            'hora': '11:15:00',
            'comprobante': comprobante,
            'banco_llegada': self.banco.pk,
            'valor': valor,
            'payment_status': 'Pendiente',
            'payment_document': '',
            'note': 'Abono de prueba',
        }

    def test_guardado_normal(self):
        respuesta = self.client.post(reverse('credit_create'), self._payload(uuid.uuid4()))

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(FinancialRecord.objects.count(), 1)

        token = FormSubmission.objects.get()
        self.assertEqual(token.scope, 'credit_create')
        self.assertEqual(token.result_pk, FinancialRecord.objects.get().pk)

    def test_el_abono_se_guarda_una_sola_vez(self):
        """
        Antes, form_valid() guardaba y después super().form_valid() volvía a llamar
        form.save(), dejando una fila de historial espuria por abono.
        """
        self.client.post(reverse('credit_create'), self._payload(uuid.uuid4()))

        abono = FinancialRecord.objects.get()
        self.assertEqual(abono.history.count(), 1)

    def test_reenvio_con_el_mismo_token_no_duplica(self):
        token = uuid.uuid4()
        payload = self._payload(token)

        self.client.post(reverse('credit_create'), payload)
        respuesta = self.client.post(reverse('credit_create'), payload, follow=True)

        self.assertEqual(FinancialRecord.objects.count(), 1)
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 0)

        mensajes = [str(m) for m in respuesta.context['messages']]
        self.assertTrue(
            any('ya fue guardado' in m for m in mensajes),
            f'Se esperaba el aviso de reenvío, llegaron: {mensajes}'
        )


@override_settings(SECURE_SSL_REDIRECT=False)
@skipUnless(
    connection.vendor == 'postgresql',
    'La espera fina de fila del INSERT en conflicto solo existe en PostgreSQL; '
    'en SQLite el segundo escritor da "database is locked".'
)
class ConcurrenciaTests(TransactionTestCase):
    """
    Dos POST idénticos EN VUELO A LA VEZ, que es el caso que ni el guard del cliente
    ni el pre-chequeo pueden atrapar. Aquí la carrera la resuelve PostgreSQL: el
    INSERT de la PK duplicada espera al commit o rollback de la transacción rival.

    Se salta en SQLite a propósito: allí el resultado sería flaky y no representa el
    comportamiento de producción (Railway usa PostgreSQL).
    """

    def setUp(self):
        self.user = User.objects.create_user('digitador', password='clave-larga-123')
        grupo, _ = Group.objects.get_or_create(name='Digitador')
        self.user.groups.add(grupo)

        self.cliente = Client.objects.create(name='CLIENTE PRUEBA', dni='900123456')
        self.vendedor = Seller.objects.create(name='VENDEDOR PRUEBA')
        # La migración 0025 inserta TransactionType con id=1 explícito, sin avanzar la
        # secuencia, así que en PostgreSQL el primer create() de una BD recién migrada
        # choca con esa fila. Reutilizamos la que ya existe: a estas pruebas les da
        # igual el nombre del tipo.
        self.tipo = TransactionType.objects.first() or TransactionType.objects.create(name='VENTA')
        self.banco = Bank.objects.create(name='BANCOLOMBIA')
        self.origen = OrigenTransaccion.objects.create(name='TRANSFERENCIA')

        hoy = timezone.now().date()
        self.payload = {
            SUBMIT_TOKEN_FIELD: str(uuid.uuid4()),
            'date': hoy.isoformat(),
            'client_search': str(self.cliente),
            'cliente_id': self.cliente.pk,
            'seller_search': self.vendedor.name,
            'vendedor_id': self.vendedor.pk,
            'transaction_type': self.tipo.pk,
            'expected_amount': '150000.00',
            'description': 'Prueba concurrente',
            'status': 'Pendiente',
            'numero_factura': '',
            'facturador': '',
            'receipts-TOTAL_FORMS': '1',
            'receipts-INITIAL_FORMS': '0',
            'receipts-MIN_NUM_FORMS': '0',
            'receipts-MAX_NUM_FORMS': '1000',
            'receipts-0-id': '',
            'receipts-0-origen_transaccion': self.origen.pk,
            'receipts-0-fecha': hoy.isoformat(),
            'receipts-0-hora': '10:30:00',
            'receipts-0-comprobante': 'REC-CONCURRENTE',
            'receipts-0-banco_llegada': self.banco.pk,
            'receipts-0-valor': '150000.00',
            'receipts-0-payment_status': 'Pendiente',
            'receipts-0-payment_document': '',
        }

    def _enviar(self, resultados, indice, barrera):
        try:
            cliente_http = DjangoClient()
            cliente_http.force_login(self.user)
            barrera.wait(timeout=10)  # los dos POST arrancan a la vez
            respuesta = cliente_http.post(reverse('record_create'), self.payload)
            resultados[indice] = respuesta.status_code
        except Exception as exc:  # se reporta en el assert, no se silencia
            resultados[indice] = repr(exc)
        finally:
            connections.close_all()

    def test_dos_post_simultaneos_crean_una_sola_transaccion(self):
        resultados = [None, None]
        barrera = threading.Barrier(2)
        hilos = [
            threading.Thread(target=self._enviar, args=(resultados, i, barrera))
            for i in range(2)
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        self.assertEqual(
            resultados, [302, 302],
            f'Ambos POST debían redirigir sin error 500. Resultados: {resultados}'
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(FinancialRecord.objects.count(), 1)
        self.assertEqual(FormSubmission.objects.count(), 1)
        self.assertEqual(DuplicateRecordAttempt.objects.count(), 0)


class RenderDelTokenTests(DatosBase):
    """
    Comprueba que los cuatro formularios de captura emiten el campo oculto y que las
    páginas no se cachean (si el navegador restaurara el formulario desde bfcache con
    un token ya consumido, el digitador perdería el registro siguiente).
    """

    def test_formulario_de_abono(self):
        respuesta = self.client.get(reverse('credit_create'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.content.decode().count(f'name="{SUBMIT_TOKEN_FIELD}"'), 1)
        self.assertIn('no-store', respuesta.headers['Cache-Control'])

    def test_formulario_de_transaccion_emite_un_token_por_formulario(self):
        transaccion = Transaction.objects.create(
            date=timezone.now().date(),
            cliente=self.cliente,
            vendedor=self.vendedor,
            transaction_type=self.tipo,
            expected_amount=Decimal('100000.00'),
            created_by=self.user,
        )
        # Excedente, para que aparezca también el formulario de "Generar Saldo a Favor".
        FinancialRecord.objects.create(
            fecha=timezone.now().date(),
            hora='09:00:00',
            comprobante='PAGO-EXCESO-RENDER',
            banco_llegada=self.banco,
            origen_transaccion=self.origen,
            valor=Decimal('120000.00'),
            transaction=transaccion,
            uploaded_by=self.user,
        )

        respuesta = self.client.get(reverse('transaction_update', args=[transaccion.pk]))
        html = respuesta.content.decode()

        self.assertEqual(respuesta.status_code, 200)
        # Dos formularios en la misma página -> dos tokens independientes.
        self.assertEqual(html.count(f'name="{SUBMIT_TOKEN_FIELD}"'), 2)
        self.assertIn('no-store', respuesta.headers['Cache-Control'])

    def test_los_tokens_de_una_misma_pagina_son_distintos(self):
        primera = self.client.get(reverse('record_create')).content.decode()
        segunda = self.client.get(reverse('record_create')).content.decode()

        import re
        patron = re.compile(rf'name="{SUBMIT_TOKEN_FIELD}" value="([^"]+)"')
        token_a = patron.search(primera).group(1)
        token_b = patron.search(segunda).group(1)

        self.assertNotEqual(token_a, token_b, 'Cada render debe traer un token nuevo.')

    def test_el_guard_de_doble_submit_esta_activo_en_los_formularios(self):
        for url in [reverse('record_create'), reverse('credit_create')]:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('data-submit-once', html)
                self.assertIn('submit-once', html)  # el <script> de base.html
