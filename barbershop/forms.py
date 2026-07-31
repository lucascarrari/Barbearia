from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import Appointment, Barber, BarberTimeBlock, Payment, PaymentMethod, Service


WORK_DAY_CHOICES = [
    ("0", "Seg"),
    ("1", "Ter"),
    ("2", "Qua"),
    ("3", "Qui"),
    ("4", "Sex"),
    ("5", "Sab"),
    ("6", "Dom"),
]


class BarberScheduleMixin:
    work_days = forms.MultipleChoiceField(
        label="Dias de trabalho",
        choices=WORK_DAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        if instance and instance.pk:
            self.initial["work_days"] = instance.work_day_list

    def clean_work_days(self):
        days = self.cleaned_data["work_days"]
        if isinstance(days, str):
            days = [days]
        if not days:
            raise forms.ValidationError("Selecione pelo menos um dia de trabalho.")
        return ",".join(days)

    def clean(self):
        cleaned = super().clean()
        work_start = cleaned.get("work_start")
        work_end = cleaned.get("work_end")
        break_start = cleaned.get("break_start")
        break_end = cleaned.get("break_end")
        if work_start and work_end and work_end <= work_start:
            self.add_error("work_end", "A saida deve ser depois da entrada.")
        if bool(break_start) != bool(break_end):
            raise forms.ValidationError("Informe inicio e fim da pausa.")
        if break_start and break_end:
            if break_end <= break_start:
                self.add_error("break_end", "O fim da pausa deve ser depois do inicio.")
            if work_start and work_end and (break_start < work_start or break_end > work_end):
                raise forms.ValidationError("A pausa precisa ficar dentro do horario de trabalho.")
        return cleaned


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


class BarberForm(BarberScheduleMixin, forms.ModelForm):
    username = forms.CharField(label="Usuario de acesso", max_length=150)
    password = forms.CharField(
        label="Senha inicial",
        min_length=8,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Barber
        fields = [
            "name",
            "username",
            "password",
            "is_active",
            "work_days",
            "work_start",
            "work_end",
            "break_start",
            "break_end",
        ]
        widgets = {
            "work_start": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "work_end": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "break_start": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "break_end": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
        }

    def clean_username(self):
        username = self.cleaned_data["username"]
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Ja existe um usuario com este nome.")
        return username


class BarberScheduleForm(BarberScheduleMixin, forms.ModelForm):
    class Meta:
        model = Barber
        fields = ["work_days", "work_start", "work_end", "break_start", "break_end"]
        widgets = {
            "work_start": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "work_end": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "break_start": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "break_end": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
        }

class BarberTimeBlockForm(forms.ModelForm):
    class Meta:
        model = BarberTimeBlock
        fields = ["date", "start_time", "end_time", "reason"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "step": "1800"}),
        }

    def clean(self):
        cleaned = super().clean()
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        if start_time and end_time and end_time <= start_time:
            self.add_error("end_time", "O fim deve ser depois do inicio.")
        return cleaned


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
