from django.test import TestCase

from infra.readiness import migrations_pending


class HealthEndpointTests(TestCase):
    def setUp(self):
        super().setUp()
        migrations_pending.cache_clear()

    def test_healthz_returns_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_readyz_passes_when_database_available(self):
        response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(response.json()["checks"]["database"], "ok")
