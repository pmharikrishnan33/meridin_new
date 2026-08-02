# Meridin — WhatsApp E-Commerce Shopping Assistant

Meridin is a FastAPI-based WhatsApp shopping assistant that understands
natural-language queries, classifies user intent, extracts product entities,
and routes requests to specialized handlers.  It supports product search,
order tracking, cancellations, returns, and AI-powered fallback responses
via OpenRouter.

## Features

- **Intent classification** — TF-IDF + LogisticRegression model with keyword fallback
- **Entity extraction** — Token-level NER with BIO tagging (colors, sizes, products, prices, order IDs, etc.)
- **Text preprocessing** — Abbreviation expansion, typo fixing, and fuzzy vocabulary matching
- **Product search** — MongoDB-backed search with fuzzy matching and result ranking
- **Order management** — Status lookup, cancellation, and return processing
- **AI fallback** — OpenRouter LLM integration for contextual responses
- **WhatsApp integration** — Webhook ingestion and outbound messaging via Meta Graph API
- **Multi-tenant** — Per-tenant settings and feature flags
- **Caching** — Redis cache for product lookups
- **Graceful degradation** — Runs in stateless ML-only mode without MongoDB

## Architecture

```
app/
├── api/              # HTTP endpoints (webhook, chat)
├── ai/               # LLM integration (OpenRouter client, prompt templates, fallback)
├── conversation/     # Session management and context tracking
├── core/             # Configuration and dependencies
├── database/         # MongoDB and Redis connection managers
├── handlers/         # Intent-specific request handlers
├── ml/               # ML pipeline (loader, classifier, extractor, preprocessor)
├── models/           # Pydantic schemas and response helpers
├── repositories/     # MongoDB repository layer
├── routing/          # Intent routing and configuration
├── search/           # Search ranking, alternative search, pagination
├── services/         # Business logic (product, order, inventory, message, response)
├── templates/        # WhatsApp template definitions
├── utils/            # Logging and helper utilities
└── main.py           # FastAPI application entry point

scripts/
└── train.py          # Training pipeline for intent and entity models

data/                 # Training data (JSON)
models/               # Pre-trained model artifacts (.pkl)
tests/                # Test suite
```

## Quick Start

### Prerequisites

- Python 3.12+
- MongoDB (optional — app runs in stateless mode without it)
- Redis (optional — cache degrades gracefully)

### Installation

```bash
# Clone and enter the project
cd NEW_MERIDIN_WITH_ML

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your configuration
```

### Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `APP_NAME` | Application name | `Meridin` |
| `MONGODB_URI` | MongoDB connection string | *(required)* |
| `MONGODB_REQUIRED` | Fail startup if MongoDB is unavailable | `false` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `OPENROUTER_API_KEY` | OpenRouter API key for AI fallback | *(required)* |
| `OPENROUTER_MODEL` | LLM model identifier | `meta-llama/llama-3.1-8b-instruct` |
| `WHATSAPP_VERIFY_TOKEN` | Meta webhook verification token | *(optional)* |

### Running

```bash
# Start the server
uvicorn app.main:app --reload

# Or use the Makefile
make dev
```

Visit `http://localhost:8000/health` to check the service status.

### Training Models

```bash
# Train both intent and entity models
python scripts/train.py

# Train only the intent classifier
python scripts/train.py --intent-only

# Evaluate existing models without retraining
python scripts/train.py --eval-only
```

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov
```

## API Endpoints

### Health Check

```
GET /health
```

### Process a Message (Local Chat)

```
POST /api/messages
Content-Type: application/json

{
  "tenant_id": "tenant-1",
  "user_id": "user-1",
  "text": "hello"
}
```

### WhatsApp Webhook

```
GET  /api/webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
POST /api/webhook
```

## Docker

```bash
# Build and run
make docker-up

# Or with docker compose
docker compose up --build
```

## Development

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Lint
make lint

# Format
make format

# Type check
make typecheck
```

## License

MIT
