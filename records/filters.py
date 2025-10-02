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
    # Filter by client of the associated FinancialRecords
    cliente = django_filters.CharFilter(
        field_name='receipts__cliente',
        lookup_expr='icontains',
        label='Cliente'
    )
    # Filter by status of the associated FinancialRecords
    status = django_filters.ChoiceFilter(
        choices=Transaction.STATUS_CHOICES,
        label='Estado'
    )
    # Filter by bank of the associated FinancialRecords
    banco_llegada = django_filters.ModelChoiceFilter(
        field_name='receipts__banco_llegada',
        queryset=Bank.objects.all(),
        label='Banco Llegada'
    )
    # Filter by date of the transaction
    date__gte = django_filters.DateFilter(
        field_name='date',
        lookup_expr='gte',
        label='Fecha desde',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    date__lte = django_filters.DateFilter(
        field_name='date',
        lookup_expr='lte',
        label='Fecha hasta',
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    class Meta:
        model = Transaction
        fields = ['cliente', 'status', 'banco_llegada', 'date__gte', 'date__lte']
