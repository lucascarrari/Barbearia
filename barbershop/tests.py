import json
from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Appointment,
    AppointmentStatus,
    Barber,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Role,
    Service,
)
from .services import available_slots, finance_summary
from .templatetags.barbershop_extras import appointment_whatsapp_url, whatsapp_phone


class BaseDataMixin:
    def setUp(self):
        self.service = Service.objects.create(
            name="Combo Tio Bigode",
            description="Corte e barba",
            price=Decimal("89.00"),
            duration_minutes=75,
        )
        self.short_service = Service.objects.create(
            name="Corte Classico",
            description="Corte",
            price=Decimal("55.00"),
            duration_minutes=45,
        )
        self.barber = Barber.objects.create(name="Tio Bigode")

    def make_appointment(self, start=time(10, 0), service=None, **kwargs):
        service = service or self.service
        return Appointment.objects.create(
            client_name=kwargs.get("client_name", "Lucas"),
            phone=kwargs.get("phone", "(11) 99999-0000"),
            email=kwargs.get("email", ""),
            barber=kwargs.get("barber", self.barber),
            service=service,
            service_name_snapshot=service.name,
            service_price=service.price,
            date=kwargs.get("date", date(2026, 8, 1)),
            start_time=start,
            duration_minutes=service.duration_minutes,
            payment_method=PaymentMethod.PIX,
            payment_status=kwargs.get("payment_status", PaymentStatus.PENDING),
            status=kwargs.get("status", AppointmentStatus.PENDING),
        )


class AppointmentRulesTests(BaseDataMixin, TestCase):
    def test_prevents_overlapping_appointment_for_same_barber(self):
        self.make_appointment(start=time(10, 0))
        with self.assertRaises(ValidationError):
            self.make_appointment(start=time(10, 30), client_name="Marcos")

    def test_allows_same_time_for_different_barber(self):
        other = Barber.objects.create(name="Nando Navalha")
        self.make_appointment(start=time(10, 0))
        appointment = self.make_appointment(start=time(10, 0), barber=other, client_name="Rafa")
        self.assertEqual(appointment.barber, other)

    def test_appointment_keeps_service_price_snapshot_after_price_change(self):
        appointment = self.make_appointment(start=time(12, 0), service=self.short_service)
        self.short_service.price = Decimal("75.00")
        self.short_service.save()
        appointment.refresh_from_db()
        self.assertEqual(appointment.service_price, Decimal("55.00"))

    def test_rejects_time_outside_30_minute_grid(self):
        with self.assertRaises(ValidationError):
            self.make_appointment(start=time(10, 15), client_name="Horario quebrado")

    def test_canceled_appointment_releases_slot(self):
        appointment = self.make_appointment(start=time(10, 0), service=self.short_service)
        before_cancel = available_slots(date(2026, 8, 1), self.barber, self.short_service)
        self.assertNotIn(
            "10:00",
            [slot["time"] for slot in before_cancel if slot["available"]],
        )
        appointment.status = AppointmentStatus.CANCELED
        appointment.payment_status = PaymentStatus.CANCELED
        appointment.save()
        after_cancel = available_slots(date(2026, 8, 1), self.barber, self.short_service)
        self.assertIn(
            "10:00",
            [slot["time"] for slot in after_cancel if slot["available"]],
        )

    def test_whatsapp_message_url_has_client_phone_and_appointment_details(self):
        appointment = self.make_appointment(
            start=time(14, 30),
            service=self.short_service,
            phone="(21) 96644-7903",
        )
        url = appointment_whatsapp_url(appointment)
        self.assertIn("https://wa.me/5521966447903?", url)
        self.assertIn("Corte+Classico", url)
        self.assertIn("14%3A30", url)

    def test_whatsapp_phone_adds_brazil_country_code(self):
        self.assertEqual(whatsapp_phone("(21) 96644-7903"), "5521966447903")


class FinanceTests(BaseDataMixin, TestCase):
    def test_finance_only_counts_paid_completed_appointments(self):
        completed = self.make_appointment(
            start=time(9, 0),
            status=AppointmentStatus.COMPLETED,
            payment_status=PaymentStatus.PAID,
        )
        Payment.objects.create(
            appointment=completed,
            amount=completed.service_price,
            method=PaymentMethod.PIX,
            status=PaymentStatus.PAID,
            paid_at=timezone.now(),
        )
        self.make_appointment(start=time(13, 0), status=AppointmentStatus.CANCELED)
        summary = finance_summary()
        self.assertEqual(summary["total"], Decimal("89.00"))
        self.assertEqual(summary["completed"], 1)


