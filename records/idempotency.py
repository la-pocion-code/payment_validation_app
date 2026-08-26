"""
Llave de idempotencia para envíos de formulario.

Los digitadores trabajan con red inestable, así que un mismo POST puede llegar dos
veces: doble clic, F5 -> "reenviar formulario", o reintento del navegador/proxy
cuando la conexión persistente se cae antes de recibir la respuesta. Sin protección,
el segundo POST choca con la validación de duplicados y muestra un error rojo aunque
el registro sí se guardó, lo que llevaba al digitador a re-digitar cambiando la hora
y crear un duplicado real.

Uso en una vista (ver records/views.py para los cuatro puntos de entrada):

    # 1) FASE 1 - al inicio del POST, ANTES de instanciar los formularios
    prior = already_submitted(request)
    if prior is not None:
        return duplicate_response(request, prior.token, noun='registro')

    ...validación...

    # 2) FASE 2 - primera sentencia dentro del atomic que hace la escritura
    try:
        with transaction.atomic():
            claim = claim_submission(request, 'mi_vista')
            ...guardado...
            complete_submission(claim, result_url=..., result_pk=..., result_label=...)
    except DuplicateSubmission as exc:
        return duplicate_response(request, exc, noun='registro')

El orden importa: la fase 1 va antes de instanciar los formularios porque
FinancialRecordForm.clean() tiene efectos secundarios de escritura (registra
DuplicateRecordAttempt), y basta acceder a form.errors para dispararlos.
"""

import logging
import uuid

from django.contrib import messages
from django.db import IntegrityError
from django.db.models import F
from django.shortcuts import redirect
from django.urls import reverse

from .models import FormSubmission

logger = logging.getLogger(__name__)

# Nombre del campo oculto que emite el template tag {% submit_token %}.
SUBMIT_TOKEN_FIELD = 'submit_token'


class DuplicateSubmission(Exception):
    """El POST trae un token ya consumido: es un reenvío, no un envío nuevo."""

    def __init__(self, token):
        self.token = token
        super().__init__(str(token))


def posted_token(request):
    """
    UUID válido presente en el POST, o None.

    Devuelve None cuando el formulario es viejo (página en caché sin el campo) o la
    petición viene fuera del flujo normal. En ese caso las vistas se comportan como
    antes: degradación con gracia, sin protección de idempotencia.
    """
    raw = (request.POST.get(SUBMIT_TOKEN_FIELD) or '').strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


def already_submitted(request):
    """
    FASE 1: chequeo de solo lectura al inicio del POST.

    Cubre el caso secuencial, que es el más frecuente: doble clic con pausa, F5, o
    reintento del navegador después de que el POST original ya hizo commit.
    Devuelve el FormSubmission previo, o None si este envío es nuevo.
    """
    token = posted_token(request)
    if token is None:
        return None
    prior = FormSubmission.objects.filter(pk=token).first()
    if prior is not None:
        # Traza medible de cuántos reenvíos absorbió el sistema.
        FormSubmission.objects.filter(pk=token).update(retry_count=F('retry_count') + 1)
    return prior


def claim_submission(request, scope):
    """
    FASE 2: consumo autoritativo del token. Debe ser la PRIMERA sentencia dentro del
    transaction.atomic() que hace la escritura.

    La carrera la resuelve la base de datos: en PostgreSQL el INSERT de una PK
    duplicada ESPERA a que la transacción rival haga commit o rollback.
      - commit   -> violación de unicidad -> DuplicateSubmission -> redirect
      - rollback -> el INSERT pasa -> este POST hace el trabajo
    Determinista en ambas ramas, sin ventana de carrera y sin polling.

    Devuelve None si el POST no trae token (degradación con gracia).
    """
    token = posted_token(request)
    if token is None:
        logger.info(
            "POST sin token de idempotencia en %s (usuario=%s)",
            scope, getattr(request.user, 'username', None)
        )
        return None
    try:
        return FormSubmission.objects.create(
            token=token,
            user=request.user if request.user.is_authenticated else None,
            scope=scope,
        )
    except IntegrityError as exc:
        # OJO: tras el IntegrityError la transacción externa queda inservible, así
        # que aquí NO se puede consultar nada. La excepción lleva solo el token y el
        # SELECT lo hace duplicate_response(), ya fuera del atomic.
        raise DuplicateSubmission(token) from exc


def complete_submission(claim, *, result_url, result_pk=None, result_label=''):
    """
    Guarda el destino al que hay que redirigir un reenvío posterior. Se llama al
    final del guardado, DENTRO del mismo atomic, para que un fallo a mitad de camino
    libere el token con el rollback.
    """
    if claim is None:
        return
    claim.result_url = result_url or ''
    claim.result_pk = result_pk
    claim.result_label = result_label or ''
    claim.save(update_fields=['result_url', 'result_pk', 'result_label'])


def duplicate_response(request, token_or_exc, fallback_url_name='record_list', noun='registro'):
    """
    Respuesta a un reenvío: SIEMPRE redirect + messages.info, nunca un error.

    El mensaje afirma que el registro sí se guardó, que es justo la información que
    le faltaba al digitador y lo llevaba a re-digitar. El 302 además rompe el ciclo
    "F5 -> reenviar formulario".
    """
    token = getattr(token_or_exc, 'token', token_or_exc)
    prior = FormSubmission.objects.filter(pk=token).first()
    label = f" ({prior.result_label})" if prior and prior.result_label else ""
    messages.info(
        request,
        f"Este {noun} ya fue guardado{label}. No se creó un duplicado."
    )
    target = prior.result_url if prior and prior.result_url else reverse(fallback_url_name)
    return redirect(target)
