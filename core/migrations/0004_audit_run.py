from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_model_registry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=250)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("preparing", "Preparing"),
                            ("target_execution", "Target execution"),
                            ("auditing", "Auditing"),
                            ("judging", "Judging"),
                            ("aggregation", "Aggregation"),
                            ("report_generation", "Report generation"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="queued",
                        max_length=30,
                    ),
                ),
                ("target_config_snapshot", models.JSONField()),
                ("auditor_config_snapshot", models.JSONField()),
                ("judge_config_snapshot", models.JSONField()),
                ("generation_parameters_snapshot", models.JSONField()),
                ("simpleaudit_version", models.CharField(max_length=120)),
                ("git_commit", models.CharField(max_length=120)),
                ("runtime_metadata", models.JSONField(blank=True, default=dict)),
                ("workflow_run_id", models.CharField(blank=True, max_length=250)),
                ("queued_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("total_scenarios", models.PositiveIntegerField(default=0)),
                ("completed_scenarios", models.PositiveIntegerField(default=0)),
                ("successful_scenarios", models.PositiveIntegerField(default=0)),
                ("failed_scenarios", models.PositiveIntegerField(default=0)),
                ("retried_scenarios", models.PositiveIntegerField(default=0)),
                ("summary_metrics", models.JSONField(blank=True, default=dict)),
                ("error_code", models.CharField(blank=True, max_length=120)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "audit_profile",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_runs", to="core.auditprofile"),
                ),
                (
                    "auditor_endpoint",
                    models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="auditor_audit_runs", to="core.modelendpoint"),
                ),
                (
                    "created_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "judge_endpoint",
                    models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="judge_audit_runs", to="core.modelendpoint"),
                ),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audit_runs", to="core.project")),
                (
                    "scenario_set_version",
                    models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="audit_runs", to="core.scenariosetversion"),
                ),
                (
                    "target_endpoint",
                    models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="target_audit_runs", to="core.modelendpoint"),
                ),
            ],
            options={
                "db_table": "core_audit_run",
                "ordering": ["-created_at"],
            },
        ),
    ]
