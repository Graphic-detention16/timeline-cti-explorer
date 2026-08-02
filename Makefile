.PHONY: bootstrap config build up down logs test lint audit frontend benchmark model ca trust-ca

bootstrap:
	python3 -m pip install -e .
	python3 scripts/bootstrap_env.py

config:
	docker compose config --quiet

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

test:
	pytest --cov=timeline_cti --cov-report=term-missing

lint:
	ruff check backend tests
	mypy backend
	bandit -q -r backend

audit:
	pip-audit
	cd frontend && corepack pnpm audit --audit-level high

frontend:
	cd frontend && corepack pnpm install --frozen-lockfile && corepack pnpm run build
	cd frontend && corepack pnpm run lint

benchmark:
	docker compose --profile benchmark run --rm benchmark python -m timeline_cti.benchmark --rows $${ROWS:-1000000}

model:
	docker compose --profile ml run --rm model-init
	docker compose restart worker

ca:
	./scripts/export_local_ca.sh

trust-ca:
	./scripts/trust_local_ca.sh
