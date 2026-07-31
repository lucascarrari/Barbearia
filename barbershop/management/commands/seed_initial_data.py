from decimal import Decimal
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from barbershop.models import Barber, Role, Service


class Command(BaseCommand):
    help = "Cria grupos, usuarios de desenvolvimento, barbeiros e servicos iniciais."

    def handle(self, *args, **options):
        User = get_user_model()
        groups = {name: Group.objects.get_or_create(name=name)[0] for name in Role.ALL}

        all_permissions = Permission.objects.all()
        groups[Role.ADMIN].permissions.set(all_permissions)
        groups[Role.MANAGER].permissions.set(
            Permission.objects.filter(
                content_type__app_label="barbershop",
                content_type__model__in=[
                    "appointment",
                    "payment",
                    "service",
                    "servicepricehistory",
                    "barber",
                ],
            )
        )
        groups[Role.RECEPTIONIST].permissions.set(
            Permission.objects.filter(
                content_type__app_label="barbershop",
                content_type__model__in=["appointment", "payment"],
            )
        )
        groups[Role.BARBER].permissions.set(
            Permission.objects.filter(
                content_type__app_label="barbershop",
                content_type__model__in=["appointment"],
            )
        )

        users = [
            ("admin", Role.ADMIN, True),
            ("gerente", Role.MANAGER, True),
            ("recepcao", Role.RECEPTIONIST, True),
            ("tiobigode", Role.BARBER, True),
        ]
        seed_password = os.environ.get("TIO_BIGODE_SEED_PASSWORD")
        for username, role, staff in users:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@tiobigode.local", "is_staff": staff},
            )
            if created:
                if seed_password:
                    user.set_password(seed_password)
                else:
                    user.set_unusable_password()
                user.save()
            user.groups.add(groups[role])

        services = [
            ("Corte Classico", "Tesoura, maquina e acabamento com navalha.", Decimal("55.00"), 45),
            ("Barba Premium", "Toalha quente, espuma cremosa e oleo finalizador.", Decimal("45.00"), 35),
            ("Bigode Assinatura", "Design, alinhamento e modelagem do bigode.", Decimal("35.00"), 25),
            ("Combo Tio Bigode", "Corte, barba, bigode e finalizacao completa.", Decimal("89.00"), 75),
        ]
        for name, description, price, duration in services:
            Service.objects.update_or_create(
                name=name,
                defaults={
                    "description": description,
                    "price": price,
                    "duration_minutes": duration,
                    "is_active": True,
                },
            )

        barber_user = User.objects.filter(username="tiobigode").first()
        barbers = [
            ("Tio Bigode", barber_user),
            ("Nando Navalha", None),
            ("Caio Tesoura", None),
            ("Rafa Fade", None),
        ]
        for name, user in barbers:
            Barber.objects.update_or_create(
                name=name,
                defaults={"user": user, "is_active": True},
            )

        if not seed_password:
            self.stdout.write(
                self.style.WARNING(
                    "Usuarios novos foram criados sem senha. Defina TIO_BIGODE_SEED_PASSWORD ou use createsuperuser."
                )
            )
        self.stdout.write(self.style.SUCCESS("Dados iniciais criados/atualizados."))
