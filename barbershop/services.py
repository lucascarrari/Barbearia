from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    AuditLog,
    Payment,
    PaymentStatus,
)


OPENING_HOUR = time(9, 0)
CLOSING_HOUR = time(19, 0)
SLOT_MINUTES = 30


def currency_brl(value):
    value = Decimal(value or 0)
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def audit(request, action, instance, old_values=None, new_values=None):
    user = getattr(request, "user", None)
    AuditLog.objects.create(
        actor=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        entity=instance.__class__.__name__,
        object_id=str(instance.pk),
        old_values=old_values or {},
        new_values=new_values or {},
        ip_address=get_client_ip(request),
        session_key=getattr(getattr(request, "session", None), "session_key", "") or "",
    )


def appointment_to_dict(appointment):
    return {
        "status": appointment.status,
        "payment_status": appointment.payment_status,
        "payment_method": appointment.payment_method,
        "date": appointment.date.isoformat(),
        "start_time": appointment.start_time.strftime("%H:%M"),
    }


def iter_slots(day, duration_minutes):
    cursor = datetime.combine(day, OPENING_HOUR)
    closing = datetime.combine(day, CLOSING_HOUR)
    while cursor + timedelta(minutes=duration_minutes) <= closing:
        yield cursor.time().strftime("%H:%M")
        cursor += timedelta(minutes=SLOT_MINUTES)


def available_slots(day, barber, service, appointment_id=None):
    slots = []
    qs = Appointment.objects.filter(
        barber=barber,
        date=day,
        is_archived=False,
        status__in=ACTIVE_APPOINTMENT_STATUSES,
    )
    if appointment_id:
        qs = qs.exclude(pk=appointment_id)
    existing = list(qs)

    for slot in iter_slots(day, service.duration_minutes):
        starts = timezone.make_aware(datetime.combine(day, datetime.strptime(slot, "%H:%M").time()))
        ends = starts + timedelta(minutes=service.duration_minutes)
        conflict = any(starts < item.ends_at and ends > item.starts_at for item in existing)
        slots.append({"time": slot, "available": not conflict})
    return slots


def finance_summary(filters=None):
    filters = filters or {}
    payments = Payment.objects.select_related(
        "appointment", "appointment__service", "appointment__barber"
    ).filter(
        status=PaymentStatus.PAID,
        appointment__status=AppointmentStatus.COMPLETED,
        appointment__is_archived=False,
    )

    start = filters.get("start")
    end = filters.get("end")
    if start:
        payments = payments.filter(paid_at__date__gte=start)
    if end:
        payments = payments.filter(paid_at__date__lte=end)
    if filters.get("barber"):
        payments = payments.filter(appointment__barber_id=filters["barber"])
    if filters.get("service"):
        payments = payments.filter(appointment__service_id=filters["service"])
    if filters.get("method"):
        payments = payments.filter(method=filters["method"])

    total = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    completed = payments.values("appointment_id").distinct().count()
    average = total / completed if completed else Decimal("0.00")
    pending = Appointment.objects.filter(payment_status=PaymentStatus.PENDING).aggregate(
        total=Sum("service_price")
    )["total"] or Decimal("0.00")
    canceled = Appointment.objects.filter(
        status__in=[AppointmentStatus.CANCELED, AppointmentStatus.NO_SHOW]
    ).aggregate(total=Sum("service_price"))["total"] or Decimal("0.00")

    by_service = payments.values("appointment__service_name_snapshot").annotate(total=Sum("amount"))
    by_barber = payments.values("appointment__barber__name").annotate(total=Sum("amount"))
    by_method = payments.values("method").annotate(total=Sum("amount"))
    by_day = payments.values("paid_at__date").annotate(total=Sum("amount")).order_by("paid_at__date")

    return {
        "total": total,
        "total_brl": currency_brl(total),
        "completed": completed,
        "average_brl": currency_brl(average),
        "pending_brl": currency_brl(pending),
        "canceled_brl": currency_brl(canceled),
        "by_service": list(by_service),
        "by_barber": list(by_barber),
        "by_method": list(by_method),
        "by_day": list(by_day),
        "payments": payments.order_by("-paid_at", "-created_at"),
    }


def period_bounds(period):
    today = timezone.localdate()
    if period == "day":
        return today, today
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, next_month - timedelta(days=1)
    if period == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return None, None
