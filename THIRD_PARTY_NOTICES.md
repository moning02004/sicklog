# Third-party notices

아파요(sicklog) 코드는 MIT 라이선스입니다. 함께 쓰는 라이브러리와 리소스는 각자의 라이선스를 따릅니다.
이 저장소에는 아래 라이브러리의 소스가 들어 있지 않고, 설치·빌드할 때 내려받습니다.

## Python (requirements.txt)

| 패키지 | 라이선스 |
| --- | --- |
| Django, asgiref, sqlparse | BSD-3-Clause |
| dj-database-url | BSD-2-Clause |
| psycopg, psycopg-binary | LGPL-3.0 (수정 없이 라이브러리로 사용) |
| gunicorn, whitenoise | MIT |
| pywebpush, py-vapid | MPL-2.0 (수정 없이 사용) |
| http-ece, urllib3, six, charset-normalizer | MIT |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| requests, aiohttp | Apache-2.0 |
| certifi | MPL-2.0 |
| Pillow | MIT-CMU (HPND) |
| pi-heif | BSD-3-Clause. HEIC 읽기 전용. 휠에 libheif·libde265(LGPL-3.0)가 들어 있다. 수정 없이 사용 |

## 화면 빌드 (assets/package.json)

| 패키지 | 라이선스 | 비고 |
| --- | --- | --- |
| tailwindcss | MIT | 빌드할 때만 사용 |
| Pretendard | SIL Open Font License 1.1 | Docker 이미지에 `PretendardVariable.woff2`가 들어간다. 폰트만 따로 팔 수는 없다 |

Pretendard: Copyright (c) 2021, Kil Hyung-jin (https://github.com/orioncactus/pretendard), SIL OFL 1.1.

## 아이콘

화면의 선 아이콘 일부는 [Lucide](https://lucide.dev)(ISC License, Copyright (c) Lucide Contributors / Feather, MIT)의 모양을 참고해 그렸습니다.

## Docker 이미지

`python:3.12-slim`, `node:20-alpine`(빌드 단계), `postgres:16-alpine` 공식 이미지를 씁니다. 각 이미지에 포함된 소프트웨어의 라이선스를 따릅니다.
