from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Baby, HospitalVisit, Illness, IllnessLog, Medication, PushSubscription, Temperature, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "name", "relation", "is_superuser", "last_login")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("아파요", {"fields": ("name", "relation", "current_baby", "notify_temperature", "notify_interval",
                             "notify_dose", "notify_quiet", "theme")}),
    )


@admin.register(Baby)
class BabyAdmin(admin.ModelAdmin):
    list_display = ("name", "birth_date", "weight_kg")
    filter_horizontal = ("guardians",)


@admin.register(Temperature)
class TemperatureAdmin(admin.ModelAdmin):
    list_display = ("baby", "recorded_at", "value", "method", "recorder_relation")
    list_filter = ("baby",)


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = ("baby", "recorded_at", "drug", "amount_ml", "recorder_relation")
    list_filter = ("baby", "drug")


admin.site.register(PushSubscription)


class IllnessLogInline(admin.TabularInline):
    model = IllnessLog
    extra = 0


@admin.register(Illness)
class IllnessAdmin(admin.ModelAdmin):
    list_display = ("baby", "title", "started_at", "cured_at")
    list_filter = ("baby",)
    inlines = [IllnessLogInline]


@admin.register(HospitalVisit)
class HospitalVisitAdmin(admin.ModelAdmin):
    list_display = ("baby", "name", "visited_at", "got_medicine")
    list_filter = ("baby",)
