.PHONY: run dev prod install lint test clean docker

install:
	pip install -e ".[dev]"

dev:
	uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

run:
	uvicorn src.main:app --host 0.0.0.0 --port 8000

prod:
	gunicorn src.main:app -c gunicorn.conf.py

docker:
	docker compose up --build -d

test:
	pytest -v

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache dist *.egg-info
