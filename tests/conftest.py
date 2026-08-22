import os


os.environ.setdefault(
    "APP_SECRET",
    "test-secret",
)

os.environ.setdefault(
    "MONGODB_URI",
    "mongodb://localhost:27017",
)

os.environ.setdefault(
    "DATABASE_NAME",
    "meridin_test",
)

os.environ.setdefault(
    "OPENROUTER_API_KEY",
    "",
)

os.environ.setdefault(
    "OPENROUTER_MODEL",
    "test-model",
)

os.environ.setdefault(
    "WHATSAPP_VERIFY_TOKEN",
    "test-token",
)

os.environ.setdefault(
    "WHATSAPP_WEBHOOK_SECRET",
    "test-webhook-secret",
)

os.environ.setdefault(
    "RATE_LIMIT_ENABLED",
    "false",
)