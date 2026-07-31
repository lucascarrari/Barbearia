from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .models import Role


def has_role(user, *roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def can_access_admin(user):
    return has_role(user, Role.ADMIN, Role.MANAGER, Role.RECEPTIONIST) or user.is_staff


def is_barber_only(user):
    return has_role(user, Role.BARBER) and not has_role(
        user,
        Role.ADMIN,
        Role.MANAGER,
        Role.RECEPTIONIST,
    )


def can_manage_services(user):
    return has_role(user, Role.ADMIN, Role.MANAGER)


def can_manage_team(user):
    return has_role(user, Role.ADMIN, Role.MANAGER)


def can_view_finance(user):
    return has_role(user, Role.ADMIN, Role.MANAGER)


def can_delete_appointments(user):
    return has_role(user, Role.ADMIN, Role.MANAGER)


def can_register_payments(user):
    return has_role(user, Role.ADMIN, Role.MANAGER, Role.RECEPTIONIST)


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if has_role(request.user, *roles):
                return view_func(request, *args, **kwargs)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return HttpResponseForbidden("Permissao insuficiente.")
            messages.error(request, "Voce nao tem permissao para acessar esta area.")
            return redirect("admin-dashboard")

        return wrapper

    return decorator


def admin_area_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if can_access_admin(request.user):
            return view_func(request, *args, **kwargs)
        if is_barber_only(request.user):
            return redirect("barber-dashboard")
        return HttpResponseForbidden("Permissao insuficiente.")

    return wrapper
