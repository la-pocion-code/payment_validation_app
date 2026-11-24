from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..idempotency import DuplicateSubmission
from ..models import (
    Bank, Client, FinancialRecord, OrigenTransaccion, PaymentDocument, Seller,
    Transaction, TransactionType,
)
from . import idempotency
from .filters import ClientApiFilter, ReceiptApiFilter, TransactionApiFilter
from .serializers import (
    BankSerializer, ClientBalanceSerializer, ClientSerializer, ClientUpsertSerializer,
    Conflict, OrigenTransaccionSerializer, PaymentDocumentSerializer,
    ReceiptCreateSerializer, ReceiptSerializer, ReceiptUpdateSerializer, SellerSerializer,
    TransactionCreateSerializer, TransactionSerializer, TransactionTypeSerializer,
    TransactionUpdateSerializer,
)


IDEMPOTENCY_PARAM = OpenApiParameter(
    name=idempotency.HEADER, location=OpenApiParameter.HEADER, required=False, type=str,
    description='UUID propio de este envío. Si reintenta el mismo POST con la misma llave '
                '(por ejemplo, tras un timeout), no se crea un duplicado: recibe el recurso '
                'ya creado con estado 200 y la cabecera `Idempotent-Replayed: true`.',
)


class ReadWriteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       mixins.CreateModelMixin, mixins.UpdateModelMixin,
                       viewsets.GenericViewSet):
    """
    Base de los recursos con escritura.

    - Sin PUT ni DELETE: se crea con POST y se modifica con PATCH. Los borrados
      siguen siendo una acción de la interfaz, con su papelera y su auditoría.
    - La respuesta de POST y PATCH es siempre la representación de lectura.
    - POST acepta `Idempotency-Key`.
    """
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    read_serializer_class = None
    create_serializer_class = None
    update_serializer_class = None
    idempotency_scope = ''
    #: grupos de la app que pueden ejecutar cada acción de escritura con su sesión
    write_groups = {}

    def get_serializer_class(self):
        if self.action == 'create' and self.create_serializer_class:
            return self.create_serializer_class
        if self.action == 'partial_update' and self.update_serializer_class:
            return self.update_serializer_class
        return self.read_serializer_class

    def _read(self, pk, **response_kwargs):
        instance = get_object_or_404(self.get_queryset(), pk=pk)
        data = self.read_serializer_class(instance, context=self.get_serializer_context()).data
        return Response(data, **response_kwargs)

    def _replay(self, pk):
        if pk is None:
            raise Conflict('El envío original con esta llave de idempotencia aún no termina.')
        return self._read(pk, status=status.HTTP_200_OK, headers={'Idempotent-Replayed': 'true'})

    def create(self, request, *args, **kwargs):
        scope = self.idempotency_scope
        # Antes de validar: un reintento chocaría con la detección de duplicados.
        prior = idempotency.previous_result(request, scope)
        if prior is not None:
            return self._replay(prior.result_pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                claimed = idempotency.claim(request, scope)
                instance = serializer.save()
                idempotency.complete(claimed, instance, label=str(instance)[:100])
        except DuplicateSubmission as exc:
            return self._replay(idempotency.result_of(exc.token))
        except IntegrityError:
            # Carrera entre dos envíos distintos con el mismo recibo: la restricción
            # única de la base de datos es la última barrera.
            raise Conflict({
                'code': 'duplicate',
                'detail': 'No se pudo guardar porque el registro ya existe.',
            })
        return self._read(instance.pk, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self._read(instance.pk)


# --------------------------------------------------------------------------- #
# Transacciones
# --------------------------------------------------------------------------- #

@extend_schema_view(
    list=extend_schema(summary='Listar transacciones (ventas) con sus recibos'),
    retrieve=extend_schema(summary='Detalle de una transacción'),
    create=extend_schema(
        summary='Crear una transacción con sus recibos',
        parameters=[IDEMPOTENCY_PARAM],
        request=TransactionCreateSerializer,
        responses={201: TransactionSerializer, 200: TransactionSerializer},
    ),
    partial_update=extend_schema(
        summary='Actualizar estado / factura de una transacción',
        request=TransactionUpdateSerializer, responses=TransactionSerializer,
    ),
)
class TransactionViewSet(ReadWriteViewSet):
    """
    Ventas a facturar. Cada transacción trae sus recibos (pagos), el total recibido,
    la diferencia contra el valor de la venta y `all_receipts_approved`.

    Sincronización: `?updated_since=<fecha ISO>` devuelve lo que cambió desde
    entonces (la transacción o cualquiera de sus recibos);
    `?listas_para_facturar=true` devuelve las pendientes con todos sus pagos aprobados.
    """
    read_serializer_class = TransactionSerializer
    create_serializer_class = TransactionCreateSerializer
    update_serializer_class = TransactionUpdateSerializer
    filterset_class = TransactionApiFilter
    ordering_fields = ['id', 'date', 'updated_at']
    ordering = ['-id']
    idempotency_scope = 'api:transactions'
    write_groups = {
        'create': ('Admin', 'Digitador'),
        'partial_update': ('Admin', 'Facturador'),
    }

    def get_queryset(self):
        return Transaction.objects.select_related(
            'cliente', 'vendedor', 'transaction_type', 'created_by'
        ).prefetch_related(Prefetch(
            'receipts',
            queryset=FinancialRecord.objects.select_related(
                'banco_llegada', 'origen_transaccion', 'cliente', 'uploaded_by'
            ).order_by('id'),
        ))


# --------------------------------------------------------------------------- #
# Recibos
# --------------------------------------------------------------------------- #

@extend_schema_view(
    list=extend_schema(summary='Listar recibos (pagos y abonos)'),
    retrieve=extend_schema(summary='Detalle de un recibo'),
    create=extend_schema(
        summary='Registrar un recibo (abono a cliente o pago de una transacción)',
        parameters=[IDEMPOTENCY_PARAM],
        request=ReceiptCreateSerializer,
        responses={201: ReceiptSerializer, 200: ReceiptSerializer},
    ),
    partial_update=extend_schema(
        summary='Validar un pago / actualizar documento de pago',
        request=ReceiptUpdateSerializer, responses=ReceiptSerializer,
    ),
)
class ReceiptViewSet(ReadWriteViewSet):
    """
    Recibos financieros. Un recibo sin `transaction` es un abono (saldo a favor del
    cliente). Un duplicado responde 409 con el `existing_id` del recibo que ya existe.
    """
    read_serializer_class = ReceiptSerializer
    create_serializer_class = ReceiptCreateSerializer
    update_serializer_class = ReceiptUpdateSerializer
    filterset_class = ReceiptApiFilter
    ordering_fields = ['id', 'fecha', 'modificado']
    ordering = ['-id']
    idempotency_scope = 'api:receipts'
    write_groups = {
        'create': ('Admin', 'Digitador'),
        'partial_update': ('Admin', 'Validador'),
    }

    def get_queryset(self):
        return FinancialRecord.objects.select_related(
            'banco_llegada', 'origen_transaccion', 'cliente', 'transaction__cliente', 'uploaded_by'
        )


# --------------------------------------------------------------------------- #
# Clientes
# --------------------------------------------------------------------------- #

@extend_schema_view(
    list=extend_schema(summary='Listar clientes'),
    retrieve=extend_schema(summary='Detalle de un cliente'),
    create=extend_schema(summary='Crear un cliente', parameters=[IDEMPOTENCY_PARAM]),
    partial_update=extend_schema(summary='Actualizar un cliente'),
)
class ClientViewSet(ReadWriteViewSet):
    read_serializer_class = ClientSerializer
    create_serializer_class = ClientSerializer
    update_serializer_class = ClientSerializer
    queryset = Client.objects.all()
    filterset_class = ClientApiFilter
    ordering_fields = ['id', 'name']
    ordering = ['id']
    idempotency_scope = 'api:clients'
    write_groups = {
        'create': ('Admin', 'Digitador'),
        'partial_update': ('Admin',),
        'upsert': ('Admin', 'Digitador'),
    }

    @extend_schema(
        summary='Crear o actualizar un cliente por su documento (DNI)',
        description='Pensado para sincronizar terceros desde Odoo: si ya existe un cliente '
                    'con ese DNI se actualizan su nombre y su `odoo_id`; si no, se crea.',
        request=ClientUpsertSerializer, responses={200: ClientSerializer, 201: ClientSerializer},
    )
    @action(detail=False, methods=['post'])
    def upsert(self, request):
        serializer = ClientUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        dni = data.pop('dni')
        try:
            client, created = Client.objects.update_or_create(dni=dni, defaults=data)
        except IntegrityError:
            # Dos sincronizaciones simultáneas del mismo tercero: gana la primera.
            client, created = Client.objects.get(dni=dni), False
        return Response(
            ClientSerializer(client).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(summary='Saldo a favor disponible del cliente', responses=ClientBalanceSerializer)
    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        client = self.get_object()
        return Response(ClientBalanceSerializer(
            {'client': client.pk, 'available_balance': client.available_balance}).data)


# --------------------------------------------------------------------------- #
# Catálogos (solo lectura, sin paginar: son listas cortas)
# --------------------------------------------------------------------------- #

class CatalogViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = None
    ordering = ['name']
    ordering_fields = ['id', 'name']


class BankViewSet(CatalogViewSet):
    queryset = Bank.objects.all()
    serializer_class = BankSerializer


class SellerViewSet(CatalogViewSet):
    queryset = Seller.objects.all()
    serializer_class = SellerSerializer


class TransactionTypeViewSet(CatalogViewSet):
    queryset = TransactionType.objects.all()
    serializer_class = TransactionTypeSerializer


class OrigenTransaccionViewSet(CatalogViewSet):
    queryset = OrigenTransaccion.objects.all()
    serializer_class = OrigenTransaccionSerializer


class PaymentDocumentViewSet(CatalogViewSet):
    queryset = PaymentDocument.objects.all()
    serializer_class = PaymentDocumentSerializer
