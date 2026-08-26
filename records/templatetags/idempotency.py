"""Template tag para emitir la llave de idempotencia de un formulario."""

import uuid

from django import template
from django.utils.html import format_html

from records.idempotency import SUBMIT_TOKEN_FIELD

register = template.Library()


@register.simple_tag
def submit_token():
    """
    Emite el campo oculto con la llave de idempotencia del envío.

    Se genera un UUID nuevo en cada render, sin reutilizar el que venga en el POST.
    Puede parecer que hace falta conservarlo cuando el formulario se re-renderiza por
    un error de validación, pero no: en esas rutas nunca se llegó al INSERT del
    token, así que no hay nada consumido. Un token fresco es igual de seguro y evita
    toda la maquinaria de reutilización (incluido el caso de dos formularios en la
    misma página, como en transaction_form.html).

    Uso: {% load idempotency %} arriba, y {% submit_token %} junto a {% csrf_token %}.
    """
    return format_html(
        '<input type="hidden" name="{}" value="{}">',
        SUBMIT_TOKEN_FIELD, uuid.uuid4()
    )
