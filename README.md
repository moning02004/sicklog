# 아파요

아기가 아플 때 증상, 체온, 해열제, 병원 기록을 가족이 함께 쓰는 모바일 웹앱(PWA)입니다. 프로젝트 이름은 `sicklog`입니다.

- **아픔 기록**: 감기·독감 같은 이름과 증상(콧물, 기침, 발열 등 여러 개)을 기록. 아픔이 있으면 어느 보호자가 로그인해도 홈에 먼저 보인다
- **증상 기록**: 증상을 고칠 때마다 "기침 생김", "콧물 나아짐"을 그 시간과 함께 남긴다
- **완치로 기록**: 자동으로 끝나지 않고 보호자가 직접 완치 시간을 골라 끝낸다 (나중에 기록해도 그때 시간으로). 3일 넘게 기록이 없으면 완치 기록을 권한다
- **병원 기록**: 언제 어느 병원에 갔는지, 위치, 받은 약, 약 봉지 사진(최대 6장, DB에 저장)
- 체온 기록(기본 측정 부위: 귀)과 체온 차트, 해열제 기록과 교차복용 타이머, 몸무게 기준 용량 가이드
- 푸시 알림: 아픔을 기록 중인 동안 체온 기록 알림, 해열제를 먹일 수 있게 되면 알림
- 회원가입 없음. 최고관리자가 설정에서 사용자(이름·관계·아이디, 비밀번호 0000)를 추가·삭제

> **의료 정보가 아니에요.** 해열제 용량과 간격은 흔히 쓰는 제품 라벨 기준의 참고값입니다.
> 제품마다 농도가 다르니 반드시 라벨을 확인하고, 의사·약사의 지시를 따르세요.

## 로컬 실행 (docker compose)

```bash
make up        # .env가 없으면 .env.example을 복사하고, 빌드 후 실행
make seed      # 예시 데이터: haru_mom / haru_dad (비밀번호 0000), 아기 2명(감기 중 / 장염 완치)
```

- 주소: http://localhost:8000
- 최고관리자: `admin` / `0000` (`.env`의 `DJANGO_ADMIN_*` 값)
- Django 관리자 화면: http://localhost:8000/django-admin/ (`.env`의 `DJANGO_ADMIN_URL`, 비우면 꺼짐)
- `.venv`에서 `manage.py`를 직접 실행할 때는 `DJANGO_DEBUG=1`을 붙이세요 (운영 모드는 `DJANGO_SECRET_KEY`가 없으면 시작하지 않음)

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
sicklog/             앱: 모델, 화면(views.py, illness_views.py), 해열제 계산(dosing.py), 푸시(push.py)
sicklog/management/  운영 명령: ensure_admin, send_reminders, generate_vapid_keys,
                     reset_password, wait_for_db, seed_demo(로컬 전용)
templates/           화면 템플릿
static/js/           app.js(화면 동작), sw.js(서비스 워커)
assets/              Tailwind 설정 (Docker 빌드 단계에서 CSS와 Pretendard 폰트를 만든다)
docker/entrypoint.sh web | migrate | scheduler | <manage.py 명령>
kubernates/          운영 매니페스트 (git에 올리지 않음)
```

기록에는 기록한 사람의 이름과 관계를 복사해 둡니다. 사용자를 삭제할 때 "기록은 남기기"를 고르면 기록은 그대로 남고,
"기록도 함께 삭제"를 고르면 그 사람이 남긴 기록이 지워집니다.

## 보안

- 회원가입 없음. 최고관리자가 사용자를 만들고(비밀번호 0000), 각자 설정 → 비밀번호 바꾸기로 바꾼다. 최고관리자는 사용자 비밀번호를 0000으로 초기화할 수 있다
- 로그인 시도 제한: 같은 아이디 5번, 같은 IP 20번 틀리면 10분 동안 막는다 (`LOGIN_*` 환경 변수, 여러 파드가 같이 보도록 DB 캐시 사용)
- 운영에서 `DJANGO_SECRET_KEY`가 없으면 시작하지 않는다. https 운영(`DJANGO_SECURE_COOKIES=1`)이면 HSTS를 켠다
- Django 관리자 화면은 `DJANGO_ADMIN_URL`이 있을 때만 열린다. 운영에서는 비워 두거나 짐작하기 어려운 주소로
- 다른 가족의 아기·기록·사진은 보호자로 연결되지 않으면 볼 수 없다

## 운영 (Kubernetes)

`kubernates/`에 namespace부터 ingress까지 들어 있습니다.

| 파일 | 내용 |
| --- | --- |
| `00-namespace.yaml` | `sicklog` 네임스페이스 |
| `01-configmap.yaml` | 도메인, 시간대 등 설정 |
| `02-secret.yaml` | SECRET_KEY, DB 비밀번호, VAPID 키 (실제 값으로 바꿔서 사용) |
| `03-postgres.yaml` | PostgreSQL StatefulSet + 5Gi 볼륨 |
| `04-migrate-job.yaml` | 마이그레이션 + 관리자 계정 Job (`make k8s-migrate`가 실행) |
| `05-deployment.yaml` | 웹 2개 (gunicorn), `/healthz` 상태 확인 |
| `06-service.yaml` | 웹 서비스 |
| `07-cronjob-reminders.yaml` | 1분마다 푸시 알림 발송 |
| `08-ingress.yaml` | nginx ingress + cert-manager TLS |

처음 배포:

1. `01-configmap.yaml`, `08-ingress.yaml`의 `sicklog.example.com`을 실제 도메인으로 바꾼다.
2. `02-secret.yaml`의 `CHANGE_ME`(관리자 비밀번호 포함)와 VAPID 키를 채운다.
3. 이미지는 GitHub Release를 발행하면 `ghcr.io/moning02004/sicklog:<태그>`와 `:latest`로 올라간다 (`.github/workflows/release.yml`). 직접 올리려면 `make push TAG=...`
4. 실행:

```bash
make k8s-apply                 # namespace ~ ingress 생성
make k8s-deploy TAG=v1.0.0     # 이미지 빌드·푸시 → 마이그레이션 → 웹·알림 이미지 교체
make k8s-status
```

이후 배포는 `make k8s-deploy TAG=<새 태그>`만 실행하면 됩니다.

## 만든 과정

기획은 직접 하고 구현은 [Claude Code](https://claude.com/claude-code)에 맡겼습니다. 직접 실행해 보며 수정 사항을 전달해 발전시켰습니다.

## 라이선스

[MIT](LICENSE). 누구나 쓰고, 고치고, fork 해서 배포할 수 있어요. 함께 쓰는 라이브러리와 폰트의 라이선스는
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리돼 있습니다.

`kubernates/`는 `.gitignore`에 들어 있어 저장소에 올라가지 않습니다. fork 해서 운영하려면 위 표의 파일을 직접 만들어 쓰세요.
