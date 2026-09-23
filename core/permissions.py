"""Project-scoped RBAC helpers for API views."""
from rest_framework.permissions import BasePermission

from .models import ProjectMembership


class IsProjectAdmin(BasePermission):
    message = "Project admin role required."

    def has_object_permission(self, request, view, obj) -> bool:
        return _has_role(request.user, getattr(obj, "project", obj), ProjectMembership.Role.ADMIN)


class IsProjectMember(BasePermission):
    message = "Project membership required."

    def has_object_permission(self, request, view, obj) -> bool:
        project = getattr(obj, "project", obj)
        return _has_role(
            request.user,
            project,
            ProjectMembership.Role.ADMIN,
            ProjectMembership.Role.AUDITOR,
            ProjectMembership.Role.VIEWER,
        )


def _has_role(user, project, *roles) -> bool:
    if not user or not user.is_authenticated or project is None:
        return False
    return ProjectMembership.objects.filter(project=project, user=user, role__in=roles).exists()
