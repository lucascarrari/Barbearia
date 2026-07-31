from django.contrib import admin

from .models import Appointment, AuditLog, Barber, BarberTimeBlock, Payment, Service, ServicePriceHistory


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_minutes", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)

    def save_model(self, request, obj, form, change):
        old_price = None
        if change:
            old_price = Service.objects.get(pk=obj.pk).price
        super().save_model(request, obj, form, change)
        if old_price is not None and old_price != obj.price:
            ServicePriceHistory.objects.create(
                service=obj,
                old_price=old_price,
                new_price=obj.price,
                changed_by=request.user,
            )


@admin.register(Barber)
class BarberAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "is_active", "work_start", "work_end", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "user__username")


@admin.register(BarberTimeBlock)
class BarberTimeBlockAdmin(admin.ModelAdmin):
    list_display = ("barber", "date", "start_time", "end_time", "reason", "is_active")
    list_filter = ("is_active", "date", "barber")
    search_fields = ("barber__name", "reason")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "client_name",
        "barber",
        "service_name_snapshot",
        "date",
        "start_time",
        "status",
        "payment_status",
    )
    list_filter = ("status", "payment_status", "barber", "service", "date")
    search_fields = ("client_name", "phone", "email")
    readonly_fields = ("service_name_snapshot", "service_price", "created_at", "updated_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("appointment", "amount", "method", "status", "paid_at", "recorded_by")
    list_filter = ("method", "status", "paid_at")
    search_fields = ("appointment__client_name", "appointment__phone")


@admin.register(ServicePriceHistory)
class ServicePriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("service", "old_price", "new_price", "changed_by", "created_at")
    readonly_fields = ("service", "old_price", "new_price", "changed_by", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "entity", "object_id", "actor", "ip_address", "created_at")
    list_filter = ("action", "entity", "created_at")
    search_fields = ("object_id", "actor__username")
    readonly_fields = (
        "actor",
        "action",
        "entity",
        "object_id",
        "old_values",
        "new_values",
        "ip_address",
        "session_key",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
