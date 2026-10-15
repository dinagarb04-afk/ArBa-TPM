.PHONY: up down logs migrate seed test lint format typecheck

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.seed

test:
	docker compose exec api pytest

lint:
	docker compose exec api ruff check .

format:
	docker compose exec api ruff format .

typecheck:
	docker compose exec api mypy app
