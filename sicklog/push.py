"""Web Push 발송."""
import json
import logging
import threading

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .models import PushSubscription

logger = logging.getLogger(__name__)


def push_enabled():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def in_quiet_hours(now):
    hour = timezone.localtime(now).hour
    return hour >= 23 or hour < 7


def send_to_user(user, title, body, url="/", tag=None):
    """사용자의 모든 기기로 알림을 보낸다. 보낸 기기 수를 돌려준다."""
    if not push_enabled():
        return 0
    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or "sicklog"})
    sent = 0
    for sub in PushSubscription.objects.filter(user=user):
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=60 * 30,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                sub.delete()  # 만료된 구독
            else:
                logger.warning("push failed user=%s status=%s %s", user.pk, status, exc)
    return sent


def josa_ga(name):
    code = ord(name[-1]) - 0xAC00
    jong = code % 28 if 0 <= code < 11172 else 0
    return name + ("이" if jong else "가")


def notify_family(baby, actor, title, body):
    """다른 보호자들에게 새 기록을 알린다. 저장 응답이 늦어지지 않게 저장이 끝난 뒤 따로 보낸다."""
    if not push_enabled():
        return
    now = timezone.now()
    users = [u for u in baby.guardians.exclude(pk=actor.pk).filter(notify_family=True, push_subscriptions__isnull=False)
             .distinct() if not (u.notify_quiet and in_quiet_hours(now))]
    if not users:
        return

    def run():
        try:
            for user in users:
                send_to_user(user, title, body, tag=f"family-{baby.pk}")
        except Exception:
            logger.exception("family push failed baby=%s", baby.pk)
        finally:
            connection.close()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())


def who(user):
    """알림에 쓰는 이름: '엄마가', '민지가'."""
    return josa_ga(user.relation or user.display_name)
