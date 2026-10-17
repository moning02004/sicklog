#!/bin/sh
# 사용법: entrypoint.sh web | migrate | scheduler | <manage.py 명령>
set -e

case "$1" in
  web)
    python manage.py wait_for_db
    if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
      python manage.py migrate --noinput
      python manage.py ensure_admin
    fi
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
