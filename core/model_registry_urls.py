from django.urls import path

from . import model_registry_views

urlpatterns = [
    path("projects/<int:project_id>/model-endpoints/", model_registry_views.list_model_endpoints, name="model-endpoint-list"),
    path(
        "projects/<int:project_id>/model-endpoints/create/",
        model_registry_views.create_model_endpoint_view,
        name="model-endpoint-create",
    ),
    path("projects/<int:project_id>/audit-profiles/", model_registry_views.list_audit_profiles, name="audit-profile-list"),
    path(
        "projects/<int:project_id>/audit-profiles/create/",
        model_registry_views.create_audit_profile_view,
        name="audit-profile-create",
    ),
]
