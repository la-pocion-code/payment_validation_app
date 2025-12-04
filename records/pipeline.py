from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from social_core.exceptions import AuthForbidden
from .models import AuthorizedUser, AccessRequest
from django.contrib.auth.models import Group

def require_email_domain(backend, details, response, *args, **kwargs):
    request = kwargs.get('request')
    email = details.get('email')
    if not email.endswith(('@lapocion.com')):  # eliminar gmail.com despues
        messages.error(request, 'No tienes un correo corporativo de La Poción y no puedes usar nuestra app. Contacta con La Poción si necesitas acceso.')
        return redirect('access_denied')
    # if not details.get('email', '').endswith('@lapocion.com'): # eliminar gmail.com despues
    #     messages.error(kwargs['request'], 'No tienes un correo corporativo de La Poción y no puedes usar nuestra app. Contacta con La Poción si necesitas acceso.')
    #     return redirect('access_denied')

def set_superuser_flag(backend, user, response, details, *args, **kwargs):
    if user:
        # Only promote to superuser/staff if email is in ADMIN_EMAILS.
        # Do not demote users if their email is not in ADMIN_EMAILS,
        # allowing manual superuser assignment to persist.
        if details.get('email') in settings.ADMIN_EMAILS:
            user.is_staff = True
            user.is_superuser = True
            user.save()

def create_access_request(backend, user, is_new, *args, **kwargs):
    if is_new and not user.is_superuser and not user.groups.exists():
        AccessRequest.objects.get_or_create(user=user)



def validate_email_domain(backend, details, response, *args, **kwargs):
    email = details.get('email')
    
    # Verifica que el email no sea vacío y que termine con el dominio permitido
    if not email or not email.endswith(('@lapocion.com')):  # Eliminar '@gmail.com' después
        raise PermissionError("Solo se permiten correos de lapocion.com")
    
    # Verifica que el email esté en la tabla de usuarios autorizados
    if not AuthorizedUser.objects.filter(email__iexact=email).exists():
        raise PermissionError("Este correo no está autorizado")

# def validate_email_domain(backend, details, response, *args, **kwargs):
#     email = details.get('email')
#     if not email or not email.endswith('@lapocion.com'):# eliminar gmail.com despues
#         raise PermissionError("Solo se permiten correos de lapocion.com")

#     if not AuthorizedUser.objects.filter(email__iexact=email).exists():
#         raise PermissionError("Este correo no está autorizado")