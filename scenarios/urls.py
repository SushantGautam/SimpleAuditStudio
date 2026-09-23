from django.urls import path

from . import views

urlpatterns = [
    path("projects/<int:project_id>/scenarios/", views.list_scenarios, name="scenario-list"),
    path("projects/<int:project_id>/scenarios/create/", views.create_scenario_view, name="scenario-create"),
    path(
        "projects/<int:project_id>/scenarios/<int:scenario_id>/",
        views.get_scenario,
        name="scenario-detail",
    ),
    path(
        "projects/<int:project_id>/scenarios/<int:scenario_id>/update/",
        views.update_scenario_view,
        name="scenario-update",
    ),
    path(
        "projects/<int:project_id>/scenarios/<int:scenario_id>/revisions/",
        views.list_revisions,
        name="scenario-revisions",
    ),
    path("projects/<int:project_id>/scenario-sets/", views.list_scenario_sets, name="scenario-set-list"),
    path("projects/<int:project_id>/scenario-sets/create/", views.create_scenario_set_view, name="scenario-set-create"),
    path(
        "projects/<int:project_id>/scenario-sets/<int:set_id>/versions/",
        views.list_versions,
        name="scenario-set-versions",
    ),
    path(
        "projects/<int:project_id>/scenario-sets/<int:set_id>/publish/",
        views.publish_version,
        name="scenario-set-publish",
    ),
    path("projects/<int:project_id>/scenarios/export/", views.export_scenarios, name="scenario-export"),
    path("projects/<int:project_id>/scenarios/import/", views.import_scenarios, name="scenario-import"),
]
