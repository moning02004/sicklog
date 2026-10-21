"""컨디션 기록을 메모로 바꾼다. 고른 답(잘 먹어요 …)은 버리지 않고 메모 글 앞에 붙여 남긴다."""

from django.db import migrations, models
import django.db.models.deletion

LABELS = {
    "ate": {"good": "잘 먹어요", "bad": "안 먹어요"},
    "played": {"good": "잘 놀아요", "bad": "처져요"},
    "slept": {"good": "푹 잤어요", "woke": "자주 깼어요", "drowsy": "계속 자려고만 해요"},
}


def answers_into_text(apps, schema_editor):
    Note = apps.get_model("sicklog", "Note")
    for note in Note.objects.all():
        said = [LABELS[f].get(getattr(note, f), "") for f in ("ate", "played", "slept")]
        parts = [", ".join(t for t in said if t), note.memo]
        text = ". ".join(p for p in parts if p)
        if text != note.memo:
            note.memo = text[:300]
            note.save(update_fields=["memo"])


class Migration(migrations.Migration):
    dependencies = [("sicklog", "0010_fever_ibuprofen")]

    operations = [
        migrations.RenameModel("ConditionCheck", "Note"),
        migrations.AlterField("note", "memo", models.CharField("메모", max_length=300, blank=True)),
        migrations.RunPython(answers_into_text, migrations.RunPython.noop),
        migrations.RemoveField("note", "ate"),
        migrations.RemoveField("note", "played"),
        migrations.RemoveField("note", "slept"),
        migrations.RenameField("note", "memo", "text"),
        migrations.AlterField("note", "text", models.CharField("메모", max_length=300)),
        migrations.AlterField("note", "illness", models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE, related_name="notes", to="sicklog.illness")),
        migrations.AlterModelOptions("note", {"ordering": ["-recorded_at", "-id"], "verbose_name": "메모", "verbose_name_plural": "메모"}),
    ]
