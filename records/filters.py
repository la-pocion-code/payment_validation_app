import django_filters
from .models import FinancialRecord, DuplicateRecordAttempt, Bank, Transaction, Client, OrigenTransaccion
from django.contrib.auth.models import User
from django import forms
from django.db.models import Q


class FinancialRecordFilter(django_filters.FilterSet):
    creado__gte = django_filters.DateFilter(
        field_name='creado',
        lookup_expr='gte',
        label='Creado desde',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    creado__lte = django_filters.DateFilter(
        field_name='creado',
        lookup_expr='lte',
        label='Creado hasta',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    modificado__gte = django_filters.DateFilter(
        field_name='modificado',
        lookup_expr='gte',
        label='Modificado desde',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    modificado__lte = django_filters.DateFilter(
        field_name='modificado',
        lookup_expr='lte',
        label='Modificado hasta',
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    class Meta:
        model = FinancialRecord
        fields = ['transaction__status', 'banco_llegada', 'transaction__vendedor', 'transaction__facturador', 'transaction__cliente']


class DuplicateRecordAttemptFilter(django_filters.FilterSet):
    timestamp__gte = django_filters.DateFilter(
        field_name='timestamp',
        lookup_expr='gte',
        label='Desde',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    timestamp__lte = django_filters.DateFilter(
        field_name='timestamp',
        lookup_expr='lte',
        label='Hasta',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    user = django_filters.ModelChoiceFilter(
        queryset=User.objects.all(),
        label='Usuario'
    )
    banco = django_filters.CharFilter(
        field_name='data__banco_llegada',
        lookup_expr='icontains',
        label='Banco'
    )

    class Meta:
        model = DuplicateRecordAttempt
        fields = ['user', 'timestamp__gte', 'timestamp__lte', 'banco']

class TransactionFilter(django_filters.FilterSet):
    id = django_filters.NumberFilter(
        field_name='unique_transaction_id',
        lookup_expr='icontains',
        label='ID Transacción'
    )
    date__gte = django_filters.DateFilter(
        field_name='date',
        lookup_expr='gte',
        label='Fecha desde',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    date__lte = django_filters.DateFilter(
        field_name='date',
        lookup_expr='lte',
        label='Fecha hasta',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    cliente = django_filters.CharFilter(
        method='filter_by_client_name_or_dni',
        label='Cliente (Nombre o ID)'
    )

    def filter_by_client_name_or_dni(self, queryset, name, value):
        return queryset.filter(
            Q(cliente__name__icontains=value) | Q(cliente__dni__icontains=value)
        ).distinct()

    vendedor = django_filters.CharFilter(
        field_name='vendedor__name',
        lookup_expr='icontains',
        label='Vendedor'
    )
    facturador = django_filters.CharFilter(
        field_name='facturador',
        lookup_expr='icontains',
        label='Facturador'
    )
    numero_factura = django_filters.CharFilter(
        field_name='numero_factura',
        lookup_expr='icontains',
        label='# de Factura'
    )
    status = django_filters.ChoiceFilter(
        choices=Transaction.STATUS_CHOICES,
        label='Estado'
    )
    valor = django_filters.NumberFilter(
        field_name='expected_amount',
        lookup_expr='icontains',
        label='Valor'
    )
    # --- INICIO: Nuevo filtro para estado de recibos ---
    receipt_status = django_filters.ChoiceFilter(
        choices=FinancialRecord.APROVED_CHOICES,
        label='Estado Recibos',
        method='filter_receipt_status'
    )

    def filter_receipt_status(self, queryset, name, value):
        # If the value is 'Aprobado', we want transactions where ALL receipts are approved.
        if value == 'Aprobado':
            # We exclude transactions that have pending or rejected receipts.
            # Additionally, we ensure that the transaction has at least one receipt.
            return queryset.filter(receipts__isnull=False).exclude(
                Q(receipts__payment_status='Pendiente') | Q(receipts__payment_status='Rechazado')
            ).distinct()
        
        # For other statuses like 'Pendiente' or 'Rechazado', the default behavior is sufficient:
        # show transactions that have AT LEAST ONE receipt with that status.
        elif value in [choice[0] for choice in FinancialRecord.APROVED_CHOICES if choice[0] != 'Aprobado']:
            return queryset.filter(receipts__payment_status=value).distinct()

        # If no value is selected, return the queryset without changes.
        return queryset
    
    origen_transaccion = django_filters.ModelChoiceFilter(
        field_name='receipts__origen_transaccion',
        queryset=OrigenTransaccion.objects.all(),
        label='Origen Transacción'
    )

    class Meta:
        model = Transaction
        fields = ['unique_transaction_id', 'date__gte', 
                  'date__lte', 'cliente', 'vendedor', 'facturador', 'numero_factura', 'status',
                    'valor','transaction_type', 'receipt_status', 'origen_transaccion']



class CreditFilter(django_filters.FilterSet):
    fecha__gte = django_filters.DateFilter(
        field_name='fecha',
        lookup_expr='gte',
        label='Fecha Desde',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    fecha__lte = django_filters.DateFilter(
        field_name='fecha',
        lookup_expr='lte',
        label='Fecha Hasta',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    comprobante = django_filters.CharFilter(
        field_name='comprobante',
        lookup_expr='icontains',
        label='Comprobante',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '# Comprobante'})
    )
    banco_llegada = django_filters.ModelChoiceFilter(
        queryset=Bank.objects.all(),
        label='Banco',
        widget=forms.Select(attrs={'class': 'form-select'}) # 'form-select' es mejor para Bootstrap 5
    )
    payment_status = django_filters.ChoiceFilter(
        choices=FinancialRecord.APROVED_CHOICES,
        label='Estado',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    # Filtro personalizado para buscar por el cliente mostrado (directo o a través de la transacción)
    display_client = django_filters.CharFilter(
        method='filter_by_client',
        label='Cliente',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre o DNI del cliente...'})
    )

    valor = django_filters.NumberFilter(
        field_name='valor',
        lookup_expr='icontains', # 'exact' es mejor para números que 'icontains'
        label='Valor',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Valor del recibo...'})
    )

    uploaded_by = django_filters.ModelChoiceFilter(
        queryset=User.objects.all(),
        field_name='uploaded_by',
        label='Subido por',
        widget=forms.Select(attrs={'class': 'form-select'})
    )


    def filter_by_client(self, queryset, name, value):
        """
        Este método personalizado filtra el queryset de FinancialRecord
        buscando el 'value' (nombre o DNI del cliente) en dos lugares:
        1. En el campo 'cliente' del propio recibo (para abonos).
        2. En el campo 'cliente' de la transacción asociada al recibo.
        """
        return queryset.filter(
            Q(cliente__name__icontains=value) | Q(cliente__dni__icontains=value) |
            Q(transaction__cliente__name__icontains=value) | Q(transaction__cliente__dni__icontains=value)
        ).distinct()

    vendedor = django_filters.CharFilter(
        field_name='transaction__vendedor__name',
        lookup_expr='icontains',
        label='Vendedor',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del vendedor...'})
    )

    facturador = django_filters.CharFilter(
        field_name='transaction__facturador', 
        lookup_expr='icontains',
        label='Facturador',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del facturador...'})
    )

    class Meta:
        model = FinancialRecord
        fields = ['fecha__gte', 'fecha__lte', 'comprobante', 'banco_llegada', 'payment_status', 
                  'display_client', 'valor', 'uploaded_by', 'vendedor', 'facturador']


class ClientFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        field_name='name',
        lookup_expr='icontains',
        label='Nombre',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Buscar por nombre...'})
    )
    dni = django_filters.CharFilter(
        field_name='dni',
        lookup_expr='icontains',
        label='Documento',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Buscar por documento...'})
    )

    class Meta:
        model = Client
        fields = ['name', 'dni']