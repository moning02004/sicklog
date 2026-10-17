from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

RELATION_CHOICES = ["엄마", "아빠", "할머니", "할아버지", "이모", "고모", "삼촌"]
ILLNESS_TITLES = ["감기", "독감", "코로나19", "장염", "수족구", "중이염", "구내염", "기관지염", "폐렴", "결막염"]
SYMPTOMS = ["발열", "콧물", "코막힘", "기침", "가래", "목 아픔", "오한", "두통", "구토", "설사", "복통", "발진",
            "귀 아픔", "눈곱", "식욕 없음", "처짐"]
# 감기가 번져서 생기는 병. 아픔을 따로 만들지 않고 같은 아픔 안에서 증상처럼 기록한다.
COMPLICATIONS = ["중이염", "부비동염", "기관지염", "모세기관지염", "폐렴", "크룹", "결막염", "장염"]
BABY_COLORS = ["warn", "ok", "ibu", "acet", "dad", "mom"]


def half_key(moment):
    """반나절 단위 비교 값: (날짜, 오후 여부). 날짜와 오전/오후만 고르는 기록끼리 비교할 때 쓴다."""
    local = timezone.localtime(moment)
    return local.date(), local.hour >= 12


def latest_first(visits):
    """병원 기록을 방문한 반나절이 늦은 순으로, 같으면 나중에 만든 순으로."""
    return sorted(visits, key=lambda v: (half_key(v.visited_at), v.pk), reverse=True)


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


class RecorderMixin(models.Model):
    """기록자는 참고용으로만 남긴다. 기록 당시의 이름과 관계를 복사해 두어 사용자가 삭제되어도 기록은 그대로 남는다."""

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)ss"
    )
    recorder_name = models.CharField(max_length=50, blank=True)
    recorder_relation = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.recorded_by and not self.recorder_relation:
            self.recorder_name = self.recorded_by.display_name
            self.recorder_relation = self.recorded_by.relation_label
        super().save(*args, **kwargs)

    @property
    def recorder_color(self):
        return relation_color(self.recorder_relation)


class Illness(RecorderMixin):
    """아픔: 감기·독감처럼 아픈 기간 하나. 보호자가 '완치로 기록'할 때까지 이어진다."""

    baby = models.ForeignKey(Baby, on_delete=models.CASCADE, related_name="illnesses")
    title = models.CharField("이름", max_length=40)
    symptoms = models.JSONField("지금 증상", default=list, blank=True)
    # 날짜와 오전/오후만 고른다. 오전은 9시, 오후는 15시로 저장한다 (오늘의 지금 반나절이면 지금 시각).
    started_at = models.DateTimeField("아프기 시작한 때", default=timezone.now)
    cured_at = models.DateTimeField("다 나은 때", null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        verbose_name = verbose_name_plural = "아픔"
        constraints = [
            models.UniqueConstraint(fields=["baby"], condition=models.Q(cured_at__isnull=True), name="one_active_illness"),
        ]

    def __str__(self):
        return f"{self.baby} {self.title}"

    @property
    def is_active(self):
        return self.cured_at is None

    @property
    def started_on(self):
        return timezone.localtime(self.started_at).date()

    @property
    def cured_on(self):
        return timezone.localtime(self.cured_at).date() if self.cured_at else None

    @property
    def ended_at(self):
        return self.cured_at

    @property
    def days(self):
        end = self.cured_on or timezone.localdate()
        return (end - self.started_on).days + 1


class IllnessLog(RecorderMixin):
    """증상이 언제 생기고 나아졌는지 남기는 로그."""

    class Kind(models.TextChoices):
        START = "start", "시작"
        ADD = "add", "증상 생김"
        REMOVE = "remove", "증상 나아짐"
        TITLE = "title", "이름 바뀜"
        CURE = "cure", "완치"
        REOPEN = "reopen", "완치 취소"

    illness = models.ForeignKey(Illness, on_delete=models.CASCADE, related_name="logs")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    symptom = models.CharField(max_length=30, blank=True)
    detail = models.CharField(max_length=80, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now)
    half_day = models.BooleanField(default=False)  # 날짜와 오전/오후만 아는 기록

    class Meta:
        ordering = ["-recorded_at", "-id"]


class RecordBase(RecorderMixin):
    """체온·해열제 기록 공통 필드. 기록은 아이의 것이다."""

    baby = models.ForeignKey(Baby, on_delete=models.CASCADE, related_name="%(class)ss")
    illness = models.ForeignKey(Illness, null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)ss")
    recorded_at = models.DateTimeField("시각", default=timezone.now, db_index=True)

    class Meta:
        abstract = True
        ordering = ["-recorded_at"]


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


class HospitalVisit(RecorderMixin):
    """병원 기록: 언제 어느 병원에 갔는지, 약을 받았는지."""

    baby = models.ForeignKey(Baby, on_delete=models.CASCADE, related_name="visits")
    illness = models.ForeignKey(Illness, null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    visited_at = models.DateTimeField("방문한 때", default=timezone.now)
    name = models.CharField("병원 이름", max_length=60)
    location = models.CharField("위치", max_length=100, blank=True)
    got_medicine = models.BooleanField("약 받음", default=False)
    medicine_note = models.CharField("받은 약", max_length=200, blank=True)
    memo = models.CharField("메모", max_length=300, blank=True)

    class Meta:
        ordering = ["-visited_at", "-id"]
        verbose_name = verbose_name_plural = "병원 기록"

    def __str__(self):
        return f"{self.baby} {self.name}"

    @property
    def visited_on(self):
        return timezone.localtime(self.visited_at).date()


class VisitPhoto(models.Model):
    """약 봉지 사진. 여러 대의 웹 서버가 같이 볼 수 있도록 DB에 저장한다 (화면에서 줄여서 올림)."""

    visit = models.ForeignKey(HospitalVisit, on_delete=models.CASCADE, related_name="photos")
    content_type = models.CharField(max_length=30)
    data = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


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
