# records/admin.py
from django.contrib import admin
from .models import (
    FinancialRecord, Bank, AccessRequest, Seller, OrigenTransaccion, Client,
    Transaction, TransactionType, DuplicateRecordAttempt, AuthorizedUser
)
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin


@admin.register(FinancialRecord)
class FinancialRecordAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'hora', 'comprobante', 'banco_llegada', 'valor','transaction__cliente', 'transaction__vendedor', 'transaction__numero_factura')
    list_filter = ('banco_llegada', 'transaction__status', 'fecha')
    search_fields = ('comprobante', 'transaction__cliente', 'transaction__vendedor', 'transaction__numero_factura')
    ordering = ('-fecha', '-hora')

@admin.register(OrigenTransaccion)
class OrigenTransaccionAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'approved', 'timestamp')
    list_filter = ('approved',)
    list_display_links = ('user',)

# Unregister the provided model admin
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_groups')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    readonly_fields = ('last_login', 'date_joined')

    def get_groups(self, obj):
        return ", ".join([g.name for g in obj.groups.all()])
    get_groups.short_description = 'Groups'

admin.site.register(Group)

@admin.register(Seller)
class sellerAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    ordering = ('name',)

class DniContainsFilter(admin.SimpleListFilter):
    title = 'DNI contiene caracteres inválidos'
    parameter_name = 'dni_invalid'

    def lookups(self, request, model_admin):
        return (
            ('letters', 'Contiene letras'),
            ('spaces', 'Contiene espacios'),
            ('special', 'Contiene caracteres especiales'),
            ('valid', 'Solo números y guiones (válido)'),
            ('any_invalid', 'Cualquier carácter inválido'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'letters':
            # DNI que contiene letras (a-z, A-Z)
            return queryset.filter(dni__regex=r'[a-zA-Z]')
        
        if self.value() == 'spaces':
            # DNI que contiene espacios
            return queryset.filter(dni__contains=' ')
        
        if self.value() == 'special':
            # DNI que contiene caracteres especiales (que no sean números, guiones o espacios)
            return queryset.exclude(dni__regex=r'^[0-9\s-]+$')
        
        if self.value() == 'valid':
            # DNI válido: solo números y guiones
            return queryset.filter(dni__regex=r'^[0-9-]+$')
        
        if self.value() == 'any_invalid':
            # DNI con cualquier carácter inválido (no números ni guiones)
            return queryset.exclude(dni__regex=r'^[0-9-]+$')
        
        return queryset


class DniSearchFilter(admin.SimpleListFilter):
    title = 'Buscar patrón en DNI'
    parameter_name = 'dni_pattern'

    def lookups(self, request, model_admin):
        # Puedes personalizar esto con patrones comunes que encuentres
        return (
            ('a', 'Contiene "a"'),
            ('e', 'Contiene "e"'),
            ('o', 'Contiene "o"'),
            ('x', 'Contiene "x"'),
            ('.', 'Contiene "."'),
            (',', 'Contiene ","'),
        )

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(dni__icontains=self.value())
        return queryset


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'dni', 'available_balance', 'dni_is_valid')
    search_fields = ('name', 'dni')
    ordering = ('name',)
    list_filter = (DniContainsFilter, DniSearchFilter)
    
    # Método personalizado para mostrar si el DNI es válido
    @admin.display(boolean=True, description='DNI Válido')
    def dni_is_valid(self, obj):
        """Muestra un check verde si el DNI solo tiene números y guiones"""
        import re
        return bool(re.match(r'^[0-9-]+$', obj.dni))
    
    # Opcional: Acciones masivas para limpiar DNI
    actions = ['clean_dni_action']
    
    @admin.action(description='Limpiar DNI seleccionados (remover caracteres inválidos)')
    def clean_dni_action(self, request, queryset):
        import re
        updated = 0
        for client in queryset:
            original_dni = client.dni
            clean_dni = re.sub(r'[^0-9-]', '', original_dni)
            if original_dni != clean_dni:
                client.dni = clean_dni
                client.save(update_fields=['dni'])
                updated += 1
        
        self.message_user(
            request,
            f'{updated} DNI(s) limpiados correctamente.',
            level='success' if updated > 0 else 'info'
        )

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('unique_transaction_id', 'date', 'cliente', 'vendedor', 'transaction_type', 'status', 'expected_amount', 'receipts_total', 'difference')
    list_filter = ('status', 'date', 'vendedor', 'transaction_type')
    search_fields = ('unique_transaction_id', 'cliente__name', 'cliente__dni', 'vendedor__name', 'numero_factura')
    ordering = ('-date',)
    readonly_fields = ('unique_transaction_id', 'receipts_total', 'difference', 'creat_at')

@admin.register(TransactionType)
class TransactionTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(DuplicateRecordAttempt)
class DuplicateRecordAttemptAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'attempt_type', 'is_resolved', 'resolved_by', 'resolved_at')
    list_filter = ('is_resolved', 'attempt_type', 'timestamp')
    search_fields = ('user__username',)
    readonly_fields = ('timestamp', 'user', 'data', 'resolved_by', 'resolved_at')

@admin.register(AuthorizedUser)
class AuthorizedUserAdmin(admin.ModelAdmin):
    list_display = ('email',)
    search_fields = ('email',)
