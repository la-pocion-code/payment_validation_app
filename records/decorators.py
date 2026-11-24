from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect
from django.urls import reverse

from .utils import user_group_names


def group_required(*group_names):
    """Requires user membership in at least one of the groups passed in."""
    def in_groups(u):
        if u.is_authenticated:
            if u.is_superuser or not user_group_names(u).isdisjoint(group_names):
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
