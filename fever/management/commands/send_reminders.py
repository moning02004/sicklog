"""열이 나는 동안 체온 기록 알림과 해열제 가능 알림을 보낸다. 1분마다 실행한다 (CronJob / scheduler)."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.utils import timezone

from fever import dosing
from fever.models import Baby, ReminderLog
from fever.push import push_enabled, send_to_user

DOSE_WINDOW = timedelta(minutes=30)  # 먹일 수 있게 된 뒤 이 시간 안에만 알린다


def in_quiet_hours(now):
    hour = timezone.localtime(now).hour
    return hour >= 23 or hour < 7


class Command(BaseCommand):
    help = "체온 기록·해열제 가능 푸시 알림을 보낸다."

    def handle(self, *args, **options):
        if not push_enabled():
            self.stdout.write("VAPID 키가 없어 알림을 보내지 않아요.")
            return
        now = timezone.now()
        sent = 0
        for baby in Baby.objects.prefetch_related("guardians__push_subscriptions"):
            temps = list(baby.temperatures.order_by("recorded_at"))
            meds = list(baby.medications.order_by("recorded_at"))
            last_times = [r[-1].recorded_at for r in (temps, meds) if r]
            if not last_times or dosing.is_recovered(max(last_times), now):
                continue  # 아프지 않은 아이
            last_temp = temps[-1] if temps else None
            for user in baby.guardians.all():
                if not user.push_subscriptions.all():
                    continue
                sent += self.temperature_reminder(user, baby, last_temp, now)
                sent += self.dose_reminder(user, baby, meds, last_temp, now)
        self.stdout.write(f"알림 {sent}건을 보냈어요.")

    def once(self, user, baby, key):
        try:
            ReminderLog.objects.create(user=user, baby=baby, key=key)
            return True
        except IntegrityError:
            return False

    def temperature_reminder(self, user, baby, last_temp, now):
        if not user.notify_temperature or not last_temp:
            return 0
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
