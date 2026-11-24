"""
Avisos por correo cuando se registra un intento de duplicado.

Quién recibe y qué dice cada aviso lo decide un administrador en «Alertas por correo»
(modelo DuplicateAlertTemplate): una plantilla para el duplicado exacto (bloqueado) y otra
para el posible duplicado que el digitador confirmó.

El disparo es la señal post_save de DuplicateRecordAttempt (ver apps.py), así que cubre
todas las vías: formularios, carga y API. Como la llave de idempotencia ya filtra los
reenvíos por red inestable, solo llegan aquí los intentos reales.

El correo sale en un hilo aparte y después del commit: un servidor de correo lento o caído
nunca frena ni rompe el guardado de un digitador.
"""
import logging
import re
import threading
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .correo import crear_mensaje

logger = logging.getLogger(__name__)

#: Variables que se pueden usar en el asunto y en el mensaje, con su explicación.
VARIABLES = [
    ('usuario', 'Quién hizo el intento'),
    ('fecha_intento', 'Cuándo ocurrió'),
    ('comprobante', 'Número de comprobante'),
    ('fecha', 'Fecha del pago'),
    ('hora', 'Hora del pago'),
    ('banco', 'Banco de llegada'),
    ('valor', 'Valor del recibo'),
    ('enlace_recibo', 'Enlace al recibo que ya existía (solo duplicado exacto)'),
    ('enlace_bandeja', 'Enlace a la bandeja de duplicados'),
]

DEFAULTS = {
    'DUPLICATE': {
        'subject': 'Intento de recibo duplicado: {comprobante}',
        'body': (
            'Hola,\n\n'
            '{usuario} intentó registrar un recibo que ya existe en Validación de Pagos. '
            'El sistema lo bloqueó: no se guardó nada nuevo.\n\n'
            'Comprobante: {comprobante}\n'
            'Fecha y hora del pago: {fecha} {hora}\n'
            'Banco: {banco}\n'
            'Valor: {valor}\n'
            'Intento registrado: {fecha_intento}\n\n'
            'Ver el recibo que ya existía: {enlace_recibo}\n\n'
            'Revisar la bandeja de duplicados: {enlace_bandeja}\n'
        ),
    },
    'SIMILAR': {
        'subject': 'Posible duplicado confirmado: {comprobante}',
        'body': (
            'Hola,\n\n'
            '{usuario} guardó un recibo que coincide en fecha, hora, banco y valor con otro '
            'que ya estaba registrado, y confirmó que no es un duplicado. '
            'Vale la pena darle una mirada.\n\n'
            'Comprobante: {comprobante}\n'
            'Fecha y hora del pago: {fecha} {hora}\n'
            'Banco: {banco}\n'
            'Valor: {valor}\n'
            'Guardado: {fecha_intento}\n\n'
            'Revisar la bandeja de duplicados: {enlace_bandeja}\n'
        ),
    },
}

SAMPLE = {
    'usuario': 'digitador.ejemplo',
    'fecha_intento': '24/11/2026 10:32',
    'comprobante': 'M03202292',
    'fecha': '23/11/2026',
    'hora': '10:15:00',
    'banco': 'BANCOLOMBIA',
    'valor': '$500.000',
}

_VARIABLE = re.compile(r'\{(\w+)\}')


def site_url():
    return (getattr(settings, 'SITE_URL', '') or '').rstrip('/')


def smtp_ready():
    """¿Este entorno entrega correo de verdad? (Sin SMTP el correo solo queda en el log.)"""
    return settings.EMAIL_BACKEND.endswith('smtp.EmailBackend') and bool(settings.EMAIL_HOST_USER)


def _absolute(path):
    base = site_url()
    return f'{base}{path}' if base else ''


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return str(value or '')
    text = f'{amount:,.2f}'.replace(',', '§').replace('.', ',').replace('§', '.')
    return '$' + (text[:-3] if text.endswith(',00') else text)


def _date(value):
    parts = str(value or '').split('-')
    return f'{parts[2]}/{parts[1]}/{parts[0]}' if len(parts) == 3 else str(value or '')


def context_for(attempt):
    """Los valores de las variables para un DuplicateRecordAttempt."""
    data = attempt.data or {}
    existing = data.get('_registro_existente_pk')
    return {
        'usuario': attempt.user.get_full_name() or attempt.user.username,
        'fecha_intento': timezone.localtime(attempt.timestamp).strftime('%d/%m/%Y %H:%M'),
        'comprobante': data.get('comprobante') or 'sin comprobante',
        'fecha': _date(data.get('fecha')),
        'hora': str(data.get('hora') or ''),
        'banco': str(data.get('banco_llegada') or ''),
        'valor': _money(data.get('valor')),
        'enlace_recibo': _absolute(reverse('credit_detail', args=[existing])) if existing else '',
        'enlace_bandeja': _absolute(reverse('duplicate_attempts_list')),
    }


def sample_context():
    context = dict(SAMPLE)
    context['enlace_recibo'] = _absolute(reverse('credit_list')) or 'https://ejemplo.lapocion.com/credits/1/'
    context['enlace_bandeja'] = _absolute(reverse('duplicate_attempts_list')) or 'https://ejemplo.lapocion.com/duplicates/'
    return context


def render(text, context):
    """
    Sustituye {variable}. Una variable desconocida se deja tal cual (no rompe el envío) y
    la línea cuyo enlace quedó vacío se omite, para no dejar «Ver el recibo: » colgando.
    """
    lines = []
    for line in (text or '').replace('\r\n', '\n').split('\n'):
        names = _VARIABLE.findall(line)
        if any(name.startswith('enlace_') and not context.get(name) for name in names):
            continue
        lines.append(_VARIABLE.sub(lambda m: str(context.get(m.group(1), m.group(0))), line))
    return '\n'.join(lines)


def build_message(template, context, to=None):
    subject = ' '.join(render(template.subject, context).split())
    return crear_mensaje(
        subject, render(template.body, context),
        para=to if to is not None else template.recipient_list(),
        cc=[] if to is not None else template.cc_list(),
        remitente=settings.DEFAULT_FROM_EMAIL,
    )


def _send(message, what):
    try:
        message.send(fail_silently=False)
    except Exception:
        # Queda en el log (nivel ERROR) y el intento sigue en la bandeja: nada se pierde.
        logger.exception('No se pudo enviar el aviso por correo de %s', what)


def dispatch(message, what):
    if getattr(settings, 'DUPLICATE_ALERTS_ASYNC', True):
        # No es daemon: si el worker se recicla, espera a que el correo salga.
        threading.Thread(target=_send, args=(message, what), daemon=False).start()
    else:
        _send(message, what)


def notify_duplicate_attempt(attempt):
    """Envía el aviso del intento si su plantilla está activa y tiene destinatarios."""
    from .models import DuplicateAlertTemplate

    template = DuplicateAlertTemplate.objects.filter(key=attempt.attempt_type, is_active=True).first()
    if template is None or not template.recipient_list():
        return False
    dispatch(build_message(template, context_for(attempt)), f'intento {attempt.pk}')
    return True


def on_attempt_saved(sender, instance, created, **kwargs):
    """Receptor de post_save: avisa una sola vez, al crearse, y después del commit."""
    if not created:
        return

    def after_commit():
        try:
            notify_duplicate_attempt(instance)
        except Exception:
            logger.exception('Falló el aviso por correo del intento %s', instance.pk)

    transaction.on_commit(after_commit)
