from .models import DuplicateRecordAttempt, AccessRequest

def duplicate_attempts_count(request):
    if request.user.is_authenticated and request.user.is_superuser:
        count = DuplicateRecordAttempt.objects.filter(is_resolved=False).count()
        return {'duplicate_attempts_count': count}
    return {'duplicate_attempts_count': 0}

def pending_requests_count(request):
    if request.user.is_superuser:
        return {'pending_requests_count': AccessRequest.objects.filter(approved=False).count()}
    return {}

# tu_app/context_processors.py

def user_group_names(request):
    """
    Agrega una lista de los nombres de los grupos a los que pertenece el usuario
    actual al contexto de la plantilla.
    """
    if request.user.is_authenticated:
        # Obtiene una lista de los nombres de los grupos del usuario
        groups = [group.name for group in request.user.groups.all()]
        return {'user_groups': groups}
    return {'user_groups': []} # Retorna una lista vacía si el usuario no está autenticado