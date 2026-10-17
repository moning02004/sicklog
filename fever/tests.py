from datetime import date, timedelta
from io import StringIO
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import dosing
from .models import Baby, Medication, Temperature, User


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

    def test_episodes_split_after_three_days(self):
        old = Temperature.objects.create(baby=self.baby, value=Decimal("38.5"), recorded_at=self.now - timedelta(days=10))
        old2 = Temperature.objects.create(baby=self.baby, value=Decimal("37.0"),
                                          recorded_at=self.now - timedelta(days=9))
        new = Temperature.objects.create(baby=self.baby, value=Decimal("38.1"), recorded_at=self.now)
        episodes = dosing.split_episodes([old, old2, new])
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0]["days"], 2)


class ViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", password="0000", name="관리자")
        self.mom = User.objects.create_user(username="haru_mom", password="0000", name="김서윤", relation="엄마")
        self.baby = Baby.objects.create(name="하루", birth_date=date(2025, 8, 10), weight_kg=Decimal("10.2"))
        self.baby.guardians.add(self.mom)

    def test_pages_render(self):
        self.client.force_login(self.mom)
        Temperature.objects.create(baby=self.baby, value=Decimal("38.6"), recorded_by=self.mom)
        for name in ("home", "history", "guide", "settings", "baby_list", "baby_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("baby_detail", args=[self.baby.pk])).status_code, 200)

    def test_login_required(self):
        self.assertRedirects(self.client.get(reverse("home")), f"{reverse('login')}?next=/")

    def test_record_temperature_keeps_recorder_snapshot(self):
        self.client.force_login(self.mom)
        self.client.post(reverse("temperature_create"), {"value": "38.4", "method": "ear"})
        record = Temperature.objects.get()
        self.assertEqual((record.recorder_relation, record.recorder_name), ("엄마", "김서윤"))

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


class EpisodeTests(TestCase):
    def setUp(self):
        self.mom = User.objects.create_user(username="haru_mom", password="0000", relation="엄마")
        self.baby = Baby.objects.create(name="봄이", birth_date=date(2023, 5, 14), weight_kg=Decimal("13.6"))
        self.baby.guardians.add(self.mom)
        now = timezone.now()
        self.old = Temperature.objects.create(baby=self.baby, value=Decimal("38.8"), recorded_at=now - timedelta(days=10))
        Temperature.objects.create(baby=self.baby, value=Decimal("37.0"), recorded_at=now - timedelta(days=9))
        self.client.force_login(self.mom)

    def test_history_lists_past_episode_only_once(self):
        res = self.client.get(reverse("history"))
        self.assertContains(res, "지금은 아픈 기록이 없어요")
        self.assertContains(res, reverse("episode_detail", args=[int(self.old.recorded_at.timestamp())]))
        self.assertNotContains(res, "38.8℃ <span")  # 지난 기록은 상세 화면에서만

    def test_episode_detail_shows_records(self):
        res = self.client.get(reverse("episode_detail", args=[int(self.old.recorded_at.timestamp())]))
        self.assertContains(res, "2일간")
        self.assertContains(res, "38.8℃")

    def test_ongoing_episode_redirects_to_history(self):
        new = Temperature.objects.create(baby=self.baby, value=Decimal("38.1"))
        res = self.client.get(reverse("episode_detail", args=[int(new.recorded_at.timestamp())]))
        self.assertRedirects(res, reverse("history"))
