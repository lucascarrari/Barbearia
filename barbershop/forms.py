from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import Appointment, Barber, Payment, PaymentMethod, Service


class AdminLoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"placeholder": "Usuario"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"placeholder": "Senha"}))


class PublicAppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "client_name",
            "phone",
            "email",
            "barber",
            "service",
            "date",
            "start_time",
            "notes",
            "payment_method",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["barber"].queryset = Barber.objects.filter(is_active=True)
        self.fields["email"].required = False
        self.fields["notes"].required = False


class AppointmentFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Busca")
    date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    barber = forms.ModelChoiceField(required=False, queryset=Barber.objects.none())
    service = forms.ModelChoiceField(required=False, queryset=Service.objects.none())
    status = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(Appointment._meta.get_field("status").choices))
    payment_status = forms.ChoiceField(
        required=False,
        choices=[("", "Todos")] + list(Appointment._meta.get_field("payment_status").choices),
    )
    view = forms.ChoiceField(
        required=False,
        choices=[("list", "Lista"), ("day", "Dia"), ("week", "Semana"), ("month", "Mes")],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["barber"].queryset = Barber.objects.filter(is_active=True)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)


class AppointmentAdminForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "client_name",
            "phone",
            "email",
            "barber",
            "service",
            "date",
            "start_time",
            "duration_minutes",
            "notes",
            "status",
            "payment_method",
            "payment_status",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "description", "price", "duration_minutes", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class BarberForm(forms.ModelForm):
    username = forms.CharField(label="Usuario de acesso", max_length=150)
    password = forms.CharField(
        label="Senha inicial",
        min_length=8,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Barber
        fields = ["name", "username", "password", "is_active"]

    def clean_username(self):
        username = self.cleaned_data["username"]
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Ja existe um usuario com este nome.")
        return username


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["method", "status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, appointment=None, **kwargs):
        self.appointment = appointment
        super().__init__(*args, **kwargs)
        self.fields["method"].choices = PaymentMethod.choices

    def save(self, commit=True):
        payment = super().save(commit=False)
        if self.appointment:
            payment.appointment = self.appointment
            payment.amount = self.appointment.service_price
        if commit:
            payment.save()
        return payment
