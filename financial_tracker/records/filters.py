import django_filters
from .models import FinancialRecord
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
