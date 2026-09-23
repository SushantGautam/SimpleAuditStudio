import os
from contextlib import contextmanager

from django.core.management import call_command
from django.test import TestCase

from accounts.models import Project, ProjectMembership


@contextmanager
def _safe_env():
    """Provide a safe, non-default config so the startup check passes on both
    local SQLite and real Postgres. The bootstrap command still enforces these
    checks; we simply supply valid values for the duration of the test."""
    values = {
        "DJANGO_SECRET_KEY": "test-secret-key-not-change-me",
        "POSTGRES_PASSWORD": "testpass123",
        "MINIO_ACCESS_KEY": "test-minio-access",
        "MINIO_SECRET_KEY": "test-minio-secret",
    }
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class BootstrapTests(TestCase):
    def test_bootstrap_is_idempotent(self):
        with _safe_env():
            for _ in range(2):
                call_command(
                    "bootstrap_platform",
                    username="admin",
                    email="admin@example.local",
                    password="admin-pass-123",
                    project_name="Default",
                )

        project = Project.objects.get(slug="default")
        memberships = ProjectMembership.objects.filter(project=project)
        self.assertEqual(memberships.count(), 1)
        self.assertEqual(memberships.first().role, ProjectMembership.Role.ADMIN)
