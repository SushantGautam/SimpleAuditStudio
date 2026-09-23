from django.urls import path

from . import scenario_views

urlpatterns = [
    path("projects/<int:project_id>/scenarios/", scenario_views.list_scenarios, name="scenario-list"),
    path("projects/<int:project_id>/scenarios/create/", scenario_views.create_scenario_view, name="scenario-create"),
    path(
        "projects/<int:project_id>/scenarios/<int:scenario_id>/",
        scenario_views.get_scenario,
        name="scenario-detail",
    ),
    path(
        "projects/<int:project_id>/scenarios/<int:scenario_id>/update/",
        scenario_views.update_scenario_view,
        name="scenario-update",
    ),
    path(
        "projects/<int:project_id>/scenarios/<int:scenario_id>/revisions/",
        scenario_views.list_revisions,
        name="scenario-revisions",
    ),
    path("projects/<int:project_id>/scenario-sets/", scenario_views.list_scenario_sets, name="scenario-set-list"),
    path("projects/<int:project_id>/scenario-sets/create/", scenario_views.create_scenario_set_view, name="scenario-set-create"),
    path(
        "projects/<int:project_id>/scenario-sets/<int:set_id>/versions/",
        scenario_views.list_versions,
        name="scenario-set-versions",
    ),
    path(
        "projects/<int:project_id>/scenario-sets/<int:set_id>/publish/",
        scenario_views.publish_version,
        name="scenario-set-publish",
    ),
]
