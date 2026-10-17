# 아파요 운영 명령. `make help`로 목록을 볼 수 있어요.
IMAGE ?= ghcr.io/moning02004/sicklog
TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo latest)
NS ?= sicklog
K8S_DIR ?= kubernates
COMPOSE ?= docker compose
MANAGE = $(COMPOSE) exec web python manage.py

.DEFAULT_GOAL := help
.PHONY: help env up down restart logs ps build seed admin shell migrate manage test vapid reminders \
        reset-password css image push k8s-apply k8s-migrate k8s-deploy k8s-status k8s-logs k8s-shell k8s-delete

help: ## 명령 목록
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## ---------- 로컬 (docker compose)
env: ## .env 파일 만들기 (.env.example 복사)
	@test -f .env && echo ".env가 이미 있어요" || (cp .env.example .env && echo ".env를 만들었어요")

up: env ## 빌드하고 백그라운드로 실행 (http://localhost:8000)
	$(COMPOSE) up -d --build

down: ## 중지
	$(COMPOSE) down

restart: ## 다시 시작
	$(COMPOSE) restart web scheduler

logs: ## 로그 보기
	$(COMPOSE) logs -f web scheduler

ps: ## 실행 상태
	$(COMPOSE) ps

build: ## 이미지만 빌드
	$(COMPOSE) build

seed: ## 예시 데이터 넣기 (haru_mom / haru_dad, 비밀번호 0000)
	$(MANAGE) seed_demo

admin: ## 최고관리자 계정 만들기 (.env 값 사용)
	$(MANAGE) ensure_admin

migrate: ## DB 마이그레이션
	$(MANAGE) migrate

shell: ## Django 셸
	$(MANAGE) shell

manage: ## 임의의 manage.py 명령: make manage CMD="showmigrations"
	$(MANAGE) $(CMD)

reset-password: ## 비밀번호 0000으로 초기화: make reset-password U=haru_mom
	$(MANAGE) reset_password $(U)

reminders: ## 알림 발송을 한 번 실행
	$(MANAGE) send_reminders

vapid: ## Web Push VAPID 키 만들기 (.env / Secret에 넣기)
	@$(COMPOSE) run --rm --no-deps web generate_vapid_keys

test: ## 테스트 실행
	$(COMPOSE) run --rm --no-deps -e DATABASE_URL=sqlite:////tmp/test.sqlite3 -e DJANGO_ADMIN_URL= web test sicklog

css: ## (선택) 로컬 node로 Tailwind CSS 빌드
	cd assets && npm install --no-audit --no-fund && npm run build
	mkdir -p static_build/fonts && cp assets/node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2 static_build/fonts/

## ---------- 운영 (Kubernetes)
image: ## 운영 이미지 빌드: make image TAG=1.0.0
	docker build -t $(IMAGE):$(TAG) .

push: image ## 이미지 빌드 후 레지스트리에 올리기
	docker push $(IMAGE):$(TAG)

k8s-apply: ## namespace부터 ingress까지 적용
	kubectl apply -k $(K8S_DIR)

k8s-migrate: ## 마이그레이션 Job 실행 (관리자 계정도 확인)
	-kubectl -n $(NS) delete job sicklog-migrate --ignore-not-found
	sed 's#image: .*#image: $(IMAGE):$(TAG)#' $(K8S_DIR)/04-migrate-job.yaml | kubectl apply -f -
	kubectl -n $(NS) wait --for=condition=complete job/sicklog-migrate --timeout=300s
	kubectl -n $(NS) logs job/sicklog-migrate

k8s-deploy: push k8s-migrate ## 이미지 올리기 → 마이그레이션 → 웹·알림 이미지 교체
	kubectl -n $(NS) set image deployment/sicklog-web web=$(IMAGE):$(TAG)
	kubectl -n $(NS) set image cronjob/sicklog-reminders reminders=$(IMAGE):$(TAG)
	kubectl -n $(NS) rollout status deployment/sicklog-web --timeout=300s

k8s-status: ## 리소스 상태
	kubectl -n $(NS) get pods,svc,ingress,cronjob,job,pvc

k8s-logs: ## 웹 로그
	kubectl -n $(NS) logs -f deployment/sicklog-web

k8s-shell: ## 웹 파드에서 Django 셸
	kubectl -n $(NS) exec -it deployment/sicklog-web -- python manage.py shell

k8s-delete: ## 네임스페이스째 삭제 (DB 볼륨 포함, 되돌릴 수 없음)
	kubectl delete -k $(K8S_DIR)
