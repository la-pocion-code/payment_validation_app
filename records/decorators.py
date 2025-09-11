from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect
from django.urls import reverse

def group_required(*group_names):
    """Requires user membership in at least one of the groups passed in."""
    def in_groups(u):
        if u.is_authenticated:
            if bool(u.groups.filter(name__in=group_names)) or u.is_superuser:
                return True
        return False
    return user_passes_test(in_groups, login_url='request_access')

def user_is_not_blocked(function):
    def wrap(request, *args, **kwargs):
        if request.user.is_active:
            return function(request, *args, **kwargs)
        else:
            return redirect(reverse('login'))
    return wrap
