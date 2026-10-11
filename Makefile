PYTHON ?= python3
UVICORN ?= uvicorn
PIP ?= pip

.PHONY: install run dev test migrate

install:
	$(PIP) install -r requirements.txt
	cd apps/web-dashboard && npm install
	cd apps/community-monitor && npm install

run:
	$(UVICORN) backend.api.main:app --host 0.0.0.0 --port 8000 --reload

dev:
	cd apps/web-dashboard && npm run dev
	cd apps/community-monitor && npm run dev

test:
	pytest -q

migrate:
	alembic upgrade head
