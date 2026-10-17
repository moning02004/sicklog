import os

from django.core.management.base import BaseCommand

from fever.models import User


class Command(BaseCommand):
    help = "최고관리자 계정이 없으면 환경 변수(DJANGO_ADMIN_USERNAME/PASSWORD/NAME) 값으로 만든다."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_ADMIN_USERNAME", "admin")
        password = os.environ.get("DJANGO_ADMIN_PASSWORD", "0000")
        name = os.environ.get("DJANGO_ADMIN_NAME", "최고관리자")
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"관리자 '{username}' 계정이 이미 있어요.")
            return
        User.objects.create_superuser(username=username, password=password, name=name, email="")
        self.stdout.write(self.style.SUCCESS(f"관리자 '{username}' 계정을 만들었어요."))
