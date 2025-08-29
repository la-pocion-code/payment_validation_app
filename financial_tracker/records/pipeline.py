from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from social_core.exceptions import AuthForbidden

def require_email_domain(backend, details, response, *args, **kwargs):
    if not details.get('email', '').endswith('@lapocion.com'):
        messages.error(kwargs['request'], 'No tienes un correo corporativo de La Poción y no puedes usar nuestra app. Contacta con La Poción si necesitas acceso.')
        return redirect('login')

def set_superuser_flag(backend, user, response, details, *args, **kwargs):
    if user and details.get('email') in settings.ADMIN_EMAILS:
        user.is_staff = True
        user.is_superuser = True
        user.save()
