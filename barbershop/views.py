import csv
import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    AdminLoginForm,
    AppointmentAdminForm,
    AppointmentFilterForm,
    BarberForm,
    BarberScheduleForm,
    BarberTimeBlockForm,
    PaymentForm,
    PublicAppointmentForm,
    ServiceForm,
)
from .models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    Barber,
    BarberTimeBlock,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Role,
    Service,
    ServicePriceHistory,
)
from .permissions import (
    admin_area_required,
    can_delete_appointments,
    can_manage_team,
    can_manage_services,
    can_register_payments,
    can_view_finance,
    has_role,
    is_barber_only,
    role_required,
)
from .services import appointment_to_dict, audit, available_slots, finance_summary, period_bounds


def wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def json_or_redirect(request, message, redirect_to="admin-dashboard", status=200):
    if wants_json(request):
        return JsonResponse({"ok": status < 400, "message": message}, status=status)
    if status < 400:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect(redirect_to)


def scoped_appointments_for(user):
    qs = Appointment.objects.select_related("barber", "service").filter(is_archived=False)
    if has_role(user, Role.BARBER) and not has_role(user, Role.ADMIN, Role.MANAGER, Role.RECEPTIONIST):
        barber = getattr(user, "barber_profile", None)
        return qs.filter(barber=barber) if barber else qs.none()
    return qs


def barber_appointments_for(user):
    barber = getattr(user, "barber_profile", None)
    if not barber:
        return Appointment.objects.none()
    return Appointment.objects.select_related("barber", "service").filter(
        barber=barber,
        is_archived=False,
    )


class AdminLoginView(LoginView):
    template_name = "barbershop/admin_login.html"
    authentication_form = AdminLoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        self.rate_key = f"login-attempts:{request.META.get('REMOTE_ADDR')}:{request.POST.get('username', '')}"
        attempts = cache.get(self.rate_key, 0)
        if attempts >= 5:
            messages.error(request, "Muitas tentativas de login. Aguarde alguns minutos.")
            return render(request, self.template_name, {"form": self.authentication_form(request)})
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if not (
            user.is_staff
            or user.is_superuser
            or user.groups.filter(name__in=Role.ALL).exists()
        ):
            raise PermissionDenied("Usuario sem acesso administrativo.")
        cache.delete(self.rate_key)
        login(self.request, user)
        if is_barber_only(user):
            return redirect("barber-dashboard")
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        cache.set(self.rate_key, cache.get(self.rate_key, 0) + 1, 15 * 60)
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy("admin-dashboard")


class AdminLogoutView(LogoutView):
    next_page = reverse_lazy("admin-login")


def home(request):
    services = Service.objects.filter(is_active=True)
    barbers = Barber.objects.filter(is_active=True)
    form = PublicAppointmentForm()
    return render(
        request,
        "barbershop/home.html",
        {"services": services, "barbers": barbers, "form": form},
    )


@require_POST
def appointment_create(request):
    form = PublicAppointmentForm(request.POST)
    if form.is_valid():
        appointment = form.save(commit=False)
        appointment.status = AppointmentStatus.PENDING
        appointment.payment_status = PaymentStatus.PENDING
        appointment.service_price = appointment.service.price
        appointment.duration_minutes = appointment.service.duration_minutes
        appointment.service_name_snapshot = appointment.service.name
        try:
            appointment.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            audit(request, "appointment_created_public", appointment, new_values=appointment_to_dict(appointment))
            messages.success(request, "Agendamento solicitado com sucesso.")
            return redirect("home")
    services = Service.objects.filter(is_active=True)
    barbers = Barber.objects.filter(is_active=True)
    messages.error(request, "Revise os dados do agendamento.")
    return render(
        request,
        "barbershop/home.html",
        {"services": services, "barbers": barbers, "form": form},
        status=400,
    )


@require_GET
def api_services(request):
    data = [
        {
            "id": service.pk,
            "name": service.name,
            "description": service.description,
            "price": str(service.price),
            "duration_minutes": service.duration_minutes,
        }
        for service in Service.objects.filter(is_active=True)
    ]
    return JsonResponse({"services": data})


@require_GET
def api_availability(request):
    try:
        day = timezone.datetime.fromisoformat(request.GET["date"]).date()
        barber = Barber.objects.get(pk=request.GET["barber"], is_active=True)
        service = Service.objects.get(pk=request.GET["service"], is_active=True)
    except (KeyError, ValueError, Barber.DoesNotExist, Service.DoesNotExist):
        return JsonResponse({"error": "Parametros invalidos."}, status=400)
    slots = [slot for slot in available_slots(day, barber, service) if slot["available"]]
    return JsonResponse({"slots": slots})


