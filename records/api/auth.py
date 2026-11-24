"""
Autenticación y permisos de la API REST.

Dos formas de entrar:

1. Integraciones (Odoo, la intranet): cabecera `Authorization: Api-Key <llave>`.
   La llave se crea en el admin o con `manage.py create_api_key`.
2. Usuarios de la app, con su sesión del navegador (la usa la propia interfaz).
"""

import hmac
from datetime import timedelta

from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions, permissions

from ..models import ApiKey
from ..utils import user_group_names

KEYWORD = 'Api-Key'


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate_header(self, request):
        # Hace que una petición sin credenciales responda 401 y no 403.
        return KEYWORD

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode('latin-1').split()
        if not header or header[0].lower() != KEYWORD.lower():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed('Cabecera Authorization mal formada. Use: Api-Key <llave>.')

        raw_key = header[1]
        parts = raw_key.split('_', 2)
        if len(parts) != 3 or parts[0] != 'pv':
            raise exceptions.AuthenticationFailed('Llave de API no válida.')

        api_key = ApiKey.objects.select_related('user').filter(prefix=parts[1]).first()
        if api_key is None or not hmac.compare_digest(api_key.hashed_key, ApiKey.hash_key(raw_key)):
            raise exceptions.AuthenticationFailed('Llave de API no válida.')
        if not api_key.is_active or not api_key.user.is_active:
            raise exceptions.AuthenticationFailed('Esta llave de API está desactivada.')

        # Un UPDATE por minuto como mucho, no uno por petición.
        now = timezone.now()
        if api_key.last_used_at is None or now - api_key.last_used_at > timedelta(minutes=1):
            ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)

        return api_key.user, api_key


class ApiKeyScheme(OpenApiAuthenticationExtension):
    """Describe la llave en la documentación OpenAPI (botón «Authorize»)."""
    target_class = 'records.api.auth.ApiKeyAuthentication'
    name = 'ApiKey'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'Escriba el valor completo: `Api-Key pv_xxxxxxxx_...`',
        }


# Grupos de la app que pueden consultar por API con su sesión.
READ_GROUPS = frozenset({'Admin', 'Digitador', 'Facturador', 'Validador', 'Contabilidad'})


class ApiAccess(permissions.BasePermission):
    """
    - Llave de API: lee siempre; escribe solo si la llave tiene `can_write`.
    - Sesión: lee cualquier usuario con un grupo de la app; escribe según los grupos
      que la vista declare para esa acción en `write_groups` (los mismos roles que
      ya gobiernan la interfaz).
    """
    message = 'No tiene permiso para realizar esta acción.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        api_key = request.auth if isinstance(request.auth, ApiKey) else None
        is_read = request.method in permissions.SAFE_METHODS

        if api_key is not None:
            if is_read or api_key.can_write:
                return True
            self.message = 'Esta llave de API es de solo lectura.'
            return False

        if user.is_superuser:
            return True
        groups = user_group_names(user)
        if is_read:
            return not groups.isdisjoint(READ_GROUPS)
        allowed = getattr(view, 'write_groups', {}).get(getattr(view, 'action', None), ())
        return not groups.isdisjoint(allowed)
