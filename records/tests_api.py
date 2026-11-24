# -*- coding: utf-8 -*-
"""
Pruebas de la API REST (/api/v1/): llaves, permisos, reglas de duplicados,
idempotencia y sincronización incremental.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    ApiKey, Client, DuplicateRecordAttempt, FinancialRecord, FormSubmission, Transaction,
)
from .tests import DatosBase


class ApiBase(DatosBase):
    def setUp(self):
        super().setUp()
        cache.clear()  # contadores del throttle
        self.key_lectura, self.raw_lectura = ApiKey.issue('Intranet')
        self.key_escritura, self.raw_escritura = ApiKey.issue('Odoo', can_write=True)
        self.api = APIClient()
        self.usar(self.raw_escritura)
        self.hoy = timezone.localdate()

    def usar(self, raw_key):
        self.api.credentials(HTTP_AUTHORIZATION=f'Api-Key {raw_key}')

    def recibo(self, **cambios):
        datos = {
            'fecha': self.hoy.isoformat(),
            'hora': '09:00:00',
            'comprobante': 'API-001',
            'banco_llegada': self.banco.pk,
            'origen_transaccion': self.origen.pk,
            'valor': '60000.00',
        }
        datos.update(cambios)
        return datos

    def transaccion(self, **cambios):
        datos = {
            'date': self.hoy.isoformat(),
            'cliente': self.cliente.pk,
            'vendedor': self.vendedor.pk,
            'transaction_type': self.tipo.pk,
            'expected_amount': '100000.00',
            'receipts': [self.recibo()],
        }
        datos.update(cambios)
        return datos

    def crear_transaccion(self, **cambios):
        respuesta = self.api.post('/api/v1/transactions/', self.transaccion(**cambios), format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return respuesta.data


class AutenticacionTests(ApiBase):
    def test_sin_credenciales_responde_401(self):
        self.assertEqual(APIClient().get('/api/v1/transactions/').status_code, 401)

    def test_llave_invalida_o_desactivada_responde_401(self):
        self.usar('pv_00000000_no-existe')
        self.assertEqual(self.api.get('/api/v1/transactions/').status_code, 401)

        self.key_lectura.is_active = False
        self.key_lectura.save()
        self.usar(self.raw_lectura)
        self.assertEqual(self.api.get('/api/v1/transactions/').status_code, 401)

    def test_la_llave_no_se_guarda_en_claro(self):
        self.assertNotIn(self.raw_lectura, [self.key_lectura.hashed_key, self.key_lectura.prefix])
        self.assertEqual(self.key_lectura.hashed_key, ApiKey.hash_key(self.raw_lectura))

    def test_llave_de_solo_lectura_consulta_pero_no_escribe(self):
        self.usar(self.raw_lectura)
        self.assertEqual(self.api.get('/api/v1/transactions/').status_code, 200)
        self.assertEqual(self.api.get('/api/v1/banks/').status_code, 200)

        respuesta = self.api.post('/api/v1/transactions/', self.transaccion(), format='json')
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_usuario_de_la_app_entra_con_su_sesion_y_respeta_su_rol(self):
        navegador = APIClient()
        navegador.force_login(self.user)  # Digitador
        self.assertEqual(navegador.get('/api/v1/transactions/').status_code, 200)

        creada = navegador.post('/api/v1/transactions/', self.transaccion(), format='json')
        self.assertEqual(creada.status_code, 201, creada.data)
        # Facturar no es del Digitador.
        facturar = navegador.patch(
            f"/api/v1/transactions/{creada.data['id']}/",
            {'status': 'Facturado', 'numero_factura': 'FV-1'}, format='json')
        self.assertEqual(facturar.status_code, 403)

    def test_usuario_sin_grupo_no_consulta(self):
        sin_grupo = User.objects.create_user('nuevo', password='clave-larga-123')
        navegador = APIClient()
        navegador.force_login(sin_grupo)
        self.assertEqual(navegador.get('/api/v1/transactions/').status_code, 403)

    def test_no_hay_borrado_ni_put(self):
        creada = self.crear_transaccion()
        url = f"/api/v1/transactions/{creada['id']}/"
        self.assertEqual(self.api.delete(url).status_code, 405)
        self.assertEqual(self.api.put(url, {}, format='json').status_code, 405)


class TransaccionesTests(ApiBase):
    def test_crear_con_recibos(self):
        datos = self.crear_transaccion()

        self.assertTrue(datos['unique_transaction_id'])
        self.assertEqual(datos['status'], 'Pendiente')
        self.assertEqual(datos['cliente']['dni'], self.cliente.dni)
        self.assertEqual(datos['receipts_total'], '60000.00')
        self.assertEqual(datos['difference'], '40000.00')
        self.assertFalse(datos['all_receipts_approved'])
        self.assertEqual(len(datos['receipts']), 1)
        self.assertEqual(datos['receipts'][0]['payment_status'], 'Pendiente')

        transaccion = Transaction.objects.get(pk=datos['id'])
        # Queda auditado a nombre del usuario de servicio de la integración.
        self.assertEqual(transaccion.created_by, self.key_escritura.user)
        self.assertEqual(transaccion.history.first().history_user, self.key_escritura.user)
        self.assertEqual(transaccion.receipts.get().uploaded_by, self.key_escritura.user)

    def test_crear_por_dni_del_cliente(self):
        datos = self.transaccion(cliente_dni=self.cliente.dni)
        datos.pop('cliente')
        respuesta = self.api.post('/api/v1/transactions/', datos, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data['cliente']['id'], self.cliente.pk)

    def test_validaciones(self):
        casos = {
            'cliente_dni': self.transaccion(cliente=None, cliente_dni='0000'),
            'expected_amount': self.transaccion(expected_amount='0'),
            'receipts': self.transaccion(receipts=[self.recibo(), self.recibo()]),
        }
        casos['cliente_dni'].pop('cliente')
        for campo, datos in casos.items():
            with self.subTest(campo=campo):
                respuesta = self.api.post('/api/v1/transactions/', datos, format='json')
                self.assertEqual(respuesta.status_code, 400, respuesta.data)
                self.assertIn(campo, respuesta.data)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_fecha_futura_del_recibo_se_rechaza(self):
        manana = (self.hoy + timedelta(days=1)).isoformat()
        respuesta = self.api.post(
            '/api/v1/transactions/', self.transaccion(receipts=[self.recibo(fecha=manana)]), format='json')
        self.assertEqual(respuesta.status_code, 400)

    def test_facturar(self):
        creada = self.crear_transaccion()
        url = f"/api/v1/transactions/{creada['id']}/"

        sin_numero = self.api.patch(url, {'status': 'Facturado'}, format='json')
        self.assertEqual(sin_numero.status_code, 400)
        self.assertIn('numero_factura', sin_numero.data)

        respuesta = self.api.patch(
            url, {'status': 'Facturado', 'numero_factura': 'FV-1001', 'odoo_id': 555}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data['status'], 'Facturado')
        self.assertEqual(respuesta.data['numero_factura'], 'FV-1001')
        self.assertEqual(respuesta.data['odoo_id'], 555)
        self.assertEqual(respuesta.data['facturador'], self.key_escritura.user.username)

    def test_no_se_pueden_cambiar_montos_por_patch(self):
        creada = self.crear_transaccion()
        self.api.patch(f"/api/v1/transactions/{creada['id']}/", {'expected_amount': '1.00'}, format='json')
        self.assertEqual(Transaction.objects.get(pk=creada['id']).expected_amount, Decimal('100000.00'))

    def test_la_lista_no_consulta_por_fila(self):
        self.crear_transaccion()

        def consultas():
            with CaptureQueriesContext(connection) as contexto:
                respuesta = self.api.get('/api/v1/transactions/')
            self.assertEqual(respuesta.status_code, 200)
            return len(contexto), respuesta.data

        con_una, _ = consultas()
        for i in range(8):
            self.crear_transaccion(receipts=[
                self.recibo(comprobante=f'API-L{i}-A', hora='10:00:00', valor=f'{1000 + i}.00'),
                self.recibo(comprobante=f'API-L{i}-B', hora='11:00:00', valor=f'{2000 + i}.00'),
            ])
        con_nueve, datos = consultas()

        self.assertEqual(con_una, con_nueve)
        self.assertEqual(datos['count'], 9)
        self.assertEqual(len(datos['results']), 9)


class DuplicadosTests(ApiBase):
    def test_duplicado_exacto_responde_409_con_el_recibo_existente(self):
        creada = self.crear_transaccion()
        existente = creada['receipts'][0]['id']

        for url, datos in (
            ('/api/v1/transactions/', self.transaccion()),
            ('/api/v1/receipts/', self.recibo(cliente=self.cliente.pk)),
        ):
            with self.subTest(url=url):
                respuesta = self.api.post(url, datos, format='json')
                self.assertEqual(respuesta.status_code, 409, respuesta.data)
                self.assertEqual(respuesta.data['code'], 'duplicate')
                self.assertEqual(int(respuesta.data['existing_id']), existente)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(FinancialRecord.objects.count(), 1)

    def test_posible_duplicado_exige_confirmacion(self):
        self.crear_transaccion()
        parecido = self.recibo(comprobante='API-OTRO', cliente=self.cliente.pk)

        respuesta = self.api.post('/api/v1/receipts/', parecido, format='json')
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data['code'], 'similar_duplicate')
        self.assertEqual(FinancialRecord.objects.count(), 1)

        confirmado = self.api.post(
            '/api/v1/receipts/', dict(parecido, confirm_duplicate=True), format='json')
        self.assertEqual(confirmado.status_code, 201, confirmado.data)
        self.assertEqual(FinancialRecord.objects.count(), 2)
        # Queda en la bandeja de duplicados, ya resuelto, como en la interfaz.
        intento = DuplicateRecordAttempt.objects.get()
        self.assertEqual(intento.attempt_type, 'SIMILAR')
        self.assertTrue(intento.is_resolved)


class IdempotenciaTests(ApiBase):
    def test_reintento_con_la_misma_llave_no_duplica(self):
        llave = str(uuid.uuid4())
        primera = self.api.post(
            '/api/v1/transactions/', self.transaccion(), format='json', HTTP_IDEMPOTENCY_KEY=llave)
        self.assertEqual(primera.status_code, 201, primera.data)

        segunda = self.api.post(
            '/api/v1/transactions/', self.transaccion(), format='json', HTTP_IDEMPOTENCY_KEY=llave)
        self.assertEqual(segunda.status_code, 200, segunda.data)
        self.assertEqual(segunda['Idempotent-Replayed'], 'true')
        self.assertEqual(segunda.data['id'], primera.data['id'])

        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(FinancialRecord.objects.count(), 1)
        self.assertEqual(FormSubmission.objects.get(pk=llave).retry_count, 1)

    def test_un_envio_rechazado_no_consume_la_llave(self):
        llave = str(uuid.uuid4())
        mala = self.api.post(
            '/api/v1/transactions/', self.transaccion(expected_amount='0'),
            format='json', HTTP_IDEMPOTENCY_KEY=llave)
        self.assertEqual(mala.status_code, 400)

        buena = self.api.post(
            '/api/v1/transactions/', self.transaccion(), format='json', HTTP_IDEMPOTENCY_KEY=llave)
        self.assertEqual(buena.status_code, 201, buena.data)

    def test_llave_mal_formada_o_reusada_en_otro_recurso(self):
        mal = self.api.post(
            '/api/v1/transactions/', self.transaccion(), format='json', HTTP_IDEMPOTENCY_KEY='no-es-uuid')
        self.assertEqual(mal.status_code, 400)

        llave = str(uuid.uuid4())
        self.api.post('/api/v1/transactions/', self.transaccion(), format='json', HTTP_IDEMPOTENCY_KEY=llave)
        otro = self.api.post(
            '/api/v1/receipts/', self.recibo(comprobante='API-X', hora='12:00:00', cliente=self.cliente.pk),
            format='json', HTTP_IDEMPOTENCY_KEY=llave)
        self.assertEqual(otro.status_code, 400)


class RecibosYSincronizacionTests(ApiBase):
    def test_aprobar_un_pago_y_ver_la_transaccion_lista_para_facturar(self):
        creada = self.crear_transaccion()
        recibo = creada['receipts'][0]['id']

        listas = self.api.get('/api/v1/transactions/', {'listas_para_facturar': 'true'})
        self.assertEqual(listas.data['count'], 0)

        aprobado = self.api.patch(f'/api/v1/receipts/{recibo}/', {'payment_status': 'Aprobado'}, format='json')
        self.assertEqual(aprobado.status_code, 200, aprobado.data)
        self.assertEqual(aprobado.data['payment_status'], 'Aprobado')

        listas = self.api.get('/api/v1/transactions/', {'listas_para_facturar': 'true'})
        self.assertEqual(listas.data['count'], 1)
        self.assertTrue(listas.data['results'][0]['all_receipts_approved'])

    def test_updated_since_ve_el_cambio_de_un_recibo(self):
        creada = self.crear_transaccion()
        ayer = timezone.now() - timedelta(days=1)
        # Se envejece la transacción y su recibo...
        Transaction.objects.filter(pk=creada['id']).update(updated_at=ayer)
        FinancialRecord.objects.filter(transaction_id=creada['id']).update(modificado=ayer)
        corte = (timezone.now() - timedelta(minutes=5)).isoformat()

        sin_cambios = self.api.get('/api/v1/transactions/', {'updated_since': corte})
        self.assertEqual(sin_cambios.data['count'], 0)

        # ...y el validador aprueba el pago: la transacción vuelve a salir.
        self.api.patch(
            f"/api/v1/receipts/{creada['receipts'][0]['id']}/", {'payment_status': 'Aprobado'}, format='json')
        con_cambios = self.api.get('/api/v1/transactions/', {'updated_since': corte})
        self.assertEqual(con_cambios.data['count'], 1)
        self.assertEqual(self.api.get('/api/v1/receipts/', {'updated_since': corte}).data['count'], 1)

    def test_abono_suelto_suma_al_saldo_a_favor(self):
        respuesta = self.api.post('/api/v1/receipts/', self.recibo(cliente=self.cliente.pk), format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertIsNone(respuesta.data['transaction'])
        self.assertEqual(respuesta.data['cliente']['id'], self.cliente.pk)

        saldo = self.api.get(f'/api/v1/clients/{self.cliente.pk}/balance/')
        self.assertEqual(saldo.data['available_balance'], '60000.00')

        sin_destino = self.api.post(
            '/api/v1/receipts/', self.recibo(comprobante='API-SIN', hora='13:00:00'), format='json')
        self.assertEqual(sin_destino.status_code, 400)


class ClientesTests(ApiBase):
    def test_upsert_crea_y_luego_actualiza_por_dni(self):
        nuevo = self.api.post(
            '/api/v1/clients/upsert/', {'dni': '800555-1', 'name': 'Drogueria Central', 'odoo_id': 77},
            format='json')
        self.assertEqual(nuevo.status_code, 201, nuevo.data)

        mismo = self.api.post(
            '/api/v1/clients/upsert/', {'dni': '800555-1', 'name': 'Drogueria Central SAS', 'odoo_id': 78},
            format='json')
        self.assertEqual(mismo.status_code, 200, mismo.data)
        self.assertEqual(mismo.data['id'], nuevo.data['id'])
        self.assertEqual(mismo.data['odoo_id'], 78)
        self.assertEqual(Client.objects.filter(dni='800555-1').count(), 1)

    def test_buscar_por_dni(self):
        respuesta = self.api.get('/api/v1/clients/', {'dni': self.cliente.dni})
        self.assertEqual(respuesta.data['count'], 1)
        self.assertEqual(respuesta.data['results'][0]['id'], self.cliente.pk)

    def test_dni_repetido_al_crear_responde_400(self):
        respuesta = self.api.post(
            '/api/v1/clients/', {'dni': self.cliente.dni, 'name': 'Otro'}, format='json')
        self.assertEqual(respuesta.status_code, 400)


class DocumentacionTests(ApiBase):
    def test_el_esquema_openapi_se_genera(self):
        respuesta = self.api.get('/api/v1/schema/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'/api/v1/transactions/', respuesta.content)

    def test_la_documentacion_pide_autenticacion(self):
        self.assertIn(APIClient().get('/api/v1/docs/').status_code, (401, 403))
