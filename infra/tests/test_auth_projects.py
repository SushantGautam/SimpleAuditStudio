from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Project, ProjectMembership

User = get_user_model()


class AuthProjectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="strong-pass-123")
        self.other = User.objects.create_user(username="bob", password="strong-pass-456")
        self.project = Project.objects.create(name="Research", slug="research")
        ProjectMembership.objects.create(project=self.project, user=self.user, role=ProjectMembership.Role.AUDITOR)

    def test_register_creates_user_and_sets_session(self):
        response = self.client.post(
            "/api/auth/register/",
            {"username": "carol", "email": "carol@example.com", "password": "another-strong-pass"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username="carol").exists())

    def test_me_requires_authentication(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 403)

    def test_member_can_list_project(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/projects/")
        self.assertEqual(response.status_code, 200)
        slugs = [item["slug"] for item in response.json()]
        self.assertIn("research", slugs)

    def test_non_member_cannot_access_project_detail(self):
        self.client.force_login(self.other)
        response = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_create_project(self):
        admin = User.objects.create_superuser(username="root", email="root@example.com", password="admin-pass-123")
        self.client.force_login(admin)
        response = self.client.post("/api/projects/create/", {"name": "Ops", "slug": "ops"})
        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(slug="ops")
        self.assertTrue(ProjectMembership.objects.filter(project=project, user=admin, role="admin").exists())

    def test_add_member_requires_superuser_or_admin(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/projects/{self.project.id}/members/add/",
            {"username": "bob", "role": "viewer"},
        )
        self.assertEqual(response.status_code, 403)
