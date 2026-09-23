from django.urls import path

from . import views

urlpatterns = [
    path("", views.list_projects, name="project-list"),
    path("create/", views.create_project, name="project-create"),
    path("<int:project_id>/", views.get_project, name="project-detail"),
    path("<int:project_id>/members/", views.list_members, name="project-members"),
    path("<int:project_id>/members/add/", views.add_member, name="project-member-add"),
]
