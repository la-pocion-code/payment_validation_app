import django_filters
from .models import FinancialRecord, DuplicateRecordAttempt, Bank, Transaction
from django.contrib.auth.models import User
from django import forms

class FinancialRecordFilter(django_filters.FilterSet):
    cliente = django_filters.CharFilter(lookup_expr='icontains', label='Cliente')
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
        fields = ['transaction__status', 'banco_llegada', 'vendedor', 'transaction__facturador', 'cliente']

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
        field_name='cliente',
        lookup_expr='icontains',
        label='Cliente'
    )
    vendedor = django_filters.CharFilter(
        field_name='vendedor',
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

    class Meta:
        model = Transaction
        fields = ['date__gte', 'date__lte', 'cliente', 'vendedor', 'facturador', 'numero_factura', 'status']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'status' not in self.data:
            self.data = self.data.copy()
            self.data['status'] = 'Pendiente'
