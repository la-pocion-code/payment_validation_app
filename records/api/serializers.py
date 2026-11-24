from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

from ..models import (
    Bank, Client, DuplicateRecordAttempt, FinancialRecord, OrigenTransaccion,
    PaymentDocument, Seller, Transaction, TransactionType,
)


class Conflict(APIException):
    status_code = 409
    default_detail = 'El recurso ya existe.'
    default_code = 'conflict'


# --------------------------------------------------------------------------- #
# Catálogos
# --------------------------------------------------------------------------- #

class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = ['id', 'name']


class SellerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Seller
        fields = ['id', 'name']


class TransactionTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionType
        fields = ['id', 'name']


class OrigenTransaccionSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrigenTransaccion
        fields = ['id', 'name', 'dias_efectivo']


class PaymentDocumentSerializer(serializers.ModelSerializer):
    prefix = serializers.CharField(source='get_prefix', read_only=True)

    class Meta:
        model = PaymentDocument
        fields = ['id', 'name', 'prefix', 'bank']


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ['id', 'name', 'dni', 'odoo_id']

    def validate_dni(self, value):
        # Misma regla que ClientForm.clean_dni
        value = (value or '').strip()
        if not value or not all(c.isdigit() or c == '-' for c in value):
            raise serializers.ValidationError('El DNI solo puede contener números y guiones (-).')
        return value


class ClientUpsertSerializer(serializers.Serializer):
    """Crea el cliente o lo actualiza si ya existe uno con ese DNI."""
    dni = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=255)
    odoo_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    validate_dni = ClientSerializer.validate_dni


class ClientBalanceSerializer(serializers.Serializer):
    client = serializers.IntegerField()
    available_balance = serializers.DecimalField(max_digits=14, decimal_places=2)


# --------------------------------------------------------------------------- #
# Recibos
# --------------------------------------------------------------------------- #

class ReceiptSerializer(serializers.ModelSerializer):
    banco_llegada = BankSerializer(read_only=True)
    origen_transaccion = OrigenTransaccionSerializer(read_only=True)
    cliente = serializers.SerializerMethodField()
    transaction_uid = serializers.CharField(
        source='transaction.unique_transaction_id', read_only=True, default=None)
    uploaded_by = serializers.CharField(source='uploaded_by.username', read_only=True, default=None)

    class Meta:
        model = FinancialRecord
        fields = [
            'id', 'fecha', 'hora', 'comprobante', 'banco_llegada', 'origen_transaccion',
            'valor', 'payment_status', 'payment_document', 'note', 'description', 'revisado',
            'cliente', 'transaction', 'transaction_uid', 'uploaded_by', 'creado', 'modificado',
        ]

    def get_cliente(self, obj) -> dict | None:
        # Cliente propio (abono) o el de la transacción; ambos vienen precargados.
        client = obj.cliente or (obj.transaction.cliente if obj.transaction_id else None)
        return ClientSerializer(client).data if client else None


def check_receipt_duplicates(attrs, confirm_duplicate=False):
    """
    Misma regla que FinancialRecordForm.clean() en la interfaz:

    - Duplicado EXACTO (fecha, hora, comprobante, banco y valor): siempre 409.
    - Posible duplicado (fecha, hora, banco y valor, con otro comprobante): 409,
      salvo que el envío traiga `confirm_duplicate: true`.

    Devuelve True si se aceptó un posible duplicado confirmado.
    """
    base = dict(fecha=attrs['fecha'], hora=attrs['hora'],
                banco_llegada=attrs['banco_llegada'], valor=attrs['valor'])
    exact = FinancialRecord.objects.filter(comprobante=attrs['comprobante'], **base) \
        .values_list('pk', flat=True).first()
    if exact:
        raise Conflict({
            'code': 'duplicate',
            'detail': 'Registro duplicado exacto: ya existe un recibo con la misma fecha, '
                      'hora, comprobante, banco y valor.',
            'existing_id': exact,
        })
    similar = list(FinancialRecord.objects.filter(**base)
                   .exclude(comprobante=attrs['comprobante']).values_list('pk', flat=True)[:10])
    if similar and not confirm_duplicate:
        raise Conflict({
            'code': 'similar_duplicate',
            'detail': 'Posible duplicado: ya existe un recibo con la misma fecha, hora, banco '
                      'y valor. Si no es un duplicado, reenvíe con "confirm_duplicate": true.',
            'existing_ids': similar,
        })
    return bool(similar)


