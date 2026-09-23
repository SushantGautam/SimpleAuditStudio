import json
import time

from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .audit_events import ScenarioResult, list_events
from .audit_models import AuditRun
from .audit_serializers import AuditRunCreateSerializer, AuditRunSerializer
from .audit_services import create_audit_run, submit_audit_run
from .exceptions import StableAPIError
from .model_registry_models import AuditProfile, ModelEndpoint
from .models import Project
from .scenario_models import ScenarioSetVersion
from .services import ensure_project_access

# Terminal event kinds: once one of these is seen for the run, the stream can end.
_TERMINAL_EVENT_KINDS = {"run_completed", "run_failed", "run_cancelled"}
_SSE_POLL_INTERVAL_SECONDS = 1.0
_SSE_MAX_DURATION_SECONDS = 3600


def _get_project_or_404(project_id) -> Project:
    try:
        return Project.objects.get(pk=project_id)
    except Project.DoesNotExist as exc:
        raise StableAPIError(detail="Project not found.", code="project_not_found", http_status=404) from exc


def _require_project_access(user, project: Project):
    if not ensure_project_access(user, project):
        raise StableAPIError(detail="Project access denied.", code="project_access_denied", http_status=403)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_audit_runs(request, project_id):
    project = _get_project_or_404(project_id)
    _require_project_access(request.user, project)
    runs = AuditRun.objects.filter(project=project).select_related("scenario_set_version")
    return Response(AuditRunSerializer(runs, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_audit_run(request, project_id, run_id):
    project = _get_project_or_404(project_id)
    _require_project_access(request.user, project)
    queryset = AuditRun.objects.filter(id=run_id, project=project).select_related(
        "scenario_set_version", "target_endpoint", "auditor_endpoint", "judge_endpoint"
    )
    try:
        run = queryset.get()
    except AuditRun.DoesNotExist as exc:
        raise StableAPIError(detail="Audit run not found.", code="audit_run_not_found", http_status=404) from exc
    return Response(AuditRunSerializer(run).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_audit_run_results(request, project_id, run_id):
    """Per-scenario results for a run, joined with the pinned version item.

    Returns one row per scenario: the durable ``ScenarioResult`` (status,
    attempts, full structured result) plus the scenario identity from the frozen
    ``ScenarioSetVersionItem`` so the UI can label rows without re-deriving them.
    """
    project = _get_project_or_404(project_id)
    _require_project_access(request.user, project)
    queryset = AuditRun.objects.filter(id=run_id, project=project)
    try:
        run = queryset.get()
    except AuditRun.DoesNotExist as exc:
        raise StableAPIError(detail="Audit run not found.", code="audit_run_not_found", http_status=404) from exc

    items = {
        str(vi.id): vi
        for vi in run.scenario_set_version.items.select_related("scenario", "revision")
    }
    results = ScenarioResult.objects.filter(run_id=run.id).order_by("version_item_id")
    data = []
    for r in results:
        item = items.get(str(r.version_item_id))
        data.append(
            {
                "version_item_id": r.version_item_id,
                "status": r.status,
                "attempts": r.attempts,
                "result": r.result or {},
                "scenario_key": item.scenario.key if item and item.scenario else None,
                "scenario_title": item.scenario.title if item and item.scenario else None,
                "position": item.position if item else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return Response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_audit_run_view(request, project_id):
    project = _get_project_or_404(project_id)
    _require_project_access(request.user, project)
    serializer = AuditRunCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        scenario_set_version = ScenarioSetVersion.objects.get(id=data["scenario_set_version_id"], scenario_set__project=project)
        target_endpoint = ModelEndpoint.objects.get(id=data["target_endpoint_id"], project=project)
        auditor_endpoint = ModelEndpoint.objects.get(id=data["auditor_endpoint_id"], project=project)
        judge_endpoint = ModelEndpoint.objects.get(id=data["judge_endpoint_id"], project=project)
        audit_profile = None
        if data.get("audit_profile_id"):
            audit_profile = AuditProfile.objects.get(id=data["audit_profile_id"], project=project)
    except (ScenarioSetVersion.DoesNotExist, ModelEndpoint.DoesNotExist, AuditProfile.DoesNotExist) as exc:
        raise StableAPIError(detail="Audit input not found in project.", code="audit_input_not_found", http_status=404) from exc

    run = create_audit_run(
        project=project,
        user=request.user,
        name=data["name"],
        scenario_set_version=scenario_set_version,
        target_endpoint=target_endpoint,
        auditor_endpoint=auditor_endpoint,
        judge_endpoint=judge_endpoint,
        audit_profile=audit_profile,
        simpleaudit_version=data.get("simpleaudit_version") or None,
        git_commit=data.get("git_commit") or None,
    )

    # Enqueue durable work. This is best-effort: if the job system is unavailable
    # the run stays queued and records why (see submit_audit_run), so a frozen
    # experiment record is never lost to a transient infrastructure failure.
    submit_audit_run(run)
    run.refresh_from_db()
    return Response(AuditRunSerializer(run).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def poll_audit_run_events(request, project_id, run_id):
    """One-shot JSON snapshot of durable events with id > ``after_id``.

    This is the polling counterpart to :func:`stream_audit_run_events`. It exists
    because token-authenticated clients (the SPA) cannot send an ``Authorization``
    header through ``EventSource``. Each call returns only new events since the
    client's cursor, so it is reconnect-safe and cheap. The client stops polling
    once it observes a terminal run event.
    """
    project = _get_project_or_404(project_id)
    _require_project_access(request.user, project)
    queryset = AuditRun.objects.filter(id=run_id, project=project)
    try:
        run = queryset.get()
    except AuditRun.DoesNotExist as exc:
        raise StableAPIError(detail="Audit run not found.", code="audit_run_not_found", http_status=404) from exc

    after_id_raw = request.query_params.get("after_id") or "0"
    try:
        after_id = int(after_id_raw)
    except (TypeError, ValueError):
        after_id = 0

    return Response(list_events(run.id, after_id=after_id))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stream_audit_run_events(request, project_id, run_id):
    """Server-Sent Events stream of durable progress for an audit run.

    Progress is durable (Postgres ``AuditEvent`` rows), so a browser reconnect or
    server restart does not lose it. The client passes its last received event id
    via the ``Last-Event-ID`` header (or ``?after_id=``) and receives only events
    with a higher id — standard SSE replay semantics. The stream ends when a
    terminal run event (completed/failed/cancelled) is observed.
    """
    project = _get_project_or_404(project_id)
    _require_project_access(request.user, project)
    queryset = AuditRun.objects.filter(id=run_id, project=project)
    try:
        run = queryset.get()
    except AuditRun.DoesNotExist as exc:
        raise StableAPIError(detail="Audit run not found.", code="audit_run_not_found", http_status=404) from exc

    after_id_raw = request.headers.get("Last-Event-ID") or request.query_params.get("after_id") or "0"
    try:
        after_id = int(after_id_raw)
    except (TypeError, ValueError):
        after_id = 0

    def event_stream():
        sent_after = after_id
        start = time.monotonic()
        while True:
            if time.monotonic() - start > _SSE_MAX_DURATION_SECONDS:
                yield "event: timeout\ndata: {}\n\n"
                break
            events = list_events(run.id, after_id=sent_after)
            for e in events:
                sent_after = e["id"]
                data = json.dumps({"kind": e["kind"], "version_item_id": e["version_item_id"], "payload": e["payload"]})
                yield f"id: {e['id']}\nevent: {e['kind']}\ndata: {data}\n\n"
                if e["kind"] in _TERMINAL_EVENT_KINDS:
                    return
            time.sleep(_SSE_POLL_INTERVAL_SECONDS)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
