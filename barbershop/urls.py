from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("agendar/", views.appointment_create, name="appointment-create"),
    path("api/services/", views.api_services, name="api-services"),
    path("api/availability/", views.api_availability, name="api-availability"),
    path("api/appointments/", views.api_appointments, name="api-appointments"),
    path("admin/login/", views.AdminLoginView.as_view(), name="admin-login"),
    path("admin/logout/", views.AdminLogoutView.as_view(), name="admin-logout"),
    path("admin/", views.admin_dashboard, name="admin-dashboard"),
    path("barbeiro/", views.barber_dashboard, name="barber-dashboard"),
    path("admin/agendamentos/<int:pk>/", views.appointment_detail, name="appointment-detail"),
    path("admin/agendamentos/<int:pk>/editar/", views.appointment_edit, name="appointment-edit"),
    path("admin/agendamentos/<int:pk>/<slug:action>/", views.appointment_action, name="appointment-action"),
    path("admin/agendamentos/<int:appointment_pk>/pagamento/", views.payment_register, name="payment-register"),
    path("admin/servicos/novo/", views.service_create, name="service-create"),
    path("admin/servicos/<int:pk>/editar/", views.service_edit, name="service-edit"),
    path("admin/equipe/novo/", views.barber_create, name="barber-create"),
    path("admin/equipe/<int:pk>/alternar-status/", views.barber_toggle_active, name="barber-toggle-active"),
    path("admin/equipe/<int:pk>/escala/", views.barber_schedule_update, name="barber-schedule-update"),
    path("admin/equipe/<int:pk>/bloqueios/novo/", views.barber_block_create, name="barber-block-create"),
    path("admin/equipe/bloqueios/<int:pk>/remover/", views.barber_block_delete, name="barber-block-delete"),
    path("admin/equipe/<int:pk>/excluir/", views.barber_delete, name="barber-delete"),
    path("admin/financeiro/exportar.csv", views.finance_export_csv, name="finance-export-csv"),
]
