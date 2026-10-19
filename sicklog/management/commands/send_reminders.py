"""아픔을 기록 중인 동안 체온 기록 알림과 해열제 가능 알림을 보낸다. 1분마다 실행한다 (CronJob / scheduler).

체온 기록 알림은 두 경우에만 보낸다.
- 마지막 체온이 미열(37.5℃) 이상일 때: 정해진 간격마다
- 해열제를 먹인 지 1시간이 지났는데 그 뒤로 체온 기록이 없을 때: 한 번
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from sicklog import dosing
from sicklog.models import Baby, ReminderLog
from sicklog.push import in_quiet_hours, push_enabled, send_to_user

DOSE_WINDOW = timedelta(minutes=30)  # 먹일 수 있게 된 뒤 이 시간 안에만 알린다
AFTER_DOSE = timedelta(hours=1)  # 해열제를 먹이고 이만큼 지나면 체온을 재 보라고 알린다
AFTER_DOSE_WINDOW = timedelta(hours=1)  # 그 뒤 이 시간 안에만 (늦게 켠 알림이 옛 복용을 알리지 않게)


class Command(BaseCommand):
    help = "체온 기록·해열제 가능 푸시 알림을 보낸다."

    def handle(self, *args, **options):
        if not push_enabled():
            self.stdout.write("VAPID 키가 없어 알림을 보내지 않아요.")
            return
        now = timezone.now()
        sent = 0
        for baby in Baby.objects.prefetch_related("guardians__push_subscriptions"):
            illness = baby.illnesses.filter(cured_at__isnull=True).first()
            if illness is None:
                continue  # 지금 아프지 않은 아이 (완치로 기록하면 알림이 멈춘다)
            temps = list(illness.temperatures.order_by("recorded_at"))
            meds = list(illness.medications.order_by("recorded_at"))
            last_temp = temps[-1] if temps else None
            last_med = meds[-1] if meds else None
            for user in baby.guardians.all():
                if not user.push_subscriptions.all():
                    continue
                followed = self.after_dose_reminder(user, baby, last_med, last_temp, now)
                sent += followed or self.temperature_reminder(user, baby, last_temp, now)
                sent += self.dose_reminder(user, baby, meds, last_temp, now)
        self.stdout.write(f"알림 {sent}건을 보냈어요.")

    def once(self, user, baby, key):
        """처음 보내는 알림이면 True. (CronJob은 동시에 하나만 돈다)"""
        _, created = ReminderLog.objects.get_or_create(user=user, baby=baby, key=key)
        return created

    def after_dose_reminder(self, user, baby, last_med, last_temp, now):
        """해열제를 먹이고 1시간이 지났는데 그 뒤 체온 기록이 없으면 한 번 알린다."""
        if not user.notify_temperature or not last_med:
            return 0
        if user.notify_quiet and in_quiet_hours(now):
            return 0
        since = now - last_med.recorded_at
        if not (AFTER_DOSE <= since < AFTER_DOSE + AFTER_DOSE_WINDOW):
            return 0
        if last_temp and last_temp.recorded_at > last_med.recorded_at:
            return 0  # 이미 재 봤다
        if not self.once(user, baby, f"after-dose:{last_med.pk}"):
            return 0
        title = f"{baby.name} 해열제를 먹인 지 1시간이 지났어요"
        return min(1, send_to_user(user, title, "체온을 재서 열이 내렸는지 확인해 볼까요?", tag=f"temp-{baby.pk}"))

    def temperature_reminder(self, user, baby, last_temp, now):
        if not user.notify_temperature or not last_temp:
            return 0
        if last_temp.value < dosing.MILD_FEVER:
            return 0  # 체온이 높지 않으면 재 보라고 하지 않는다
        if user.notify_quiet and in_quiet_hours(now):
            return 0
        interval = timedelta(minutes=user.notify_interval)
        elapsed = now - last_temp.recorded_at
        if elapsed < interval:
            return 0
        step = int(elapsed / interval)
        if not self.once(user, baby, f"temp:{last_temp.pk}:{user.notify_interval}:{step}"):
            return 0
        body = (f"마지막 체온 {last_temp.value}℃ ({dosing.humanize_ago(elapsed)}). 지금 재고 기록해 주세요.")
        return min(1, send_to_user(user, f"{baby.name} 체온 잴 시간이에요", body, tag=f"temp-{baby.pk}"))

    def dose_reminder(self, user, baby, meds, last_temp, now):
        if not user.notify_dose or not meds:
            return 0
        count = 0
        for cls in ("acet", "ibu"):
            nd = dosing.next_dose(meds, cls, now)
            at = nd["available_at"]
            if not at or nd["full"] or not (at <= now < at + DOSE_WINDOW):
                continue
            if not self.once(user, baby, f"dose:{cls}:{int(at.timestamp())}"):
                continue
            if last_temp and last_temp.value < dosing.FEVER:
                body = f"지금 체온 {last_temp.value}℃로 높지 않으면 먹이지 않아도 돼요."
            else:
                body = "체온을 먼저 재고 38℃ 이상이면 먹여 주세요."
            title = f"{baby.name}에게 {nd['klass'].drugs}을 먹일 수 있어요"
            count += min(1, send_to_user(user, title, body, tag=f"dose-{baby.pk}-{cls}"))
        return count
