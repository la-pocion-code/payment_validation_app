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
