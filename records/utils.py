import holidays
from datetime import timedelta

def calculate_effective_date(start_date, business_days_to_add):
    """
    Calcula una fecha futura sumando días hábiles (lunes a viernes),
    excluyendo los festivos de Colombia.
    """
    if business_days_to_add <= 0:
        return start_date

    # Inicializamos los festivos de Colombia
    co_holidays = holidays.CountryHoliday('CO')
    current_date = start_date
    days_added = 0

    while days_added < business_days_to_add:
        current_date += timedelta(days=1)
        # El día de la semana es < 5 si es de Lunes a Viernes
        is_weekday = current_date.weekday() < 5
        is_holiday = current_date in co_holidays

        if is_weekday and not is_holiday:
            days_added += 1

    return current_date


class _Echo:
    """Pseudo-buffer: csv.writer le «escribe» y devuelve la línea ya formateada."""

    def write(self, value):
        return value


def stream_csv(filename, header, rows, delimiter=',', bom=False):
    """
    Devuelve un CSV como StreamingHttpResponse.

    `rows` debe ser un iterable perezoso (un generador sobre queryset.iterator()):
    las filas se envían al navegador a medida que salen de la base de datos, así el
    archivo nunca vive entero en memoria y el worker no se queda mudo mientras lo
    arma. Antes un export grande superaba el timeout de gunicorn y tumbaba la app.
    """
    import csv
    from django.http import StreamingHttpResponse

    writer = csv.writer(_Echo(), delimiter=delimiter)

    def generate():
        if bom:
            # BOM para que Excel abra bien los caracteres especiales (UTF-8)
            yield '﻿'
        yield writer.writerow(header)
        for row in rows:
            yield writer.writerow(row)

    response = StreamingHttpResponse(generate(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def user_group_names(user):
    """
    Nombres de los grupos del usuario, consultados una sola vez por request.

    El resultado se guarda en el propio objeto usuario (que vive lo que dura la
    petición), así el decorador group_required y el context processor comparten
    la misma consulta en vez de repetirla.
    """
    if not getattr(user, 'is_authenticated', False):
        return frozenset()
    cached = getattr(user, '_group_names_cache', None)
    if cached is None:
        cached = frozenset(user.groups.values_list('name', flat=True))
        user._group_names_cache = cached
    return cached
