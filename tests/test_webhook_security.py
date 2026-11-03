"""Regressões básicas da autenticação do webhook (sem chamadas externas)."""
import unittest
from unittest.mock import patch
import evolution


class WebhookSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = evolution.app.test_client()

    def test_missing_server_secret_blocks_requests(self):
        with patch.object(evolution, "WEBHOOK_SHARED_SECRET", ""):
            response = self.client.post("/webhook/messages-upsert", json={"event": "messages.upsert"})
        self.assertEqual(response.status_code, 503)

    def test_invalid_token_blocks_requests(self):
        with patch.object(evolution, "WEBHOOK_SHARED_SECRET", "a-private-test-token"):
            response = self.client.post(
                "/webhook/messages-upsert",
                headers={"X-Webhook-Token": "wrong"},
                json={"event": "messages.upsert"},
            )
        self.assertEqual(response.status_code, 401)

    def test_valid_token_rejects_non_json(self):
        with patch.object(evolution, "WEBHOOK_SHARED_SECRET", "a-private-test-token"):
            response = self.client.post(
                "/webhook/messages-upsert",
                headers={"X-Webhook-Token": "a-private-test-token"},
                data="not-json",
                content_type="text/plain",
            )
        self.assertEqual(response.status_code, 415)

    def test_valid_token_accepts_ignored_event(self):
        with patch.object(evolution, "WEBHOOK_SHARED_SECRET", "a-private-test-token"):
            response = self.client.post(
                "/webhook/messages-upsert",
                headers={"X-Webhook-Token": "a-private-test-token"},
                json={"event": "other"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ignored"})


if __name__ == "__main__":
    unittest.main()