@require_POST
def api_appointments(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalido."}, status=400)

    form = PublicAppointmentForm(payload)
    if not form.is_valid():
        errors = form.errors.as_json()
        status = 409 if "conflita" in errors else 400
        return JsonResponse({"errors": form.errors}, status=status)

    appointment = form.save(commit=False)
    appointment.status = AppointmentStatus.PENDING
    appointment.payment_status = PaymentStatus.PENDING
    appointment.service_price = appointment.service.price
    appointment.duration_minutes = appointment.service.duration_minutes
    appointment.service_name_snapshot = appointment.service.name
    try:
        appointment.save()
    except ValidationError as exc:
        return JsonResponse({"errors": exc.message_dict if hasattr(exc, "message_dict") else exc.messages}, status=409)
    audit(request, "appointment_created_api", appointment, new_values=appointment_to_dict(appointment))
    return JsonResponse({"id": appointment.pk, "status": appointment.status}, status=201)


@admin_area_required
def admin_dashboard(request):
    allowed_sections = {"dashboard", "agenda", "servicos", "equipe", "financeiro"}
    active_section = request.GET.get("section", "dashboard")
    if active_section not in allowed_sections:
        active_section = "dashboard"

    filters = AppointmentFilterForm(request.GET or None)
    appointments = scoped_appointments_for(request.user)
    if filters.is_valid():
        cleaned = filters.cleaned_data
        if cleaned.get("q"):
            term = cleaned["q"]
            appointments = appointments.filter(Q(client_name__icontains=term) | Q(phone__icontains=term))
        if cleaned.get("date"):
            appointments = appointments.filter(date=cleaned["date"])
        if cleaned.get("start"):
            appointments = appointments.filter(date__gte=cleaned["start"])
        if cleaned.get("end"):
            appointments = appointments.filter(date__lte=cleaned["end"])
        if cleaned.get("barber"):
            appointments = appointments.filter(barber=cleaned["barber"])
        if cleaned.get("service"):
            appointments = appointments.filter(service=cleaned["service"])
        if cleaned.get("status"):
            appointments = appointments.filter(status=cleaned["status"])
        if cleaned.get("payment_status"):
            appointments = appointments.filter(payment_status=cleaned["payment_status"])

    view_mode = request.GET.get("view", "list")
    today = timezone.localdate()
    if view_mode == "day":
        appointments = appointments.filter(date=request.GET.get("date") or today)
    elif view_mode == "week":
        start = today - timedelta(days=today.weekday())
        appointments = appointments.filter(date__range=(start, start + timedelta(days=6)))
    elif view_mode == "month":
        appointments = appointments.filter(date__year=today.year, date__month=today.month)

    paginator = Paginator(appointments.order_by("date", "start_time"), 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    period = request.GET.get("finance_period", "month")
    start, end = period_bounds(period)
    finance = None
    if can_view_finance(request.user):
        finance = finance_summary(
            {
                "start": request.GET.get("finance_start") or start,
                "end": request.GET.get("finance_end") or end,
                "barber": request.GET.get("finance_barber"),
                "service": request.GET.get("finance_service"),
                "method": request.GET.get("finance_method"),
            }
        )

    today = timezone.localdate()
    month_start, month_end = period_bounds("month")
    scoped_all = scoped_appointments_for(request.user)
    dashboard = {
        "today_count": scoped_all.filter(date=today).count(),
        "month_count": scoped_all.filter(date__range=(month_start, month_end)).count(),
        "completed_count": scoped_all.filter(status=AppointmentStatus.COMPLETED).count(),
        "pending_count": scoped_all.filter(status=AppointmentStatus.PENDING).count(),
        "next_appointments": scoped_all.filter(
            date__gte=today,
            status__in=[
                AppointmentStatus.PENDING,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.IN_PROGRESS,
            ],
        ).order_by("date", "start_time")[:8],
    }
    if can_view_finance(request.user):
        dashboard["today_revenue"] = finance_summary({"start": today, "end": today})["total_brl"]
        dashboard["month_revenue"] = finance_summary({"start": month_start, "end": month_end})[
            "total_brl"
        ]

    team_barbers = Barber.objects.select_related("user").prefetch_related("time_blocks").all()
    schedule_forms = {
        barber.pk: BarberScheduleForm(instance=barber, prefix=f"schedule-{barber.pk}")
        for barber in team_barbers
    }
    block_forms = {
        barber.pk: BarberTimeBlockForm(prefix=f"block-{barber.pk}") for barber in team_barbers
    }
    active_blocks = {
        barber.pk: [
            block
            for block in barber.time_blocks.all()
            if block.is_active and block.date >= today
        ][:6]
        for barber in team_barbers
    }

    context = {
        "active_section": active_section,
        "dashboard": dashboard,
        "filters": filters,
        "page_obj": page_obj,
        "appointments": page_obj.object_list,
        "services": Service.objects.all(),
        "barbers": Barber.objects.filter(is_active=True),
        "team_barbers": team_barbers,
        "schedule_forms": schedule_forms,
        "block_forms": block_forms,
        "active_blocks": active_blocks,
        "payment_methods": PaymentMethod.choices,
        "appointment_statuses": AppointmentStatus.choices,
        "payment_statuses": PaymentStatus.choices,
        "finance": finance,
        "can_manage_services": can_manage_services(request.user),
        "can_manage_team": can_manage_team(request.user),
        "can_view_finance": can_view_finance(request.user),
        "can_delete_appointments": can_delete_appointments(request.user),
        "can_register_payments": can_register_payments(request.user),
        "service_form": ServiceForm(),
        "barber_form": BarberForm(),
    }
    return render(request, "barbershop/admin_dashboard.html", context)


@login_required
def barber_dashboard(request):
    if not is_barber_only(request.user):
        return redirect("admin-dashboard")

    barber = getattr(request.user, "barber_profile", None)
    appointments = barber_appointments_for(request.user)
    today = timezone.localdate()

    selected_date = request.GET.get("date")
    selected_status = request.GET.get("status")
    if selected_date:
        appointments = appointments.filter(date=selected_date)
    else:
        appointments = appointments.filter(date__gte=today)
    if selected_status:
        appointments = appointments.filter(status=selected_status)

    appointments = appointments.order_by("date", "start_time")
    context = {
        "barber": barber,
        "appointments": appointments[:60],
        "selected_date": selected_date,
        "selected_status": selected_status,
        "statuses": AppointmentStatus.choices,
        "today_count": barber_appointments_for(request.user).filter(date=today).count(),
        "pending_count": barber_appointments_for(request.user).filter(
            status=AppointmentStatus.PENDING,
            date__gte=today,
        ).count(),
        "confirmed_count": barber_appointments_for(request.user).filter(
            status=AppointmentStatus.CONFIRMED,
            date__gte=today,
        ).count(),
    }
    return render(request, "barbershop/barber_dashboard.html", context)


@admin_area_required
def appointment_detail(request, pk):
    appointment = get_object_or_404(scoped_appointments_for(request.user), pk=pk)
    return render(
        request,
        "barbershop/appointment_detail.html",
        {"appointment": appointment, "payments": appointment.payments.all()},
    )


@admin_area_required
def appointment_edit(request, pk):
    appointment = get_object_or_404(scoped_appointments_for(request.user), pk=pk)
    old_values = appointment_to_dict(appointment)
    form = AppointmentAdminForm(request.POST or None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        updated = form.save()
        audit(request, "appointment_updated", updated, old_values, appointment_to_dict(updated))
        messages.success(request, "Agendamento atualizado.")
        return redirect("appointment-detail", pk=updated.pk)
    return render(request, "barbershop/appointment_form.html", {"form": form, "appointment": appointment})


@require_POST
@admin_area_required
def appointment_action(request, pk, action):
    appointment = get_object_or_404(scoped_appointments_for(request.user), pk=pk)
    if action == "delete" and not can_delete_appointments(request.user):
        return json_or_redirect(request, "Somente administradores podem excluir.", status=403)

    old_values = appointment_to_dict(appointment)
    actions = {
        "confirm": AppointmentStatus.CONFIRMED,
        "start": AppointmentStatus.IN_PROGRESS,
        "cancel": AppointmentStatus.CANCELED,
        "no_show": AppointmentStatus.NO_SHOW,
    }
    try:
        if action == "complete":
            method = request.POST.get("payment_method") or appointment.payment_method
            appointment, payment = appointment.complete_with_payment(request.user, method=method)
            audit(request, "appointment_completed", appointment, old_values, appointment_to_dict(appointment))
            audit(request, "payment_registered", payment, new_values={"amount": str(payment.amount), "status": payment.status})
            return json_or_redirect(request, "Atendimento concluido e pagamento registrado.")
        if action == "delete":
            appointment.is_archived = True
            appointment.save()
            audit(request, "appointment_archived", appointment, old_values, appointment_to_dict(appointment))
            return json_or_redirect(request, "Agendamento arquivado.")
        if action not in actions:
            return json_or_redirect(request, "Acao invalida.", status=400)
        appointment.status = actions[action]
        if action in {"cancel", "no_show"}:
            appointment.payment_status = PaymentStatus.CANCELED
        appointment.save()
    except ValidationError as exc:
        return json_or_redirect(request, "; ".join(exc.messages), status=400)
    audit(request, f"appointment_{action}", appointment, old_values, appointment_to_dict(appointment))
    return json_or_redirect(request, "Agendamento atualizado.")


@role_required(Role.ADMIN, Role.MANAGER)
def service_create(request):
    form = ServiceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        service = form.save()
        audit(request, "service_created", service, new_values={"price": str(service.price)})
        messages.success(request, "Servico cadastrado.")
        return redirect("admin-dashboard")
    return render(request, "barbershop/service_form.html", {"form": form})


@role_required(Role.ADMIN, Role.MANAGER)
def service_edit(request, pk):
    service = get_object_or_404(Service, pk=pk)
    old_price = service.price
    form = ServiceForm(request.POST or None, instance=service)
    if request.method == "POST" and form.is_valid():
        updated = form.save()
        if old_price != updated.price:
            ServicePriceHistory.objects.create(
                service=updated,
                old_price=old_price,
                new_price=updated.price,
                changed_by=request.user,
            )
        audit(
            request,
            "service_updated",
            updated,
            {"price": str(old_price)},
            {"price": str(updated.price), "is_active": updated.is_active},
        )
        messages.success(request, "Servico atualizado.")
        return redirect("admin-dashboard")
    return render(
        request,
        "barbershop/service_form.html",
        {"form": form, "service": service, "history": service.price_history.all()[:20]},
    )


@require_POST
@role_required(Role.ADMIN, Role.MANAGER)
def barber_create(request):
    form = BarberForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            User = get_user_model()
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            barber_group, _ = Group.objects.get_or_create(name=Role.BARBER)
            user.groups.add(barber_group)
            barber = form.save(commit=False)
            barber.user = user
            barber.save()
            audit(
                request,
                "barber_created",
                barber,
                new_values={
                    "name": barber.name,
                    "is_active": barber.is_active,
                    "username": user.username,
                },
            )
        messages.success(request, "Barbeiro cadastrado.")
    else:
        first_error = next(iter(form.errors.values()))[0]
        messages.error(request, f"Revise os dados do barbeiro: {first_error}")
    return redirect(f"{reverse('admin-dashboard')}?section=equipe")


@require_POST
@role_required(Role.ADMIN, Role.MANAGER)
def barber_delete(request, pk):
    barber = get_object_or_404(Barber, pk=pk)
    old_values = {"name": barber.name, "is_active": barber.is_active}
    if barber.appointments.exists():
        barber.is_active = False
        barber.save()
        audit(
            request,
            "barber_deactivated",
            barber,
            old_values,
            {"name": barber.name, "is_active": barber.is_active},
        )
        messages.success(request, "Barbeiro desativado para preservar o historico de agendamentos.")
    else:
        audit(request, "barber_deleted", barber, old_values, {})
        barber.delete()
        messages.success(request, "Barbeiro excluido.")
    return redirect(f"{reverse('admin-dashboard')}?section=equipe")


@require_POST
@role_required(Role.ADMIN, Role.MANAGER)
def barber_toggle_active(request, pk):
    barber = get_object_or_404(Barber, pk=pk)
    old_values = {"name": barber.name, "is_active": barber.is_active}
    barber.is_active = not barber.is_active
    barber.save()
    action = "barber_activated" if barber.is_active else "barber_deactivated"
    audit(
        request,
        action,
        barber,
        old_values,
        {"name": barber.name, "is_active": barber.is_active},
    )
    messages.success(
        request,
        f"{barber.name} foi {'ativado' if barber.is_active else 'desativado'}.",
    )
    return redirect(f"{reverse('admin-dashboard')}?section=equipe")


@require_POST
@role_required(Role.ADMIN, Role.MANAGER)
def barber_schedule_update(request, pk):
    barber = get_object_or_404(Barber, pk=pk)
    old_values = {
        "work_days": barber.work_days,
        "work_start": barber.work_start.strftime("%H:%M"),
        "work_end": barber.work_end.strftime("%H:%M"),
        "break_start": barber.break_start.strftime("%H:%M") if barber.break_start else "",
        "break_end": barber.break_end.strftime("%H:%M") if barber.break_end else "",
    }
    form = BarberScheduleForm(request.POST, instance=barber, prefix=f"schedule-{barber.pk}")
    if form.is_valid():
        updated = form.save()
        audit(
            request,
            "barber_schedule_updated",
            updated,
            old_values,
            {
                "work_days": updated.work_days,
                "work_start": updated.work_start.strftime("%H:%M"),
                "work_end": updated.work_end.strftime("%H:%M"),
                "break_start": updated.break_start.strftime("%H:%M") if updated.break_start else "",
                "break_end": updated.break_end.strftime("%H:%M") if updated.break_end else "",
            },
        )
        messages.success(request, f"Escala de {barber.name} atualizada.")
    else:
        first_error = next(iter(form.errors.values()))[0]
        messages.error(request, f"Revise a escala: {first_error}")
    return redirect(f"{reverse('admin-dashboard')}?section=equipe")


@require_POST
@role_required(Role.ADMIN, Role.MANAGER)
def barber_block_create(request, pk):
    barber = get_object_or_404(Barber, pk=pk)
    form = BarberTimeBlockForm(request.POST, prefix=f"block-{barber.pk}")
    if form.is_valid():
        block = form.save(commit=False)
        block.barber = barber
        try:
            block.save()
        except ValidationError as exc:
            message = "; ".join(exc.messages)
            messages.error(request, f"Nao foi possivel criar o bloqueio: {message}")
        else:
            audit(
                request,
                "barber_time_block_created",
                block,
                new_values={
                    "barber": barber.name,
                    "date": block.date.isoformat(),
                    "start_time": block.start_time.strftime("%H:%M"),
                    "end_time": block.end_time.strftime("%H:%M"),
                },
            )
            messages.success(request, f"Horario bloqueado para {barber.name}.")
    else:
        first_error = next(iter(form.errors.values()))[0]
        messages.error(request, f"Revise o bloqueio: {first_error}")
    return redirect(f"{reverse('admin-dashboard')}?section=equipe")


@require_POST
@role_required(Role.ADMIN, Role.MANAGER)
def barber_block_delete(request, pk):
    block = get_object_or_404(BarberTimeBlock, pk=pk)
    barber_name = block.barber.name
    old_values = {
        "barber": barber_name,
        "date": block.date.isoformat(),
        "start_time": block.start_time.strftime("%H:%M"),
        "end_time": block.end_time.strftime("%H:%M"),
    }
    block.is_active = False
    block.save()
    audit(request, "barber_time_block_removed", block, old_values, {"is_active": False})
    messages.success(request, f"Bloqueio removido para {barber_name}.")
    return redirect(f"{reverse('admin-dashboard')}?section=equipe")


@require_POST
@role_required(Role.ADMIN, Role.MANAGER, Role.RECEPTIONIST)
def payment_register(request, appointment_pk):
    appointment = get_object_or_404(scoped_appointments_for(request.user), pk=appointment_pk)
    form = PaymentForm(request.POST, appointment=appointment)
    if form.is_valid():
        with transaction.atomic():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            payment.amount = appointment.service_price
            payment.save()
            appointment.payment_method = payment.method
            appointment.payment_status = payment.status
            appointment.save()
        audit(
            request,
            "payment_registered",
            payment,
            new_values={"amount": str(payment.amount), "status": payment.status},
        )
        return json_or_redirect(request, "Pagamento registrado.")
    return json_or_redirect(request, "Pagamento invalido.", status=400)


@role_required(Role.ADMIN, Role.MANAGER)
def finance_export_csv(request):
    start, end = period_bounds(request.GET.get("finance_period", "month"))
    finance = finance_summary(
        {
            "start": request.GET.get("finance_start") or start,
            "end": request.GET.get("finance_end") or end,
            "barber": request.GET.get("finance_barber"),
            "service": request.GET.get("finance_service"),
            "method": request.GET.get("finance_method"),
        }
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="financeiro-tio-bigode.csv"'
    writer = csv.writer(response)
    writer.writerow(["data", "cliente", "servico", "barbeiro", "valor", "forma", "status", "agendamento"])
    for payment in finance["payments"]:
        writer.writerow(
            [
                payment.paid_at.date().isoformat() if payment.paid_at else "",
                payment.appointment.client_name,
                payment.appointment.service_name_snapshot,
                payment.appointment.barber.name,
                payment.amount,
                payment.get_method_display(),
                payment.get_status_display(),
                payment.appointment_id,
            ]
        )
    return response