def log_confirmed_similar(user, attrs):
    """Deja en la bandeja de duplicados el similar que la integración confirmó (ya resuelto)."""
    DuplicateRecordAttempt.objects.create(
        user=user,
        data={k: str(v) for k, v in attrs.items()},
        attempt_type='SIMILAR',
        is_resolved=True,
        resolved_by=user,
        resolved_at=timezone.now(),
    )


class ReceiptWriteBase(serializers.ModelSerializer):
    confirm_duplicate = serializers.BooleanField(write_only=True, required=False, default=False)

    def validate_comprobante(self, value):
        return value.strip()

    def validate_fecha(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError('La fecha del recibo no puede estar en el futuro.')
        return value

    def validate_valor(self, value):
        if value == Decimal('0'):
            raise serializers.ValidationError('El valor no puede ser cero.')
        return value


class NestedReceiptSerializer(ReceiptWriteBase):
    """Recibo dentro de la creación de una transacción."""

    class Meta:
        model = FinancialRecord
        fields = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'origen_transaccion',
                  'valor', 'payment_document', 'note', 'confirm_duplicate']
        # La unicidad la valida check_receipt_duplicates, que responde 409 con el
        # recibo existente en vez del 400 genérico del validador automático.
        validators = []


class ReceiptCreateSerializer(ReceiptWriteBase):
    """Recibo suelto: abono a un cliente (`cliente`) o pago de una transacción (`transaction`)."""

    class Meta:
        model = FinancialRecord
        fields = ['fecha', 'hora', 'comprobante', 'banco_llegada', 'origen_transaccion',
                  'valor', 'cliente', 'transaction', 'payment_document', 'note',
                  'confirm_duplicate']
        validators = []

    def validate(self, attrs):
        if not attrs.get('cliente') and not attrs.get('transaction'):
            raise serializers.ValidationError(
                'Indique "cliente" (abono / saldo a favor) o "transaction" (pago de una transacción).')
        attrs['_similar'] = check_receipt_duplicates(attrs, attrs.pop('confirm_duplicate', False))
        return attrs

    def create(self, validated_data):
        similar = validated_data.pop('_similar', False)
        user = self.context['request'].user
        receipt = FinancialRecord(uploaded_by=user, **validated_data)
        receipt._history_user = user
        receipt.save()
        if similar:
            log_confirmed_similar(user, validated_data)
        return receipt


class ReceiptUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialRecord
        fields = ['payment_status', 'payment_document', 'note', 'revisado']

    def validate(self, attrs):
        # Misma regla de prefijo que aplica la interfaz al Facturador.
        document = (attrs.get('payment_document') or '').strip()
        if document:
            payment_doc = PaymentDocument.objects.filter(bank=self.instance.banco_llegada).first()
            if payment_doc and not document.upper().startswith(payment_doc.get_prefix()):
                raise serializers.ValidationError({
                    'payment_document': f'El documento de pago debe iniciar con "{payment_doc.get_prefix()}".'})
        return attrs

    def update(self, instance, validated_data):
        instance._history_user = self.context['request'].user
        return super().update(instance, validated_data)


# --------------------------------------------------------------------------- #
# Transacciones
# --------------------------------------------------------------------------- #

