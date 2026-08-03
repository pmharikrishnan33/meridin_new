import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import httpx
import numpy as np

from app.ml.entity_extractor import entity_extractor
from app.ml.intent_classifier import intent_classifier
from app.ml.loader import model_loader
from app.models.schemas import EntityType, IntentType
from app.main import app
from app.core.config import settings


class _TokenVectorizer:
    def transform(self, values):
        return values


class _TokenModel:
    def predict(self, values):
        return np.array(["B-COLOR", "I-COLOR", "B-PRODUCT"])

    def predict_proba(self, values):
        return np.array([[0.05, 0.95], [0.10, 0.90], [0.15, 0.85]])


class ModelPipelineTests(unittest.TestCase):
    def test_intent_model_and_vectorizer_are_compatible(self):
        model_loader.load_all()
        self.assertIsNotNone(model_loader.intent_model)
        self.assertIsNotNone(model_loader.intent_vectorizer)
        self.assertEqual(
            model_loader.intent_model.n_features_in_,
            model_loader.intent_vectorizer.transform(["test"]).shape[1],
        )

    def test_model_label_aliases_match_application_intents(self):
        self.assertEqual(
            intent_classifier._map_to_intent_type("product_availability"),
            IntentType.AVAILABILITY,
        )
        self.assertEqual(
            intent_classifier._map_to_intent_type("cancel_request"),
            IntentType.CANCEL_ORDER,
        )

    def test_entity_bio_predictions_are_grouped_with_positions(self):
        old_model = model_loader._entity_model
        old_vectorizer = model_loader._entity_vectorizer
        old_loaded = model_loader._loaded
        model_loader._entity_model = _TokenModel()
        model_loader._entity_vectorizer = _TokenVectorizer()
        model_loader._loaded = True

        try:
            entities = entity_extractor._extract_ml("navy blue dress")
        finally:
            model_loader._entity_model = old_model
            model_loader._entity_vectorizer = old_vectorizer
            model_loader._loaded = old_loaded

        self.assertEqual(len(entities), 2)
        self.assertEqual(entities[0].entity_type, EntityType.COLOR)
        self.assertEqual(entities[0].value, "navy blue")
        self.assertEqual((entities[0].start_pos, entities[0].end_pos), (0, 9))
        self.assertEqual(entities[1].entity_type, EntityType.PRODUCT)
        self.assertEqual(entities[1].value, "dress")


class ApiFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_messages_endpoint_is_not_publicly_exposed(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/messages",
                json={"tenant_id": "tenant-1", "user_id": "user-1", "text": "hello"},
            )

        self.assertEqual(response.status_code, 404)

    async def test_whatsapp_webhook_processes_text_messages(self):
        webhook_secret = settings.WHATSAPP_WEBHOOK_SECRET or settings.APP_SECRET
        body = json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry-1",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "metadata": {"phone_number_id": "tenant-1"},
                        "messages": [{
                            "from": "user-1",
                            "id": "message-1",
                            "timestamp": "1710000000",
                            "type": "text",
                            "text": {"body": "thank you"},
                        }],
                    },
                }],
            }],
        }).encode("utf-8")
        signature = hmac.new(
            key=webhook_secret.encode(),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        with patch("app.api.security.rate_limiter._enabled", False):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/webhook",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x_hub_signature_256": f"sha256={signature}",
                    },
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "accepted")
        self.assertEqual(payload["processed"][0]["intent"], "thanks")


if __name__ == "__main__":
    unittest.main()
