# 열체크

아기가 열이 날 때 체온과 해열제를 기록하고, 엄마·아빠가 함께 보는 모바일 웹앱(PWA)입니다.

- 체온 기록(기본 측정 부위: 귀)과 24시간 체온 차트
- 해열제 기록과 교차복용 타이머 (타이레놀 ↔ 맥시부펜·이부프로펜 2시간, 같은 계열 4/6시간)
- 몸무게 기준 해열제 용량 가이드 (제품 라벨 확인 안내 포함)
- 기록이 3일 넘게 없으면 처음~마지막 기록으로 "며칠간 아팠어요" 요약
- 푸시 알림: 열이 나는 동안 체온 기록 알림, 해열제를 먹일 수 있게 되면 알림
- 회원가입 없음. 최고관리자가 설정에서 사용자(이름·관계·아이디, 비밀번호 0000)를 추가·삭제

## 로컬 실행 (docker compose)

```bash
make up        # .env가 없으면 .env.example을 복사하고, 빌드 후 실행
make seed      # 예시 데이터: haru_mom / haru_dad (비밀번호 0000), 아기 2명
```

- 주소: http://localhost:8000
- 최고관리자: `admin` / `0000` (`.env`의 `DJANGO_ADMIN_*` 값)
- Django 관리자 화면: http://localhost:8000/django-admin/

푸시 알림을 써 보려면 `make vapid`로 키를 만들어 `.env`의 `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`에 넣고
`make up`으로 다시 띄운 뒤, 설정 → "이 기기에서 알림 받기"를 켜세요. 알림은 `scheduler` 컨테이너가 1분마다 보냅니다.

| 명령 | 하는 일 |
| --- | --- |
| `make up` / `make down` | 실행 / 중지 |
| `make logs` | web·scheduler 로그 |
| `make test` | 테스트 |
| `make seed` | 예시 데이터 |
| `make reset-password U=haru_mom` | 비밀번호를 0000으로 초기화 |
| `make reminders` | 알림 발송 한 번 실행 |
| `make manage CMD="..."` | 임의의 manage.py 명령 |

## 구조

```
config/              Django 설정 (모든 운영 값은 환경 변수)
fever/               앱: 모델, 화면, 해열제 계산(dosing.py), 푸시(push.py)
fever/management/    운영 명령: ensure_admin, send_reminders, generate_vapid_keys,
                     reset_password, wait_for_db, seed_demo(로컬 전용)
templates/           화면 템플릿
static/js/           app.js(화면 동작), sw.js(서비스 워커)
assets/              Tailwind 설정 (Docker 빌드 단계에서 CSS와 Pretendard 폰트를 만든다)
docker/entrypoint.sh web | migrate | scheduler | <manage.py 명령>
kubernates/          운영 매니페스트 (git에 올리지 않음)
```

기록에는 기록한 사람의 이름과 관계를 복사해 둡니다. 사용자를 삭제할 때 "기록은 남기기"를 고르면 기록은 그대로 남고,
"기록도 함께 삭제"를 고르면 그 사람이 남긴 기록이 지워집니다.

## 운영 (Kubernetes)

`kubernates/`에 namespace부터 ingress까지 들어 있습니다.

| 파일 | 내용 |
| --- | --- |
| `00-namespace.yaml` | `fevercheck` 네임스페이스 |
| `01-configmap.yaml` | 도메인, 시간대 등 설정 |
| `02-secret.yaml` | SECRET_KEY, DB 비밀번호, VAPID 키 (실제 값으로 바꿔서 사용) |
| `03-postgres.yaml` | PostgreSQL StatefulSet + 5Gi 볼륨 |
| `04-migrate-job.yaml` | 마이그레이션 + 관리자 계정 Job (`make k8s-migrate`가 실행) |
| `05-deployment.yaml` | 웹 2개 (gunicorn), `/healthz` 상태 확인 |
| `06-service.yaml` | 웹 서비스 |
| `07-cronjob-reminders.yaml` | 1분마다 푸시 알림 발송 |
| `08-ingress.yaml` | nginx ingress + cert-manager TLS |

처음 배포:

1. `01-configmap.yaml`, `08-ingress.yaml`의 `fevercheck.example.com`을 실제 도메인으로 바꾼다.
2. `02-secret.yaml`의 `CHANGE_ME`와 VAPID 키를 채운다.
3. 이미지 주소를 정한다: `export IMAGE=registry.example.com/fevercheck`
4. 실행:

```bash
make k8s-apply                 # namespace ~ ingress 생성
make k8s-deploy TAG=1.0.0      # 이미지 빌드·푸시 → 마이그레이션 → 웹·알림 이미지 교체
make k8s-status
```

이후 배포는 `make k8s-deploy TAG=<새 태그>`만 실행하면 됩니다.
