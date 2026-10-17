from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sicklog.models import User


class Command(BaseCommand):
    help = "사용자 비밀번호를 기본값(0000)이나 지정한 값으로 초기화한다."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password", default=None)

    def handle(self, username, password, **options):
        user = User.objects.filter(username=username).first()
        if not user:
            raise CommandError(f"'{username}' 사용자가 없어요.")
        user.set_password(password or settings.DEFAULT_USER_PASSWORD)
        user.save(update_fields=["password"])
        self.stdout.write(self.style.SUCCESS(f"'{username}' 비밀번호를 초기화했어요."))
