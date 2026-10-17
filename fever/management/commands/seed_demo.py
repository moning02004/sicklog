"""로컬 확인용 예시 데이터. 운영에서는 실행하지 않는다."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from fever.models import Baby, Medication, Temperature, User


class Command(BaseCommand):
    help = "엄마·아빠 계정(비밀번호 0000)과 아기 두 명, 예시 기록을 만든다."

    def handle(self, *args, **options):
        mom, _ = User.objects.get_or_create(username="haru_mom", defaults={"name": "김서윤", "relation": "엄마"})
        dad, _ = User.objects.get_or_create(username="haru_dad", defaults={"name": "이준호", "relation": "아빠"})
        for u in (mom, dad):
            u.set_password("0000")
            u.save()
        if Baby.objects.exists():
            self.stdout.write("아기 데이터가 이미 있어 기록은 만들지 않았어요.")
            return
        now = timezone.now()
        ago = lambda m: now - timedelta(minutes=m)

        haru = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        bom = Baby.objects.create(name="봄이", birth_date=date(2023, 5, 14), weight_kg=Decimal("13.6"))
        for baby in (haru, bom):
            baby.guardians.add(mom, dad)
        for u in (mom, dad):
            u.current_baby = haru
            u.save(update_fields=["current_baby"])

        def t(baby, m, v, by, method="ear"):
            Temperature.objects.create(baby=baby, recorded_at=ago(m), value=Decimal(str(v)), recorded_by=by, method=method)

        def d(baby, m, drug, ml, by):
            Medication.objects.create(baby=baby, recorded_at=ago(m), drug=drug, amount_ml=Decimal(str(ml)), recorded_by=by)

        for m, v, by in [(1150, 37.9, dad), (1030, 38.9, mom), (900, 38.2, mom), (760, 37.6, dad), (600, 38.4, mom),
                         (420, 38.7, mom), (300, 37.9, mom), (200, 37.5, dad), (100, 38.6, dad), (40, 37.9, mom), (10, 37.6, mom)]:
            t(haru, m, v, by)
        for m, drug, ml, by in [(1025, "tylenol", 4.5, mom), (595, "maxibupen", 5.0, mom),
                                (415, "tylenol", 4.5, mom), (95, "maxibupen", 5.0, dad)]:
            d(haru, m, drug, ml, by)
        for m, v, by in [(16000, 38.2, mom), (15700, 38.8, dad), (15300, 37.8, mom), (14800, 38.3, mom), (14000, 37.1, mom)]:
            t(bom, m, v, by)
        d(bom, 15990, "tylenol", 6.5, mom)
        d(bom, 15640, "ibuprofen", 5.5, dad)
        self.stdout.write(self.style.SUCCESS("예시 데이터를 만들었어요. haru_mom / haru_dad, 비밀번호 0000"))
