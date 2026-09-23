"""Model registry and audit profile models.

These entities are selectable resources for future AuditRun creation. They store
safe configuration only; credentials remain external secret references.
"""
from django.conf import settings
from django.db import models


class ModelEndpoint(models.Model):
    project = models.ForeignKey("accounts.Project", on_delete=models.CASCADE, related_name="model_endpoints")
    display_name = models.CharField(max_length=250)
    provider = models.CharField(max_length=120)
    base_url = models.URLField()
    model_id = models.CharField(max_length=250)
    model_revision = models.CharField(max_length=250, blank=True)
    capabilities = models.JSONField(default=dict, blank=True)
    default_parameters = models.JSONField(default=dict, blank=True)
    secret_reference = models.CharField(max_length=250, blank=True)
    api_key_direct = models.CharField(max_length=500, blank=True, default="")
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_model_endpoint"
        constraints = [
            models.UniqueConstraint(fields=["project", "display_name"], name="unique_model_endpoint_display_name_per_project"),
        ]
        ordering = ["project__name", "display_name"]

    def __str__(self) -> str:
        return self.display_name


class AuditProfile(models.Model):
    project = models.ForeignKey("accounts.Project", on_delete=models.CASCADE, related_name="audit_profiles")
    name = models.CharField(max_length=250)
    max_turns = models.PositiveIntegerField(default=4)
    temperature_target = models.FloatField(default=0.7)
    temperature_auditor = models.FloatField(default=0.2)
    temperature_judge = models.FloatField(default=0.0)
    top_p = models.FloatField(default=1.0)
    max_tokens = models.PositiveIntegerField(default=2048)
    retry_policy = models.JSONField(default=dict, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=300)
    concurrency = models.PositiveIntegerField(default=1)
    language = models.CharField(max_length=30, default="en")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_audit_profile"
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="unique_audit_profile_name_per_project"),
        ]
        ordering = ["project__name", "name"]

    def __str__(self) -> str:
        return self.name
