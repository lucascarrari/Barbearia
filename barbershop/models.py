from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Role:
    ADMIN = "Administrador"
    MANAGER = "Gerente"
    BARBER = "Barbeiro"
    RECEPTIONIST = "Recepcionista"
    ALL = [ADMIN, MANAGER, BARBER, RECEPTIONIST]


class Service(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name


class Barber(TimeStampedModel):
    DEFAULT_WORK_DAYS = "0,1,2,3,4,5"

    name = models.CharField(max_length=120, unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="barber_profile",
    )
    is_active = models.BooleanField(default=True)
    work_days = models.CharField(max_length=20, default=DEFAULT_WORK_DAYS)
    work_start = models.TimeField(default=time(9, 0))
    work_end = models.TimeField(default=time(19, 0))
    break_start = models.TimeField(null=True, blank=True)
    break_end = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name

    @property
    def work_day_list(self):
        return [item for item in self.work_days.split(",") if item != ""]

    def works_on(self, day):
        return str(day.weekday()) in self.work_day_list

    def has_break(self):
        return self.break_start and self.break_end and self.break_start < self.break_end

    def is_inside_work_window(self, starts_at, ends_at):
        start_time = starts_at.time()
        end_time = ends_at.time()
        if start_time < self.work_start or end_time > self.work_end:
            return False
        if self.has_break() and start_time < self.break_end and end_time > self.break_start:
            return False
        return True


class AppointmentStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    CONFIRMED = "confirmed", "Confirmado"
    IN_PROGRESS = "in_progress", "Em atendimento"
    COMPLETED = "completed", "Concluido"
    CANCELED = "canceled", "Cancelado"
    NO_SHOW = "no_show", "Cliente nao compareceu"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    PAID = "paid", "Pago"
    PARTIAL = "partial", "Parcial"
    REFUNDED = "refunded", "Estornado"
    CANCELED = "canceled", "Cancelado"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Dinheiro"
    PIX = "pix", "Pix"
    DEBIT = "debit_card", "Cartao de debito"
    CREDIT = "credit_card", "Cartao de credito"
    OTHER = "other", "Outro"


ACTIVE_APPOINTMENT_STATUSES = [
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.COMPLETED,
]

SLOT_MINUTES = 30


class BarberTimeBlock(TimeStampedModel):
    barber = models.ForeignKey(Barber, on_delete=models.CASCADE, related_name="time_blocks")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    reason = models.CharField(max_length=160, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["barber", "date", "start_time"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.barber} - {self.date} {self.start_time}-{self.end_time}"

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.combine(self.date, self.start_time))

    @property
    def ends_at(self):
        return timezone.make_aware(datetime.combine(self.date, self.end_time))

    def clean(self):
        super().clean()
        if not self.start_time or not self.end_time:
            return
        if self.start_time.minute % SLOT_MINUTES != 0 or self.end_time.minute % SLOT_MINUTES != 0:
            raise ValidationError("Use horarios de 30 em 30 minutos para bloqueios.")
        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "O fim do bloqueio deve ser depois do inicio."})
        if not self.barber_id or not self.date or not self.is_active:
            return
        conflicting = (
            Appointment.objects.filter(
                barber=self.barber,
                date=self.date,
                is_archived=False,
                status__in=ACTIVE_APPOINTMENT_STATUSES,
            )
            .exclude(status__in=[AppointmentStatus.CANCELED, AppointmentStatus.NO_SHOW])
            .select_related("service")
        )
        for appointment in conflicting:
            if self.starts_at < appointment.ends_at and self.ends_at > appointment.starts_at:
                raise ValidationError(
                    "Nao e possivel bloquear um horario que ja tem atendimento ativo."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Appointment(TimeStampedModel):
    client_name = models.CharField(max_length=140)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    barber = models.ForeignKey(Barber, on_delete=models.PROTECT, related_name="appointments")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="appointments")
    service_name_snapshot = models.CharField(max_length=120)
    service_price = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.PIX,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["date", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["barber", "date", "start_time"],
                condition=Q(is_archived=False, status__in=ACTIVE_APPOINTMENT_STATUSES),
                name="unique_active_barber_start_time",
            ),
        ]
        indexes = [
            models.Index(fields=["date", "start_time"]),
            models.Index(fields=["barber", "date", "start_time"]),
            models.Index(fields=["status"]),
            models.Index(fields=["payment_status"]),
            models.Index(fields=["client_name"]),
            models.Index(fields=["phone"]),
        ]

    def __str__(self):
        return f"{self.client_name} - {self.date} {self.start_time}"

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.combine(self.date, self.start_time))

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    def _overlaps(self, other):
        return self.starts_at < other.ends_at and self.ends_at > other.starts_at

    def clean(self):
        super().clean()
        if self.service_id:
            if not self.service_price:
                self.service_price = self.service.price
            if not self.duration_minutes:
                self.duration_minutes = self.service.duration_minutes
            if not self.service_name_snapshot:
                self.service_name_snapshot = self.service.name

        if not self.barber_id or not self.date or not self.start_time or not self.duration_minutes:
            return

        if self.start_time.minute % SLOT_MINUTES != 0 or self.start_time.second or self.start_time.microsecond:
            raise ValidationError(
                {"start_time": "Escolha um horario fechado de 30 em 30 minutos."}
            )

        if self.status not in ACTIVE_APPOINTMENT_STATUSES or self.is_archived:
            return

        same_slot = False
        if self.pk:
            same_slot = Appointment.objects.filter(
                pk=self.pk,
                barber=self.barber,
                date=self.date,
                start_time=self.start_time,
                duration_minutes=self.duration_minutes,
            ).exists()

        if not same_slot:
            if not self.barber.is_active:
                raise ValidationError({"barber": "Este barbeiro esta inativo no momento."})

            if not self.barber.works_on(self.date):
                raise ValidationError({"date": "Este barbeiro nao trabalha nesta data."})

            if not self.barber.is_inside_work_window(self.starts_at, self.ends_at):
                raise ValidationError(
                    {"start_time": "Este horario esta fora da escala ou pausa do barbeiro."}
                )

            blocked = BarberTimeBlock.objects.filter(
                barber=self.barber,
                date=self.date,
                is_active=True,
            )
            for block in blocked:
                if self.starts_at < block.ends_at and self.ends_at > block.starts_at:
                    raise ValidationError({"start_time": "Este horario esta bloqueado para o barbeiro."})

        conflicting = (
            Appointment.objects.filter(
                barber=self.barber,
                date=self.date,
                is_archived=False,
                status__in=ACTIVE_APPOINTMENT_STATUSES,
            )
            .exclude(pk=self.pk)
            .select_related("service")
        )
        for appointment in conflicting:
            if self._overlaps(appointment):
                raise ValidationError(
                    {
                        "start_time": (
                            "Este horario conflita com outro agendamento do mesmo barbeiro."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        if self.service_id:
            self.service_name_snapshot = self.service_name_snapshot or self.service.name
            self.service_price = self.service_price or self.service.price
            self.duration_minutes = self.duration_minutes or self.service.duration_minutes
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def complete_with_payment(self, user, method=None, notes=""):
        locked = Appointment.objects.select_for_update().get(pk=self.pk)
        locked.status = AppointmentStatus.COMPLETED
        locked.payment_status = PaymentStatus.PAID
        locked.payment_method = method or locked.payment_method
        locked.save()
        payment, _ = Payment.objects.update_or_create(
            appointment=locked,
            status=PaymentStatus.PAID,
            defaults={
                "amount": locked.service_price,
                "method": locked.payment_method,
                "paid_at": timezone.now(),
                "notes": notes,
                "recorded_by": user if getattr(user, "is_authenticated", False) else None,
            },
        )
        return locked, payment


class Payment(TimeStampedModel):
    appointment = models.ForeignKey(Appointment, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_payments",
    )

    class Meta:
        ordering = ["-paid_at", "-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["method"]),
            models.Index(fields=["paid_at"]),
        ]

    def __str__(self):
        return f"{self.appointment_id} - {self.amount}"

    def clean(self):
        super().clean()
        if self.amount <= Decimal("0.00"):
            raise ValidationError({"amount": "O valor do pagamento deve ser positivo."})
        if self.appointment_id and self.amount > self.appointment.service_price:
            raise ValidationError(
                {"amount": "O pagamento nao pode exceder o valor do agendamento."}
            )
        if self.status == PaymentStatus.PAID and not self.paid_at:
            self.paid_at = timezone.now()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ServicePriceHistory(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="price_history")
    old_price = models.DecimalField(max_digits=10, decimal_places=2)
    new_price = models.DecimalField(max_digits=10, decimal_places=2)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_price_changes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.service} {self.old_price} -> {self.new_price}"


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=80)
    entity = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    session_key = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity", "object_id"]),
            models.Index(fields=["action"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.action} {self.entity} {self.object_id}"
