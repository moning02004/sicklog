"""로컬 확인용 예시 데이터. 운영에서는 실행하지 않는다."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from sicklog.models import Baby, HospitalVisit, Illness, IllnessLog, Medication, Temperature, User


class Command(BaseCommand):
    help = "엄마·아빠 계정(비밀번호 0000)과 아기 두 명, 예시 아픔·병원 기록을 만든다."

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

        def illness(baby, title, start, by, symptoms, later=(), cured=None):
            ill = Illness.objects.create(baby=baby, title=title, started_at=ago(start),
                                         recorded_by=by, symptoms=list(symptoms), cured_at=ago(cured) if cured else None)
            IllnessLog.objects.create(illness=ill, kind="start", detail=title, recorded_at=ill.started_at, half_day=True, recorded_by=by)
            for s in symptoms:
                IllnessLog.objects.create(illness=ill, kind="add", symptom=s, recorded_at=ill.started_at, half_day=True, recorded_by=by)
            for minutes, kind, s, who in later:
                IllnessLog.objects.create(illness=ill, kind=kind, symptom=s, recorded_at=ago(minutes), recorded_by=who)
                ill.symptoms = [x for x in ill.symptoms if x != s] + ([s] if kind == "add" else [])
            if cured:
                IllnessLog.objects.create(illness=ill, kind="cure", recorded_at=ago(cured), half_day=True, recorded_by=by)
            ill.save()
            return ill

        cold = illness(haru, "감기", 1160, mom, ["발열", "콧물"], later=[(500, "add", "기침", dad), (120, "add", "중이염", mom)])
        for m, v, by in [(1150, 37.9, dad), (1030, 38.9, mom), (900, 38.2, mom), (760, 37.6, dad), (600, 38.4, mom),
                         (420, 38.7, mom), (300, 37.9, mom), (200, 37.5, dad), (100, 38.6, dad), (40, 37.9, mom), (10, 37.6, mom)]:
            Temperature.objects.create(baby=haru, illness=cold, recorded_at=ago(m), value=Decimal(str(v)), recorded_by=by)
        for m, drug, ml, by in [(1025, "tylenol", 4.5, mom), (595, "maxibupen", 5.0, mom),
                                (415, "tylenol", 4.5, mom), (95, "maxibupen", 5.0, dad)]:
            Medication.objects.create(baby=haru, illness=cold, recorded_at=ago(m), drug=drug, amount_ml=Decimal(str(ml)), recorded_by=by)
        HospitalVisit.objects.create(baby=haru, illness=cold, visited_at=ago(480), name="우리소아청소년과",
                                     location="분당구 정자동", got_medicine=True, medicine_note="해열제, 콧물약 3일분",
                                     memo="3일 뒤에도 열 나면 다시 오라고 함", recorded_by=mom)

        flu = illness(bom, "장염", 16010, mom, ["발열", "구토"],
                      later=[(15500, "add", "설사", dad), (14600, "remove", "구토", mom), (14100, "remove", "발열", mom)],
                      cured=13900)
        for m, v, by in [(16000, 38.2, mom), (15700, 38.8, dad), (15300, 37.8, mom), (14800, 38.3, mom), (14000, 37.1, mom)]:
            Temperature.objects.create(baby=bom, illness=flu, recorded_at=ago(m), value=Decimal(str(v)), recorded_by=by)
        Medication.objects.create(baby=bom, illness=flu, recorded_at=ago(15990), drug="tylenol", amount_ml=Decimal("6.5"), recorded_by=mom)
        Medication.objects.create(baby=bom, illness=flu, recorded_at=ago(15640), drug="ibuprofen", amount_ml=Decimal("5.5"), recorded_by=dad)
        HospitalVisit.objects.create(baby=bom, illness=flu, visited_at=ago(15400), name="우리소아청소년과",
                                     location="분당구 정자동", got_medicine=True, medicine_note="정장제, 해열제",
                                     recorded_by=dad)
        self.stdout.write(self.style.SUCCESS("예시 데이터를 만들었어요. haru_mom / haru_dad, 비밀번호 0000"))
