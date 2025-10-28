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
