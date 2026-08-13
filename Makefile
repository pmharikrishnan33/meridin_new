.PHONY: install install-dev run dev test test-cov lint format typecheck clean docker-up docker-down docker-logs train eval

# Install production dependencies
install:
	pip install -r requirements.txt

# Install development dependencies
install-dev:
	pip install -r requirements.txt -r requirements-dev.txt

# Run the server (production mode)
run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run the server (development mode with auto-reload)
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
test:
	python -m pytest tests/ -v

# Run tests with coverage
test-cov:
	python -m pytest tests/ -v --cov=app/ --cov-report=term-missing --cov-report=html

# Run linting
lint:
	ruff check app/ scripts/ tests/

# Auto-format code
format:
	ruff format app/ scripts/ tests/
	ruff check --fix app/ scripts/ tests/

# Type checking
typecheck:
	mypy app/ --ignore-missing-imports

# Clean up
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage

# Docker commands
docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ML training
train:
	python scripts/train.py

# ML evaluation (no training)
eval:
	python scripts/train.py --eval-only
