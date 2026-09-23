from django.urls import path

from . import audit_views

urlpatterns = [
    path("projects/<int:project_id>/audit-runs/", audit_views.list_audit_runs, name="audit-run-list"),
    path("projects/<int:project_id>/audit-runs/create/", audit_views.create_audit_run_view, name="audit-run-create"),
    path("projects/<int:project_id>/audit-runs/<int:run_id>/", audit_views.get_audit_run, name="audit-run-detail"),
    path(
        "projects/<int:project_id>/audit-runs/<int:run_id>/results/",
        audit_views.list_audit_run_results,
        name="audit-run-results",
    ),
    path(
        "projects/<int:project_id>/audit-runs/<int:run_id>/events/poll/",
        audit_views.poll_audit_run_events,
        name="audit-run-events-poll",
    ),
    path(
        "projects/<int:project_id>/audit-runs/<int:run_id>/events/",
        audit_views.stream_audit_run_events,
        name="audit-run-events",
    ),
]
