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
