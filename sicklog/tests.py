from datetime import date, datetime, timedelta
from io import StringIO
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import dosing
from .models import Baby, HospitalVisit, Illness, IllnessLog, Medication, Temperature, User


class DosingTests(TestCase):
    def setUp(self):
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.now = timezone.now()

    def med(self, minutes_ago, drug):
        return Medication.objects.create(baby=self.baby, drug=drug, amount_ml=Decimal("5"),
                                         recorded_at=self.now - timedelta(minutes=minutes_ago))

    def test_dose_range_uses_weight_and_concentration(self):
        r = dosing.dose_range(Decimal("10.2"), "tylenol")
        self.assertEqual((r["ml_min"], r["ml_max"]), (Decimal("3.2"), Decimal("4.8")))

    def test_cross_dosing_waits_two_hours_after_other_class(self):
        meds = [self.med(415, "tylenol"), self.med(95, "maxibupen")]
        acet = dosing.next_dose(meds, "acet", self.now)
        self.assertFalse(acet["ready"])
        self.assertEqual(acet["reason"], "cross")
        self.assertEqual(acet["available_at"], meds[1].recorded_at + timedelta(hours=2))

    def test_maxibupen_and_ibuprofen_share_six_hour_gap(self):
        meds = [self.med(300, "maxibupen")]
        ibu = dosing.next_dose(meds, "ibu", self.now)
        self.assertEqual(ibu["reason"], "same")
        self.assertEqual(ibu["available_at"], meds[0].recorded_at + timedelta(hours=6))


class ViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", password="0000", name="관리자")
        self.mom = User.objects.create_user(username="haru_mom", password="0000", name="김서윤", relation="엄마")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom)
        self.illness = Illness.objects.create(baby=self.baby, title="감기", symptoms=["발열"], recorded_by=self.mom)

    def test_pages_render(self):
        self.client.force_login(self.mom)
        Temperature.objects.create(baby=self.baby, value=Decimal("38.6"), recorded_by=self.mom)
        for name in ("home", "history", "guide", "settings", "baby_list", "baby_create", "visit_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("baby_detail", args=[self.baby.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("illness_detail", args=[self.illness.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("illness_edit", args=[self.illness.pk])).status_code, 200)
        self.assertEqual(self.client.get(f"{reverse('history')}?tab=visits").status_code, 200)

    def test_login_required(self):
        self.assertRedirects(self.client.get(reverse("home")), f"{reverse('login')}?next=/")

    def test_record_temperature_keeps_recorder_snapshot(self):
        self.client.force_login(self.mom)
        self.client.post(reverse("temperature_create"), {"value": "38.4", "method": "ear"})
        record = Temperature.objects.get()
        self.assertEqual((record.recorder_relation, record.recorder_name), ("엄마", "김서윤"))
        self.assertEqual(record.illness, self.illness)

    def test_future_time_is_rejected(self):
        self.client.force_login(self.mom)
        future = (timezone.localtime() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("temperature_create"), {"value": "38.4", "method": "ear", "recorded_at": future})
        self.assertFalse(Temperature.objects.exists())

    def test_admin_adds_user_with_default_password(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("user_add"), {"name": "박순자", "relation": "할머니", "username": "haru_grandma"})
        self.assertTrue(User.objects.get(username="haru_grandma").check_password("0000"))

    def test_delete_user_keeps_records_by_default(self):
        Temperature.objects.create(baby=self.baby, value=Decimal("38.6"), recorded_by=self.mom)
        self.client.force_login(self.admin)
        self.client.post(reverse("user_delete", args=[self.mom.pk]), {"records": "keep"})
        record = Temperature.objects.get()
        self.assertIsNone(record.recorded_by)
        self.assertEqual(record.recorder_relation, "엄마")

    def test_delete_user_with_records(self):
        Temperature.objects.create(baby=self.baby, value=Decimal("38.6"), recorded_by=self.mom)
        self.client.force_login(self.admin)
        self.client.post(reverse("user_delete", args=[self.mom.pk]), {"records": "delete"})
        self.assertFalse(Temperature.objects.exists())

    def test_non_guardian_cannot_see_baby(self):
        other = User.objects.create_user(username="other", password="0000")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("baby_detail", args=[self.baby.pk])).status_code, 404)

    def test_seed_demo_runs(self):
        Baby.objects.all().delete()
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Baby.objects.count(), 2)
        self.assertEqual(Temperature.objects.count(), 16)
        self.assertEqual(Illness.objects.filter(cured_at__isnull=True).count(), 1)




class IllnessTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.dad = User.objects.create_user(username="haru_dad", password="0000", relation="아빠")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom, self.dad)
        self.client.force_login(self.mom)

    def start(self, **extra):
        data = {"title": "감기", "symptoms": ["콧물", "발열"], **extra}
        return self.client.post(reverse("illness_create"), data)

    def test_home_without_illness_offers_new_record(self):
        res = self.client.get(reverse("home"))
        self.assertContains(res, "지금은 아프지 않아요")
        self.assertContains(res, reverse("illness_create"))

    def test_temperature_needs_active_illness(self):
        self.client.post(reverse("temperature_create"), {"value": "38.4", "method": "ear"})
        self.assertFalse(Temperature.objects.exists())

    def test_create_logs_start_and_symptoms(self):
        self.start()
        illness = Illness.objects.get()
        self.assertEqual(illness.symptoms, ["콧물", "발열"])
        # 최근 것이 먼저
        self.assertEqual(list(illness.logs.values_list("kind", "symptom")),
                         [("add", "발열"), ("add", "콧물"), ("start", "")])
        self.assertTrue(all(illness.logs.values_list("half_day", flat=True)))

    def test_other_guardian_sees_active_illness_first(self):
        self.start()
        self.client.force_login(self.dad)
        res = self.client.get(reverse("home"))
        self.assertContains(res, "지금 아파요")
        self.assertContains(res, "감기")

    def test_edit_logs_added_and_removed_symptoms_at_chosen_time(self):
        self.start(started_at=f"{timezone.localdate() - timedelta(days=2)} am")
        illness = Illness.objects.get()
        day = timezone.localdate() - timedelta(days=1)
        self.client.post(reverse("illness_edit", args=[illness.pk]),
                         {"title": "독감", "symptoms": ["발열", "기침"], "changed_at": f"{day} pm"})
        illness.refresh_from_db()
        self.assertEqual((illness.title, illness.symptoms), ("독감", ["발열", "기침"]))
        added = illness.logs.get(kind="add", symptom="기침")
        self.assertEqual(timezone.localtime(added.recorded_at).date(), day)
        self.assertTrue(added.half_day)
        self.assertEqual(timezone.localtime(added.recorded_at).hour, 15)
        self.assertTrue(illness.logs.filter(kind="remove", symptom="콧물").exists())
        self.assertTrue(illness.logs.filter(kind="title", detail="감기 → 독감").exists())

    def test_cure_is_manual_and_can_be_backdated(self):
        self.start(started_at=f"{timezone.localdate() - timedelta(days=4)} am")
        illness = Illness.objects.get()
        cured = timezone.localdate() - timedelta(days=1)
        self.client.post(reverse("illness_cure", args=[illness.pk]), {"cured_at": f"{cured} pm"})
        illness.refresh_from_db()
        self.assertEqual(illness.cured_on, cured)
        self.assertEqual(illness.days, 4)
        self.assertContains(self.client.get(reverse("home")), "지금은 아프지 않아요")

    def test_only_one_active_illness(self):
        self.start()
        self.start(title="독감")
        self.assertEqual(Illness.objects.count(), 1)

    def test_visit_with_photo(self):
        self.start()
        jpeg = SimpleUploadedFile("pill.jpg", b"\xff\xd8\xff\xe0fakejpeg", content_type="image/jpeg")
        self.client.post(reverse("visit_create"), {"name": "우리소아청소년과", "location": "정자동",
                                                   "got_medicine": "on", "medicine_note": "콧물약", "photos": [jpeg]})
        visit = HospitalVisit.objects.get()
        self.assertEqual(visit.illness, Illness.objects.get())
        photo = visit.photos.get()
        res = self.client.get(reverse("visit_photo", args=[photo.pk]))
        self.assertEqual(res["Content-Type"], "image/jpeg")

    def test_visit_rejects_non_image(self):
        bad = SimpleUploadedFile("x.txt", b"hello", content_type="text/plain")
        self.client.post(reverse("visit_create"), {"name": "병원", "got_medicine": "on", "photos": [bad]})
        self.assertFalse(HospitalVisit.objects.exists())

    def test_photo_hidden_from_other_family(self):
        visit = HospitalVisit.objects.create(baby=self.baby, name="병원")
        photo = visit.photos.create(content_type="image/jpeg", data=b"\xff\xd8\xff")
        other = User.objects.create_user(username="other", password="0000")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("visit_photo", args=[photo.pk])).status_code, 404)


class DateOnlyTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom)
        self.client.force_login(self.mom)

    def test_visit_date_only(self):
        day = timezone.localdate() - timedelta(days=10)
        self.client.post(reverse("visit_create"), {"name": "우리소아청소년과", "visited_at": f"{day} am"})
        visit = HospitalVisit.objects.get()
        self.assertEqual((visit.visited_on, timezone.localtime(visit.visited_at).hour), (day, 9))

    def test_future_day_rejected(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.client.post(reverse("illness_create"), {"title": "감기", "started_at": f"{tomorrow} am"})
        self.assertFalse(Illness.objects.exists())

    def test_complication_shown_in_same_illness(self):
        self.client.post(reverse("illness_create"), {"title": "감기", "symptoms": ["콧물"]})
        illness = Illness.objects.get()
        self.client.post(reverse("illness_edit", args=[illness.pk]), {"title": "감기", "symptoms": ["콧물", "중이염"]})
        res = self.client.get(reverse("home"))
        self.assertContains(res, "bg-warnsoft text-[13px] font-semibold text-warn\">중이염")


class NewIllnessHomeTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom)
        old = Illness.objects.create(baby=self.baby, title="장염", started_at=timezone.now() - timedelta(days=9),
                                     cured_at=timezone.now() - timedelta(days=7))
        Temperature.objects.create(baby=self.baby, illness=old, value=Decimal("38.9"),
                                   recorded_at=timezone.now() - timedelta(days=8))
        Medication.objects.create(baby=self.baby, illness=old, drug="tylenol", amount_ml=Decimal("3.0"),
                                  recorded_at=timezone.now() - timedelta(days=8))
        self.client.force_login(self.mom)
        self.client.post(reverse("illness_create"), {"title": "감기"})

    def test_new_illness_asks_for_temperature(self):
        res = self.client.get(reverse("home"))
        self.assertContains(res, "열이 있나요?")
        self.assertNotContains(res, "38.9")

    def test_medicine_defaults_to_last_amount(self):
        res = self.client.get(reverse("home"))
        self.assertEqual(res.context["sheet_data"]["drugs"]["tylenol"]["lastMl"], 3.0)
        self.assertIsNone(res.context["sheet_data"]["drugs"]["maxibupen"]["lastMl"])


class AjaxFormTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom)
        self.client.force_login(self.mom)

    def post(self, name, data, *args):
        return self.client.post(reverse(name, args=args), data, HTTP_X_REQUESTED_WITH="fetch")

    def test_success_returns_message_without_storing_it(self):
        res = self.post("illness_create", {"title": "감기"})
        self.assertEqual(res.json()["ok"], True)
        self.assertIn("감기", res.json()["message"])
        self.assertNotContains(self.client.get(reverse("home")), 'id="flash"')

    def test_error_returns_message(self):
        res = self.post("illness_create", {"title": ""})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"], "어떤 아픔인지 골라 주세요")


class HalfDayTests(TestCase):
    def test_half_label(self):
        from sicklog.templatetags.sick_tags import half
        moment = timezone.make_aware(datetime(2026, 5, 12, 15, 0))
        self.assertEqual(half(moment), "5월 12일 오후")

    def test_today_future_half_rejected(self):
        from sicklog.illness_views import FormError, parse_half
        local = timezone.localtime()
        if local.hour >= 12:
            self.skipTest("오전에만 확인할 수 있어요")
        with self.assertRaises(FormError):
            parse_half(f"{local.date()} pm")


class SameHalfDayTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="봄이", birth_date=date(2023, 5, 14), weight_kg=Decimal("13.6"))
        self.baby.guardians.add(self.mom)
        self.client.force_login(self.mom)
        self.local = timezone.localtime()
        # 같은 반나절의 대표 시각이 지금보다 뒤일 수도 있다 (예: 새벽에 '오전 9시'로 저장된 시작)
        self.later_same_half = self.local.replace(hour=11 if self.local.hour < 12 else 23, minute=0)
        self.half = "pm" if self.local.hour >= 12 else "am"

    def test_cure_in_same_half_as_start(self):
        illness = Illness.objects.create(baby=self.baby, title="감기", started_at=self.later_same_half)
        self.client.post(reverse("illness_cure", args=[illness.pk]), {"cured_at": f"{self.local.date()} {self.half}"})
        illness.refresh_from_db()
        self.assertIsNotNone(illness.cured_at)
        self.assertGreaterEqual(illness.cured_at, illness.started_at)

    def test_home_shows_latest_visit_and_newest_on_tie(self):
        illness = Illness.objects.create(baby=self.baby, title="감기")
        HospitalVisit.objects.create(baby=self.baby, illness=illness, name="먼저 만든 병원", visited_at=self.later_same_half)
        HospitalVisit.objects.create(baby=self.baby, illness=illness, name="나중에 만든 병원", visited_at=timezone.now())
        HospitalVisit.objects.create(baby=self.baby, illness=illness, name="어제 병원",
                                     visited_at=timezone.now() - timedelta(days=1))
        res = self.client.get(reverse("home"))
        self.assertEqual(res.context["last_visit"].name, "나중에 만든 병원")


class SecurityTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.admin = User.objects.create_superuser(username="admin", password="0000")

    def login(self, password, username="haru_mom", ip="10.0.0.1"):
        return self.client.post(reverse("login"), {"username": username, "password": password}, REMOTE_ADDR=ip)

    def test_login_locks_after_repeated_failures(self):
        for _ in range(5):
            self.login("1111")
        res = self.login("0000")  # 맞는 비밀번호여도 잠긴 동안은 막는다
        self.assertContains(res, "너무 많이 시도했어요")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ip_lock_covers_many_usernames(self):
        for i in range(20):
            self.login("1111", username=f"guess{i}")
        self.assertContains(self.login("0000"), "너무 많이 시도했어요")

    def test_success_resets_username_counter(self):
        for _ in range(4):
            self.login("1111")
        self.assertRedirects(self.login("0000"), reverse("home"), fetch_redirect_response=False)

    def test_select_ignores_external_next(self):
        baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        baby.guardians.add(self.mom)
        self.client.force_login(self.mom)
        res = self.client.post(reverse("baby_select", args=[baby.pk]), {"next": "https://evil.example.com/"})
        self.assertEqual(res["Location"], reverse("home"))

    def test_password_change(self):
        self.client.force_login(self.mom)
        res = self.client.post(reverse("password_change"),
                               {"old_password": "0000", "new_password1": "2468", "new_password2": "2468"})
        self.assertRedirects(res, reverse("settings"), fetch_redirect_response=False)
        self.mom.refresh_from_db()
        self.assertTrue(self.mom.check_password("2468"))
        self.assertIn("_auth_user_id", self.client.session)  # 바꾼 기기는 로그인 유지

    def test_password_change_rejects_wrong_old_password(self):
        self.client.force_login(self.mom)
        res = self.client.post(reverse("password_change"),
                               {"old_password": "9999", "new_password1": "2468", "new_password2": "2468"})
        self.assertContains(res, "지금 비밀번호가 맞지 않아요")

    def test_admin_resets_password(self):
        self.mom.set_password("2468")
        self.mom.save()
        self.client.force_login(self.admin)
        self.client.post(reverse("user_reset_password", args=[self.mom.pk]))
        self.mom.refresh_from_db()
        self.assertTrue(self.mom.check_password("0000"))

    def test_family_cannot_reset_password(self):
        other = User.objects.create_user(username="haru_dad", password="0000")
        self.client.force_login(other)
        self.client.post(reverse("user_reset_password", args=[self.mom.pk]))
        self.mom.refresh_from_db()
        self.assertTrue(self.mom.check_password("0000"))
        self.assertEqual(self.client.get("/django-admin/").status_code, 404)  # 관리자 화면은 기본으로 꺼짐


class RecordEditTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.dad = User.objects.create_user(username="haru_dad", password="0000", relation="아빠")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom, self.dad)
        self.illness = Illness.objects.create(baby=self.baby, title="감기")
        self.temp = Temperature.objects.create(baby=self.baby, illness=self.illness, value=Decimal("37.6"),
                                               recorded_by=self.mom)
        self.med = Medication.objects.create(baby=self.baby, illness=self.illness, drug="tylenol",
                                             amount_ml=Decimal("4.5"), recorded_by=self.mom)
        self.client.force_login(self.dad)

    def test_pages_render(self):
        for kind, rec in (("temp", self.temp), ("med", self.med)):
            self.assertEqual(self.client.get(reverse("record_edit", args=[kind, rec.pk])).status_code, 200)

    def test_edit_temperature_keeps_original_recorder(self):
        when = (timezone.localtime() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("record_edit", args=["temp", self.temp.pk]),
                         {"value": "36.7", "method": "armpit", "recorded_at": when})
        self.temp.refresh_from_db()
        self.assertEqual((self.temp.value, self.temp.method, self.temp.recorder_relation),
                         (Decimal("36.7"), "armpit", "엄마"))
        self.assertEqual(self.temp.editor_relation, "아빠")
        self.assertContains(self.client.get(reverse("illness_detail", args=[self.illness.pk])), "아빠가 고침")

    def test_edit_medication(self):
        self.client.post(reverse("record_edit", args=["med", self.med.pk]),
                         {"drug": "maxibupen", "amount_ml": "5.0", "recorded_at": ""})
        self.med.refresh_from_db()
        self.assertEqual((self.med.drug, self.med.amount_ml), ("maxibupen", Decimal("5.0")))

    def test_delete(self):
        self.client.post(reverse("record_delete", args=["temp", self.temp.pk]))
        self.assertFalse(Temperature.objects.filter(pk=self.temp.pk).exists())

    def test_other_family_cannot_edit(self):
        other = User.objects.create_user(username="other", password="0000")
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("record_delete", args=["temp", self.temp.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("record_edit", args=["bogus", 1])).status_code, 404)


class SummaryTests(TestCase):
    def test_summary_shows_symptom_spans_and_meds(self):
        mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        baby.guardians.add(mom)
        self.client.force_login(mom)
        self.client.post(reverse("illness_create"), {"title": "감기", "symptoms": ["콧물", "발열"]})
        illness = Illness.objects.get()
        self.client.post(reverse("illness_edit", args=[illness.pk]), {"title": "감기", "symptoms": ["콧물", "중이염"]})
        Temperature.objects.create(baby=baby, illness=illness, value=Decimal("38.9"))
        Medication.objects.create(baby=baby, illness=illness, drug="tylenol", amount_ml=Decimal("4.5"))
        res = self.client.get(reverse("illness_summary", args=[illness.pk]))
        self.assertContains(res, "38.9℃")
        self.assertContains(res, "나아짐")      # 발열이 빠졌다
        self.assertContains(res, "부터 계속")    # 콧물·중이염은 남아 있다
        self.assertContains(res, "아세트아미노펜 4.5mL")
        self.assertNotContains(res, "144mg")    # 요약에는 mg를 보이지 않는다
        spans = {s["name"]: s for s in res.context["symptoms"]}
        self.assertIsNotNone(spans["발열"]["end"])
        self.assertIsNone(spans["중이염"]["end"])


class DoseTextTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="봄이", birth_date=date(2023, 5, 14), weight_kg=Decimal("13.6"))
        self.baby.guardians.add(self.mom)
        self.illness = Illness.objects.create(baby=self.baby, title="감기")
        self.client.force_login(self.mom)
        now = timezone.now()
        for minutes, drug in ((50, "maxibupen"), (50, "tylenol"), (2, "maxibupen")):
            Medication.objects.create(baby=self.baby, illness=self.illness, drug=drug, amount_ml=Decimal("5"),
                                      recorded_at=now - timedelta(minutes=minutes))

    def test_waiting_text_names_the_dose_that_blocks(self):
        res = self.client.get(reverse("home"))
        acet = next(r for r in res.context["dose_rows"] if r["cls"] == "acet")
        self.assertIn("아세트아미노펜 기준", acet["sub"])   # 같은 계열 아세트아미노펜 때문에 기다린다


class TimerMessageTests(TestCase):
    def test_just_dosed_says_wait_and_watch(self):
        mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        baby.guardians.add(mom)
        illness = Illness.objects.create(baby=baby, title="감기")
        Temperature.objects.create(baby=baby, illness=illness, value=Decimal("38.8"))
        Medication.objects.create(baby=baby, illness=illness, drug="tylenol", amount_ml=Decimal("4.5"))
        Medication.objects.create(baby=baby, illness=illness, drug="maxibupen", amount_ml=Decimal("5"))
        self.client.force_login(mom)
        res = self.client.get(reverse("home"))
        self.assertContains(res, "해열제가 듣는 중이에요. 1시간쯤 지켜봐요.")
        self.assertNotContains(res, "물수건")


class TimerScopeTests(TestCase):
    def test_timer_ignores_doses_from_previous_illness(self):
        mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        baby = Baby.objects.create(name="봄이", birth_date=date(2023, 5, 14), weight_kg=Decimal("13.6"))
        baby.guardians.add(mom)
        old = Illness.objects.create(baby=baby, title="감기", started_at=timezone.now() - timedelta(hours=3),
                                     cured_at=timezone.now() - timedelta(hours=2))
        Medication.objects.create(baby=baby, illness=old, drug="tylenol", amount_ml=Decimal("3.5"),
                                  recorded_at=timezone.now() - timedelta(hours=1))
        Illness.objects.create(baby=baby, title="감기")
        self.client.force_login(mom)
        res = self.client.get(reverse("home"))
        acet = next(r for r in res.context["dose_rows"] if r["cls"] == "acet")
        self.assertTrue(acet["ready"])
        self.assertEqual(acet["sub"], "먹인 기록이 없어요")
        # 먹인 양 기억은 지난 아픔 것도 쓴다
        self.assertEqual(res.context["sheet_data"]["drugs"]["tylenol"]["lastMl"], 3.5)


class VisitMinTests(TestCase):
    def test_visit_before_illness_start_rejected(self):
        mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        baby.guardians.add(mom)
        Illness.objects.create(baby=baby, title="감기", started_at=timezone.now() - timedelta(days=1))
        self.client.force_login(mom)
        before = timezone.localdate() - timedelta(days=3)
        self.client.post(reverse("visit_create"), {"name": "병원", "visited_at": f"{before} am"})
        self.assertFalse(HospitalVisit.objects.exists())
        self.assertContains(self.client.get(reverse("visit_create")), "data-min=")


class HeicPhotoTests(TestCase):
    def test_heic_upload_is_converted_to_jpeg(self):
        import io as _io
        from pathlib import Path

        from PIL import Image

        sample = (Path(__file__).parent / "fixtures" / "sample.heic").read_bytes()  # 2400×1200 HEIC
        mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        baby.guardians.add(mom)
        self.client.force_login(mom)
        heic = SimpleUploadedFile("IMG_0001.HEIC", sample, content_type="image/heic")
        self.client.post(reverse("visit_create"), {"name": "병원", "got_medicine": "on", "photos": [heic]})
        photo = HospitalVisit.objects.get().photos.get()
        self.assertEqual(photo.content_type, "image/jpeg")
        image = Image.open(_io.BytesIO(bytes(photo.data)))
        self.assertEqual((image.format, max(image.size)), ("JPEG", 1600))


