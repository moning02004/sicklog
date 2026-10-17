from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

RELATION_CHOICES = ["엄마", "아빠", "할머니", "할아버지", "이모", "고모", "삼촌"]
BABY_COLORS = ["warn", "ok", "ibu", "acet", "dad", "mom"]


def relation_color(relation):
    return {"엄마": "mom", "아빠": "dad", "관리자": "accent"}.get(relation, "ok")


class User(AbstractUser):
    class Theme(models.TextChoices):
        SYSTEM = "system", "기기 설정"
        LIGHT = "light", "밝게"
        DARK = "dark", "어둡게"

    name = models.CharField("이름", max_length=50, blank=True)
    relation = models.CharField("관계", max_length=20, blank=True)
    current_baby = models.ForeignKey(
        "Baby", verbose_name="보고 있는 자녀", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    notify_temperature = models.BooleanField("체온 기록 알림", default=True)
    notify_interval = models.PositiveSmallIntegerField(
        "체온 알림 간격(분)", default=60, choices=[(30, "30분"), (60, "1시간"), (120, "2시간")]
    )
    notify_dose = models.BooleanField("해열제 가능 알림", default=True)
    notify_quiet = models.BooleanField("밤에는 조용히", default=False)
    theme = models.CharField("화면 모드", max_length=10, choices=Theme.choices, default=Theme.SYSTEM)

    @property
    def display_name(self):
        return self.name or self.username

    @property
    def relation_label(self):
        return self.relation or ("관리자" if self.is_superuser else "가족")

    @property
    def color(self):
        return relation_color(self.relation_label)

    def accessible_babies(self):
        if self.is_superuser:
            return Baby.objects.all()
        return self.babies.all()


class Baby(models.Model):
    name = models.CharField("이름", max_length=30)
    birth_date = models.DateField("생년월일")
    weight_kg = models.DecimalField(
        "몸무게(kg)", max_digits=4, decimal_places=1,
        validators=[MinValueValidator(Decimal("1.0")), MaxValueValidator(Decimal("60.0"))],
    )
    weight_updated_at = models.DateTimeField("몸무게 변경일", default=timezone.now)
    guardians = models.ManyToManyField(settings.AUTH_USER_MODEL, verbose_name="보호자", related_name="babies", blank=True)
    color = models.CharField(max_length=10, default="warn")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["birth_date", "id"]
        verbose_name = verbose_name_plural = "아기"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.pk and not kwargs.get("update_fields"):
            self.color = BABY_COLORS[Baby.objects.count() % len(BABY_COLORS)]
        super().save(*args, **kwargs)

    @property
    def age_label(self):
        today = timezone.localdate()
        months = (today.year - self.birth_date.year) * 12 + today.month - self.birth_date.month
        if today.day < self.birth_date.day:
            months -= 1
        months = max(months, 0)
        return f"{months}개월" if months < 24 else f"{months // 12}살"

    @property
    def initial(self):
        return self.name[:1]


class RecordBase(models.Model):
    """체온·해열제 기록 공통 필드.

    기록은 아이의 것이다. 기록자는 참고용으로만 남기며, 기록 당시의 이름과 관계를 복사해 두어
    사용자가 삭제되어도 기록은 그대로 남는다.
    """

    baby = models.ForeignKey(Baby, on_delete=models.CASCADE, related_name="%(class)ss")
    recorded_at = models.DateTimeField("시각", default=timezone.now, db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)ss"
    )
    recorder_name = models.CharField(max_length=50, blank=True)
    recorder_relation = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-recorded_at"]

    def save(self, *args, **kwargs):
        if self.recorded_by and not self.recorder_relation:
            self.recorder_name = self.recorded_by.display_name
            self.recorder_relation = self.recorded_by.relation_label
        super().save(*args, **kwargs)

    @property
    def recorder_color(self):
        return relation_color(self.recorder_relation)


class Temperature(RecordBase):
    class Method(models.TextChoices):
        EAR = "ear", "귀"
        ARMPIT = "armpit", "겨드랑이"
        FOREHEAD = "forehead", "이마"

    kind = "temp"
    value = models.DecimalField(
        "체온", max_digits=3, decimal_places=1,
        validators=[MinValueValidator(Decimal("34.0")), MaxValueValidator(Decimal("43.0"))],
    )
    method = models.CharField("측정 부위", max_length=10, choices=Method.choices, default=Method.EAR)

    class Meta(RecordBase.Meta):
        verbose_name = verbose_name_plural = "체온 기록"

    def __str__(self):
        return f"{self.baby} {self.value}℃"


class Medication(RecordBase):
    class Drug(models.TextChoices):
        TYLENOL = "tylenol", "타이레놀"
        MAXIBUPEN = "maxibupen", "맥시부펜"
        IBUPROFEN = "ibuprofen", "이부프로펜"

    kind = "med"
    drug = models.CharField("해열제", max_length=20, choices=Drug.choices)
    amount_ml = models.DecimalField(
        "먹인 양(mL)", max_digits=4, decimal_places=1,
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("40.0"))],
    )

    class Meta(RecordBase.Meta):
        verbose_name = verbose_name_plural = "해열제 기록"

    def __str__(self):
        return f"{self.baby} {self.get_drug_display()} {self.amount_ml}mL"


class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.CharField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "푸시 구독"


class ReminderLog(models.Model):
    """같은 알림을 두 번 보내지 않도록 보낸 기록을 남긴다."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    baby = models.ForeignKey(Baby, on_delete=models.CASCADE)
    key = models.CharField(max_length=80)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "baby", "key"], name="unique_reminder")]
