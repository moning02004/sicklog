# syntax=docker/dockerfile:1

# 1) Tailwind CSS와 Pretendard 폰트 빌드
FROM node:20.18.1-alpine AS assets
WORKDIR /build/assets
COPY assets/package.json ./
RUN npm install --no-audit --no-fund
COPY assets/ ./
COPY templates/ /build/templates/
COPY fever/ /build/fever/
COPY static/js/ /build/static/js/
RUN npx tailwindcss -c tailwind.config.js -i app.css -o /build/static_build/css/app.css --minify \
 && mkdir -p /build/static_build/fonts \
 && cp node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2 /build/static_build/fonts/

# 2) Django 앱
FROM python:3.12.8-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BUILD_STATIC_DIR=/app/static_build
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
COPY --from=assets /build/static_build /app/static_build
RUN DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput \
 && useradd --system --uid 1000 --home /app fevercheck \
 && chown -R fevercheck /app
USER 1000

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