class ReminderTests(TestCase):
    def setUp(self):
        from sicklog.models import PushSubscription

        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom)
        PushSubscription.objects.create(user=self.mom, endpoint="https://push.example/1", p256dh="k", auth="a")
        self.illness = Illness.objects.create(baby=self.baby, title="감기")
        self.now = timezone.now()

    def run_reminders(self):
        from unittest import mock

        sent = []
        with mock.patch("sicklog.management.commands.send_reminders.push_enabled", return_value=True), \
             mock.patch("sicklog.management.commands.send_reminders.send_to_user",
                        side_effect=lambda user, title, body, **kw: sent.append(title) or 1):
            call_command("send_reminders", stdout=StringIO())
        return sent

    def temp(self, value, hours_ago):
        Temperature.objects.create(baby=self.baby, illness=self.illness, value=Decimal(value),
                                   recorded_at=self.now - timedelta(hours=hours_ago))

    def med(self, hours_ago):
        Medication.objects.create(baby=self.baby, illness=self.illness, drug="tylenol", amount_ml=Decimal("4.5"),
                                  recorded_at=self.now - timedelta(hours=hours_ago))

    def test_no_reminder_when_temperature_is_normal(self):
        self.temp("37.2", 3)
        self.assertFalse([t for t in self.run_reminders() if "체온" in t or "1시간" in t])

    def test_reminds_when_mild_fever(self):
        self.temp("37.6", 1.5)
        self.assertIn("하루 체온 잴 시간이에요", self.run_reminders())

    def test_reminds_once_an_hour_after_dose(self):
        self.temp("38.6", 2)
        self.med(1.2)
        sent = self.run_reminders()
        self.assertIn("하루 해열제를 먹인 지 1시간이 지났어요", sent)
        self.assertNotIn("하루 체온 잴 시간이에요", sent)  # 같은 때 두 번 보내지 않는다
        self.assertNotIn("하루 해열제를 먹인 지 1시간이 지났어요", self.run_reminders())

    def test_no_after_dose_reminder_if_measured_since(self):
        self.med(1.2)
        self.temp("37.0", 0.2)
        self.assertNotIn("하루 해열제를 먹인 지 1시간이 지났어요", self.run_reminders())


class ConditionCheckTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom)
        self.illness = Illness.objects.create(baby=self.baby, title="감기", started_at=timezone.now() - timedelta(days=2))
        self.client.force_login(self.mom)

    def tap(self, item, value, slot=""):
        return self.client.post(reverse("illness_check", args=[self.illness.pk]),
                                {"item": item, "value": value, "slot": slot}).json()

    def test_summary_sentence(self):
        from sicklog.models import ConditionCheck

        check = ConditionCheck(ate=True, played=True)
        self.assertEqual((check.summary, check.overall_label), ("밥 잘 먹고 잘 놀아요", "좋음"))
        check = ConditionCheck(ate=False, played=True, slept=False)
        self.assertEqual((check.summary, check.overall_label), ("밥은 잘 안 먹고 잘 놀고 잠을 설쳐요", "나쁨"))

    def test_taps_save_one_check_per_half_day(self):
        self.tap("ate", "o")
        data = self.tap("played", "x")
        self.assertEqual((data["summary"], data["label"]), ("밥 잘 먹고 잘 안 놀아요", "보통"))
        self.assertEqual(self.illness.checks.count(), 1)
        yesterday = f"{timezone.localdate() - timedelta(days=1)} pm"
        self.tap("ate", "o", yesterday)
        self.assertEqual(self.illness.checks.count(), 2)

    def test_clearing_all_answers_removes_the_check(self):
        self.tap("ate", "o")
        data = self.tap("ate", "")
        self.assertEqual(data["summary"], "")
        self.assertFalse(self.illness.checks.exists())

    def test_shown_on_detail_and_summary(self):
        self.tap("ate", "o")
        self.tap("played", "o")
        self.assertContains(self.client.get(reverse("illness_detail", args=[self.illness.pk])), "밥 잘 먹고 잘 놀아요")
        self.assertContains(self.client.get(reverse("illness_summary", args=[self.illness.pk])), "밥 잘 먹고 잘 놀아요")
        self.assertContains(self.client.get(reverse("home")), "오늘 컨디션은 어떤가요?")

    def test_before_illness_start_rejected(self):
        old = f"{timezone.localdate() - timedelta(days=10)} am"
        self.assertFalse(self.tap("ate", "o", old)["ok"])