class TransactionSerializer(serializers.ModelSerializer):
    cliente = ClientSerializer(read_only=True)
    vendedor = SellerSerializer(read_only=True)
    transaction_type = TransactionTypeSerializer(read_only=True)
    created_by = serializers.CharField(source='created_by.username', read_only=True, default=None)
    created_at = serializers.DateTimeField(source='creat_at', read_only=True)
    receipts = ReceiptSerializer(many=True, read_only=True)
    receipts_total = serializers.SerializerMethodField()
    difference = serializers.SerializerMethodField()
    all_receipts_approved = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'unique_transaction_id', 'date', 'cliente', 'vendedor', 'transaction_type',
            'description', 'status', 'numero_factura', 'facturador', 'expected_amount',
            'receipts_total', 'difference', 'all_receipts_approved', 'odoo_id',
            'created_by', 'created_at', 'updated_at', 'receipts',
        ]

    # Se calculan sobre los recibos precargados: sin consultas por fila.
    def _total(self, obj):
        return sum((r.valor for r in obj.receipts.all() if r.valor is not None), Decimal('0.00'))

    def get_receipts_total(self, obj) -> str:
        return str(self._total(obj))

    def get_difference(self, obj) -> str:
        return str(obj.expected_amount - self._total(obj))

    def get_all_receipts_approved(self, obj) -> bool:
        receipts = list(obj.receipts.all())
        return bool(receipts) and all(r.payment_status == 'Aprobado' for r in receipts)


class TransactionCreateSerializer(serializers.ModelSerializer):
    cliente = serializers.PrimaryKeyRelatedField(queryset=Client.objects.all(), required=False)
    cliente_dni = serializers.CharField(write_only=True, required=False)
    receipts = NestedReceiptSerializer(many=True, required=False)

    class Meta:
        model = Transaction
        fields = ['date', 'cliente', 'cliente_dni', 'vendedor', 'transaction_type',
                  'expected_amount', 'description', 'odoo_id', 'receipts']

    def validate_expected_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('El valor de la venta debe ser mayor que cero.')
        return value

    def validate(self, attrs):
        dni = attrs.pop('cliente_dni', None)
        if not attrs.get('cliente'):
            if not dni:
                raise serializers.ValidationError({'cliente': 'Indique "cliente" (id) o "cliente_dni".'})
            attrs['cliente'] = Client.objects.filter(dni=dni.strip()).first()
            if attrs['cliente'] is None:
                raise serializers.ValidationError(
                    {'cliente_dni': f'No existe un cliente con el documento {dni}.'})

        seen = set()
        for receipt in attrs.get('receipts', []):
            key = (receipt['fecha'], receipt['hora'], receipt['comprobante'],
                   receipt['banco_llegada'].pk, receipt['valor'])
            if key in seen:
                raise serializers.ValidationError(
                    {'receipts': 'Hay recibos repetidos dentro del mismo envío.'})
            seen.add(key)
            receipt['_similar'] = check_receipt_duplicates(receipt, receipt.pop('confirm_duplicate', False))
        return attrs

    def create(self, validated_data):
        receipts = validated_data.pop('receipts', [])
        user = self.context['request'].user

        new_transaction = Transaction(created_by=user, **validated_data)
        # Misma regla que TransactionForm.clean(): los fletes no se facturan.
        if new_transaction.transaction_type.name == 'FLETE':
            new_transaction.status = 'No Facturable'
        new_transaction._history_user = user
        new_transaction.save()

        for data in receipts:
            similar = data.pop('_similar', False)
            receipt = FinancialRecord(transaction=new_transaction, uploaded_by=user, **data)
            receipt._history_user = user
            receipt.save()
            if similar:
                log_confirmed_similar(user, data)
        return new_transaction


class TransactionUpdateSerializer(serializers.ModelSerializer):
    """Lo que devuelve quien factura: estado, número de factura y referencia en Odoo."""

    class Meta:
        model = Transaction
        fields = ['status', 'numero_factura', 'facturador', 'description', 'odoo_id']

    def validate(self, attrs):
        status = attrs.get('status', self.instance.status)
        numero = attrs.get('numero_factura', self.instance.numero_factura)
        if 'status' in attrs and status == 'Facturado' and not numero:
            raise serializers.ValidationError(
                {'numero_factura': 'Para marcar la transacción como Facturado indique el número de factura.'})
        return attrs

    def update(self, instance, validated_data):
        user = self.context['request'].user
        billed = validated_data.get('status') == 'Facturado' and instance.status != 'Facturado'
        invoiced = validated_data.get('numero_factura') and \
            validated_data['numero_factura'] != instance.numero_factura
        # Igual que la interfaz: quien factura queda como facturador, salvo que se envíe otro.
        if (billed or invoiced) and 'facturador' not in validated_data:
            validated_data['facturador'] = user.username[:100]
        instance._history_user = user
        return super().update(instance, validated_data)