class PermissionTests(BaseDataMixin, TestCase):
    def test_receptionist_cannot_create_service(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.RECEPTIONIST)
        user = user_model.objects.create_user("recepcao", password="senha-forte-123")
        user.groups.add(group)
        self.client.force_login(user)
        response = self.client.get(reverse("service-create"))
        self.assertEqual(response.status_code, 302)

    def test_public_api_rejects_conflicting_appointment(self):
        self.make_appointment(start=time(10, 0))
        payload = {
            "client_name": "Rafael",
            "phone": "(11) 98888-7777",
            "email": "rafael@example.com",
            "barber": self.barber.pk,
            "service": self.short_service.pk,
            "date": "2026-08-01",
            "start_time": "10:30",
            "notes": "",
            "payment_method": PaymentMethod.PIX,
        }
        response = self.client.post(
            reverse("api-appointments"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_manager_can_create_barber_from_team_section(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.MANAGER)
        user = user_model.objects.create_user("gerente", password="senha-forte-123")
        user.groups.add(group)
        self.client.force_login(user)
        response = self.client.post(
            reverse("barber-create"),
            {
                "name": "Beto Navalha",
                "username": "beto",
                "password": "senha-forte-123",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        barber = Barber.objects.get(name="Beto Navalha", is_active=True)
        self.assertEqual(barber.user.username, "beto")
        self.assertTrue(barber.user.groups.filter(name=Role.BARBER).exists())
        self.assertTrue(barber.user.check_password("senha-forte-123"))

    def test_created_barber_user_logs_into_barber_dashboard_only(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.MANAGER)
        manager = user_model.objects.create_user("gerente", password="senha-forte-123")
        manager.groups.add(group)
        self.client.force_login(manager)
        self.client.post(
            reverse("barber-create"),
            {
                "name": "Beto Navalha",
                "username": "beto",
                "password": "senha-forte-123",
                "is_active": "on",
            },
        )
        self.client.logout()
        logged_in = self.client.login(username="beto", password="senha-forte-123")
        self.assertTrue(logged_in)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertRedirects(response, reverse("barber-dashboard"))

    def test_delete_barber_with_appointments_deactivates_instead_of_removing(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.MANAGER)
        user = user_model.objects.create_user("gerente", password="senha-forte-123")
        user.groups.add(group)
        self.client.force_login(user)
        self.make_appointment(start=time(15, 0))
        response = self.client.post(reverse("barber-delete", args=[self.barber.pk]))
        self.assertEqual(response.status_code, 302)
        self.barber.refresh_from_db()
        self.assertFalse(self.barber.is_active)

    def test_manager_can_toggle_barber_active_status(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.MANAGER)
        user = user_model.objects.create_user("gerente", password="senha-forte-123")
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.post(reverse("barber-toggle-active", args=[self.barber.pk]))
        self.assertEqual(response.status_code, 302)
        self.barber.refresh_from_db()
        self.assertFalse(self.barber.is_active)

        response = self.client.post(reverse("barber-toggle-active", args=[self.barber.pk]))
        self.assertEqual(response.status_code, 302)
        self.barber.refresh_from_db()
        self.assertTrue(self.barber.is_active)

    def test_barber_user_is_redirected_from_admin_to_own_dashboard(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.BARBER)
        user = user_model.objects.create_user("barbeiro", password="senha-forte-123")
        user.groups.add(group)
        self.barber.user = user
        self.barber.save()
        self.client.force_login(user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertRedirects(response, reverse("barber-dashboard"))

    def test_barber_dashboard_only_lists_own_clients(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.BARBER)
        user = user_model.objects.create_user("barbeiro", password="senha-forte-123")
        user.groups.add(group)
        self.barber.user = user
        self.barber.save()
        other_barber = Barber.objects.create(name="Outro Barbeiro")
        self.make_appointment(start=time(9, 0), client_name="Cliente do barbeiro")
        self.make_appointment(
            start=time(9, 0),
            barber=other_barber,
            client_name="Cliente de outro barbeiro",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("barber-dashboard"))
        body = response.content.decode("utf-8")
        self.assertContains(response, "Cliente do barbeiro")
        self.assertNotIn("Cliente de outro barbeiro", body)

    def test_manager_dashboard_has_full_management_sections(self):
        user_model = get_user_model()
        group = Group.objects.create(name=Role.MANAGER)
        user = user_model.objects.create_user("gerente", password="senha-forte-123")
        user.groups.add(group)
        self.client.force_login(user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertContains(response, "Financeiro")
        self.assertContains(response, "Equipe")
        self.assertContains(response, "Servicos")
