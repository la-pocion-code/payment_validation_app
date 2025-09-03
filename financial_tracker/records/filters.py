import django_filters
from .models import FinancialRecord, DuplicateRecordAttempt, Bank
from django.contrib.auth.models import User
from django import forms

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
        fields = ['status', 'banco_llegada', 'vendedor', 'facturador']

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
