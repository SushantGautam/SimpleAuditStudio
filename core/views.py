"""Foundation views: health, auth, and project management."""
import logging

from django.contrib.auth import authenticate, login
from django.db import connection
from django.http import JsonResponse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .exceptions import StableAPIError
from .models import Project, ProjectMembership, User
from .serializers import (
    ProjectMembershipSerializer,
    ProjectSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .readiness import ready_payload
from .services import bootstrap_admin_and_default_project, ensure_project_access

logger = logging.getLogger(__name__)


def healthz(request):
    return JsonResponse({"status": "ok"})


def readyz(request):
    payload = ready_payload()
    status_code = 200 if payload["status"] == "ready" else 503
    return JsonResponse(payload, status=status_code)


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def obtain_token(request):
    """Issue a DRF auth token for username/password.

    The SPA uses token auth (``Authorization: Token <key>``) so it works across
    origins and without CSRF handling. Returns the token plus the user payload.
    """
    username = request.data.get("username", "")
    password = request.data.get("password", "")
    user = authenticate(request, username=username, password=password)
    if user is None:
        raise StableAPIError(detail="Invalid credentials.", code="invalid_credentials", http_status=401)
    token, _created = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": UserSerializer(user).data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_projects(request):
    if request.user.is_superuser:
        projects = Project.objects.all()
    else:
        projects = Project.objects.filter(memberships__user=request.user).distinct()
    return Response(ProjectSerializer(projects, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_project(request):
    if not request.user.is_superuser:
        raise StableAPIError(detail="Only superusers can create projects.", code="project_create_forbidden")
    serializer = ProjectSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    project = serializer.save()
    ProjectMembership.objects.get_or_create(
        project=project,
        user=request.user,
        defaults={"role": ProjectMembership.Role.ADMIN},
    )
    return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_project(request, project_id):
    project = _get_project_or_404(project_id)
    if not ensure_project_access(request.user, project):
        raise StableAPIError(detail="Project access denied.", code="project_access_denied", http_status=403)
    return Response(ProjectSerializer(project).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_members(request, project_id):
    project = _get_project_or_404(project_id)
    if not ensure_project_access(request.user, project):
        raise StableAPIError(detail="Project access denied.", code="project_access_denied", http_status=403)
    memberships = project.memberships.select_related("user").all()
    return Response(ProjectMembershipSerializer(memberships, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_member(request, project_id):
    project = _get_project_or_404(project_id)
    if not ensure_project_access(request.user, project) or not request.user.is_superuser:
        raise StableAPIError(detail="Project admin or superuser required.", code="membership_forbidden", http_status=403)

    username = request.data.get("username")
    role = request.data.get("role", ProjectMembership.Role.VIEWER)
    if role not in dict(ProjectMembership.Role.choices):
        raise StableAPIError(detail="Invalid role.", code="invalid_role")
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        raise StableAPIError(detail="User not found.", code="user_not_found", http_status=404)

    membership, _ = ProjectMembership.objects.update_or_create(
        project=project,
        user=user,
        defaults={"role": role},
    )
    return Response(ProjectMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


def _get_project_or_404(project_id) -> Project:
    try:
        return Project.objects.get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise StableAPIError(detail="Project not found.", code="project_not_found", http_status=404) from exc
