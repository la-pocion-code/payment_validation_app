import django_filters
from django.db.models import Q

from ..models import Client, FinancialRecord, Transaction


class TransactionApiFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Transaction.STATUS_CHOICES)
    date_from = django_filters.DateFilter(field_name='date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='date', lookup_expr='lte')
    cliente = django_filters.NumberFilter(field_name='cliente_id')
    cliente_dni = django_filters.CharFilter(field_name='cliente__dni')
    vendedor = django_filters.NumberFilter(field_name='vendedor_id')
    transaction_type = django_filters.NumberFilter(field_name='transaction_type_id')
    numero_factura = django_filters.CharFilter()
    unique_transaction_id = django_filters.CharFilter()
    odoo_id = django_filters.NumberFilter()
    sin_factura = django_filters.BooleanFilter(method='filter_sin_factura')
    receipt_status = django_filters.ChoiceFilter(
        choices=FinancialRecord.APROVED_CHOICES, method='filter_receipt_status')
    listas_para_facturar = django_filters.BooleanFilter(method='filter_listas')
    updated_since = django_filters.IsoDateTimeFilter(method='filter_updated_since')

    class Meta:
        model = Transaction
        fields = []

    def filter_sin_factura(self, queryset, name, value):
        vacia = Q(numero_factura__isnull=True) | Q(numero_factura='')
        return queryset.filter(vacia) if value else queryset.exclude(vacia)

    def filter_receipt_status(self, queryset, name, value):
        return queryset.filter(receipts__payment_status=value).distinct()

    def filter_listas(self, queryset, name, value):
        """Pendientes con al menos un recibo y todos sus recibos aprobados."""
        listas = Q(status='Pendiente', receipts__isnull=False) & ~Q(
            pk__in=FinancialRecord.objects.filter(transaction__isnull=False)
            .exclude(payment_status='Aprobado').values('transaction_id')
        )
        return queryset.filter(listas).distinct() if value else queryset.exclude(listas).distinct()

    def filter_updated_since(self, queryset, name, value):
        # Una transacción «cambió» si cambió ella o cualquiera de sus recibos
        # (p. ej. el validador aprobó un pago).
        return queryset.filter(
            Q(updated_at__gte=value) | Q(receipts__modificado__gte=value)
        ).distinct()


class ReceiptApiFilter(django_filters.FilterSet):
    payment_status = django_filters.ChoiceFilter(choices=FinancialRecord.APROVED_CHOICES)
    fecha_from = django_filters.DateFilter(field_name='fecha', lookup_expr='gte')
    fecha_to = django_filters.DateFilter(field_name='fecha', lookup_expr='lte')
    comprobante = django_filters.CharFilter()
    banco_llegada = django_filters.NumberFilter(field_name='banco_llegada_id')
    cliente = django_filters.NumberFilter(method='filter_cliente')
    transaction = django_filters.NumberFilter(field_name='transaction_id')
    sin_transaccion = django_filters.BooleanFilter(field_name='transaction', lookup_expr='isnull')
    revisado = django_filters.BooleanFilter()
    updated_since = django_filters.IsoDateTimeFilter(field_name='modificado', lookup_expr='gte')

    class Meta:
        model = FinancialRecord
        fields = []

    def filter_cliente(self, queryset, name, value):
        # El cliente de un recibo es el suyo propio (abono) o el de su transacción.
        return queryset.filter(Q(cliente_id=value) | Q(transaction__cliente_id=value))


class ClientApiFilter(django_filters.FilterSet):
    dni = django_filters.CharFilter()
    name = django_filters.CharFilter(lookup_expr='icontains')
    odoo_id = django_filters.NumberFilter()
    sin_odoo_id = django_filters.BooleanFilter(field_name='odoo_id', lookup_expr='isnull')

    class Meta:
        model = Client
        fields = []
