# records/admin.py
from django.contrib import admin
from .models import FinancialRecord, Bank, AccessRequest
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

@admin.register(FinancialRecord)
class FinancialRecordAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'hora', 'comprobante', 'banco_llegada', 'valor', 'cliente', 'vendedor')
    list_filter = ('banco_llegada', 'transaction__status', 'fecha')
    search_fields = ('comprobante', 'cliente', 'vendedor', 'transaction__numero_factura')
    ordering = ('-fecha', '-hora')

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
