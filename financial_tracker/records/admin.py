# records/admin.py
from django.contrib import admin
from .models import FinancialRecord

@admin.register(FinancialRecord)
class FinancialRecordAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'hora', 'comprobante', 'banco_llegada', 'valor', 'cliente', 'vendedor')
    list_filter = ('banco_llegada', 'status', 'fecha')
    search_fields = ('comprobante', 'cliente', 'vendedor', 'numero_factura')
    ordering = ('-fecha', '-hora')