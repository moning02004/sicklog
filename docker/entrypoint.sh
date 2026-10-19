#!/bin/sh
# 사용법: entrypoint.sh web | dev | migrate | scheduler | <manage.py 명령>
set -e

prepare_db() {
  python manage.py wait_for_db
  if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py createcachetable
    python manage.py ensure_admin
  fi
}

case "$1" in
  dev)
    # 로컬 개발용: 코드가 바뀌면 다시 시작한다 (compose에서 DJANGO_DEBUG=1과 함께 쓴다)
    prepare_db
    exec python manage.py runserver 0.0.0.0:8000
    ;;
  web)
    prepare_db
    exec gunicorn config.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-2}" \
      --threads "${GUNICORN_THREADS:-4}" \
      --access-logfile - \
      --forwarded-allow-ips "*"
    ;;
  migrate)
    python manage.py wait_for_db
    python manage.py migrate --noinput
    python manage.py createcachetable
    exec python manage.py ensure_admin
    ;;
  scheduler)
    # 로컬용: 1분마다 알림 발송. 운영에서는 CronJob이 send_reminders를 실행한다.
    python manage.py wait_for_db
    while true; do
      python manage.py send_reminders || true
      sleep "${REMINDER_INTERVAL_SECONDS:-60}"
    done
    ;;
  *)
    exec python manage.py "$@"
    ;;
esac
