import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """날짜만 받던 시작·완치·병원 방문을 날짜+오전/오후(시각)로 바꾼다. 기존 날짜는 그날 0시(UTC 기준)로 옮겨진다."""

    dependencies = [("sicklog", "0001_initial")]

    operations = [
        migrations.RemoveConstraint(model_name="illness", name="one_active_illness"),
        migrations.RenameField(model_name="illness", old_name="started_on", new_name="started_at"),
        migrations.AlterField(model_name="illness", name="started_at",
                              field=models.DateTimeField(default=django.utils.timezone.now, verbose_name="아프기 시작한 때")),
        migrations.RenameField(model_name="illness", old_name="cured_on", new_name="cured_at"),
        migrations.AlterField(model_name="illness", name="cured_at",
                              field=models.DateTimeField(blank=True, null=True, verbose_name="다 나은 때")),
        migrations.AddConstraint(model_name="illness", constraint=models.UniqueConstraint(
            condition=models.Q(cured_at__isnull=True), fields=("baby",), name="one_active_illness")),
        migrations.AlterModelOptions(name="illness", options={"ordering": ["-started_at", "-id"], "verbose_name": "아픔",
                                                              "verbose_name_plural": "아픔"}),
        migrations.RenameField(model_name="illnesslog", old_name="all_day", new_name="half_day"),
        migrations.RenameField(model_name="hospitalvisit", old_name="visited_on", new_name="visited_at"),
        migrations.AlterField(model_name="hospitalvisit", name="visited_at",
                              field=models.DateTimeField(default=django.utils.timezone.now, verbose_name="방문한 때")),
        migrations.AlterModelOptions(name="hospitalvisit", options={"ordering": ["-visited_at", "-id"], "verbose_name": "병원 기록",
                                                                    "verbose_name_plural": "병원 기록"}),
    ]
