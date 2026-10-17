import time

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connection


class Command(BaseCommand):
    help = "데이터베이스에 연결될 때까지 기다린다."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, timeout, **options):
        deadline = time.monotonic() + timeout
        while True:
            try:
                connection.ensure_connection()
                self.stdout.write("데이터베이스에 연결됐어요.")
                return
            except OperationalError:
                if time.monotonic() > deadline:
                    raise CommandError("데이터베이스에 연결하지 못했어요.")
                time.sleep(1)
