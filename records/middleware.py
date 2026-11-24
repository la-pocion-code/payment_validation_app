import logging

from social_core.exceptions import (
    AuthCanceled, AuthMissingParameter, AuthStateForbidden, AuthStateMissing,
)
from social_django.middleware import SocialAuthExceptionMiddleware

logger = logging.getLogger(__name__)


class SocialAuthErrorsMiddleware(SocialAuthExceptionMiddleware):
    """
    Convierte los errores del login con Google en un aviso y un redirect al login.

    El caso de todos los días es AuthStateMissing: la sesión (1 hora) vence entre
    abrir la pantalla de login y volver de Google, o se vuelve con el botón Atrás o
    desde una pestaña vieja. Sin este middleware eso terminaba en un error 500.
    """

    def raise_exception(self, request, exception):
        # Siempre se maneja, también con DEBUG=True.
        return False

    def get_message(self, request, exception):
        if isinstance(exception, (AuthStateMissing, AuthStateForbidden, AuthMissingParameter)):
            return 'El inicio de sesión expiró. Por favor, intenta de nuevo.'
        if isinstance(exception, AuthCanceled):
            return 'Cancelaste el inicio de sesión con Google.'
        logger.warning('Error de autenticación social: %s', exception)
        return 'No se pudo iniciar sesión con Google. Por favor, intenta de nuevo.'


class ProtectedDeleteMiddleware:
    """
    Eliminar algo que ya está en uso (un banco con recibos, un vendedor con ventas) lanza
    ProtectedError. Varias vistas de catálogo no lo capturaban y respondían 500; aquí se
    convierte en un mensaje claro, en JSON para la ventana de catálogos o como aviso.
    """
    MESSAGE = 'No se puede eliminar porque ya está en uso en recibos o transacciones.'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from django.contrib import messages
        from django.db.models.deletion import ProtectedError
        from django.http import JsonResponse
        from django.shortcuts import redirect

        if not isinstance(exception, ProtectedError):
            return None
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': self.MESSAGE}, status=400)
        messages.error(request, self.MESSAGE)
        return redirect(request.META.get('HTTP_REFERER') or '/')


class RoleRequiredMiddleware:
    """
    Sin rol no se ve nada.

    Todo usuario con sesión debe tener al menos un rol (grupo) o ser administrador. Quien
    no lo tiene —recién llegado, o alguien a quien se le quitaron los roles— solo puede ver
    la pantalla de «acceso pendiente» y cerrar sesión, y queda en la lista de solicitudes
    de «Usuarios» para que un administrador le asigne el rol.

    Antes cada vista decidía por su cuenta, y algunas no pedían rol (exportar recibos,
    abrir una transacción por su dirección, autocompletados).
    """
    OPEN_URL_NAMES = {'login', 'logout', 'request_access', 'access_denied'}
    OPEN_PREFIXES = ('/social/', '/static/', '/admin/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.http import JsonResponse
        from django.shortcuts import redirect

        from .models import AccessRequest
        from .utils import user_group_names

        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated or user.is_superuser:
            return None
        if request.path.startswith(self.OPEN_PREFIXES):
            return None
        match = request.resolver_match
        if match is not None and match.url_name in self.OPEN_URL_NAMES and not match.namespace:
            return None
        if user_group_names(user):
            return None

        # Que aparezca como pendiente en «Usuarios», aunque su solicitud original ya no exista.
        access_request, _ = AccessRequest.objects.get_or_create(user=user)
        if access_request.approved:
            access_request.approved = False
            access_request.save(update_fields=['approved'])

        wants_json = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
                      or request.path.startswith('/api/'))
        if wants_json:
            return JsonResponse(
                {'success': False, 'message': 'Tu usuario aún no tiene un rol asignado.'}, status=403)
        return redirect('request_access')
