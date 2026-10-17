from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import RELATION_CHOICES, Baby, Medication, Temperature, User


class RecordedAtMixin:
    """비어 있으면 지금, 미래 시각은 거절."""

    def clean_recorded_at(self):
        value = self.cleaned_data.get("recorded_at")
        now = timezone.now()
        if not value:
            return now
        if value > now + timedelta(minutes=1):
            raise forms.ValidationError("아직 오지 않은 시간이에요")
        return value


class TemperatureForm(RecordedAtMixin, forms.ModelForm):
    recorded_at = forms.DateTimeField(required=False, input_formats=["%Y-%m-%dT%H:%M"])

    class Meta:
        model = Temperature
        fields = ["value", "method", "recorded_at"]


class MedicationForm(RecordedAtMixin, forms.ModelForm):
    recorded_at = forms.DateTimeField(required=False, input_formats=["%Y-%m-%dT%H:%M"])

    class Meta:
        model = Medication
        fields = ["drug", "amount_ml", "recorded_at"]


class BabyForm(forms.ModelForm):
    class Meta:
        model = Baby
        fields = ["name", "birth_date", "weight_kg"]

    def clean_birth_date(self):
        value = self.cleaned_data["birth_date"]
        if value > timezone.localdate():
            raise forms.ValidationError("생년월일을 다시 확인해 주세요")
        return value


class WeightForm(forms.Form):
    weight_kg = forms.DecimalField(min_value=Decimal("1.0"), max_value=Decimal("60.0"), decimal_places=1)


class UserCreateForm(forms.Form):
    name = forms.CharField(max_length=50, error_messages={"required": "이름을 입력해 주세요."})
    relation = forms.ChoiceField(
        choices=[(r, r) for r in RELATION_CHOICES], error_messages={"required": "관계를 골라 주세요."}
    )
    username = forms.RegexField(
        regex=r"^[a-z0-9_]{3,20}$",
        error_messages={"required": "아이디를 입력해 주세요.", "invalid": "아이디는 영문 소문자, 숫자, _로 3–20자예요."},
    )

    def clean_username(self):
        username = self.cleaned_data["username"].lower()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("이미 있는 아이디예요.")
        return username

    def clean_name(self):
        return self.cleaned_data["name"].strip()


class NotificationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["notify_temperature", "notify_interval", "notify_dose", "notify_quiet"]
