"""
Idempotencia de las escrituras por API: cabecera `Idempotency-Key: <uuid>`.

Es el mismo mecanismo que protege los formularios (records/idempotency.py) y usa la
misma tabla FormSubmission: si la integración reintenta un POST porque no recibió la
respuesta, el segundo intento no crea nada y devuelve el recurso ya creado.
"""

import uuid

from django.db import IntegrityError
from django.db.models import F
from rest_framework import exceptions

from ..idempotency import DuplicateSubmission
from ..models import FormSubmission

HEADER = 'Idempotency-Key'


def idempotency_key(request):
    """UUID de la cabecera, None si no viene, o 400 si viene mal formada."""
    raw = (request.headers.get(HEADER) or '').strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise exceptions.ValidationError({HEADER: 'Debe ser un UUID (por ejemplo, un uuid4).'})


def previous_result(request, scope):
    """
    Chequeo de solo lectura antes de validar: devuelve el FormSubmission de un envío
    anterior con esta misma llave (su `result_pk` es lo que creó), o None si el
    envío es nuevo.
    """
    token = idempotency_key(request)
    if token is None:
        return None
    prior = FormSubmission.objects.filter(pk=token).first()
    if prior is None:
        return None
    if prior.scope != scope:
        raise exceptions.ValidationError(
            {HEADER: 'Esta llave de idempotencia ya se usó en otra operación.'})
    FormSubmission.objects.filter(pk=token).update(retry_count=F('retry_count') + 1)
    return prior


def claim(request, scope):
    """
    Consumo autoritativo de la llave. Debe ser la PRIMERA sentencia dentro del
    transaction.atomic() que escribe; levanta DuplicateSubmission si otro envío
    simultáneo con la misma llave ya hizo commit (capturar FUERA del atomic).
    """
    token = idempotency_key(request)
    if token is None:
        return None
    try:
        return FormSubmission.objects.create(
            token=token,
            user=request.user if request.user.is_authenticated else None,
            scope=scope,
        )
    except IntegrityError as exc:
        raise DuplicateSubmission(token) from exc


def complete(claimed, instance, label=''):
    if claimed is None:
        return
    claimed.result_pk = instance.pk
    claimed.result_label = (label or '')[:100]
    claimed.save(update_fields=['result_pk', 'result_label'])


def result_of(token):
    """PK creada por el envío que ganó la carrera (se consulta ya fuera del atomic)."""
    return FormSubmission.objects.filter(pk=token).values_list('result_pk', flat=True).first()
