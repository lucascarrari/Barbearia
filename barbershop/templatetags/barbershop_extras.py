from django import template
from django.utils.http import urlencode

from barbershop.services import currency_brl

register = template.Library()


@register.filter
def brl(value):
    return currency_brl(value)


@register.filter
def chart_height(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0
    return max(12, min(160, int(amount / 8)))


@register.filter
def whatsapp_phone(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if len(digits) in {10, 11}:
        return f"55{digits}"
    return digits


@register.simple_tag
def appointment_whatsapp_url(appointment):
    phone = whatsapp_phone(appointment.phone)
    if not phone:
        return ""
    message = (
        f"Ola, {appointment.client_name}! Passando para reforcar seu agendamento "
        f"na Barbearia Tio Bigode: {appointment.service_name_snapshot} com "
        f"{appointment.barber.name}, no dia {appointment.date:%d/%m/%Y} as "
        f"{appointment.start_time:%H:%M}. Se precisar remarcar, fale conosco por aqui."
    )
    return f"https://wa.me/{phone}?{urlencode({'text': message})}"
