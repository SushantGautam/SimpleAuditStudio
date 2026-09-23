"""Server-rendered UI — Django CBVs + Forms + HTMX."""
import hashlib
import json

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, View

from .audit_events import ScenarioResult
from .audit_models import AuditRun
from .audit_services import create_audit_run, submit_audit_run
from .comparison import compare_runs
from .model_registry_models import AuditProfile, ModelEndpoint
from .scenario_models import Scenario, ScenarioRevision, ScenarioSet, ScenarioSetVersionItem
from .scenario_services import publish_scenario_set_version


# ─── Mixins ──────────────────────────────────────────────────────────────────

class ProjectMixin(LoginRequiredMixin):
    """Scope all queries to request.project (set by ProjectMiddleware)."""


# ─── Auth ────────────────────────────────────────────────────────────────────

class IndexView(TemplateView):
    def get(self, request, *args, **kwargs):
        return redirect("dashboard" if request.user.is_authenticated else "login")


class LoginView(TemplateView):
    template_name = "auth/login.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kw):
        kw.setdefault("form", AuthenticationForm())
        return super().get_context_data(**kw)

    def post(self, request, *args, **kwargs):
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect("dashboard")
        return self.render_to_response(self.get_context_data(form=form))


class RegisterView(CreateView):
    model = None
    template_name = "auth/register.html"
    fields = []

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        from .models import User
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        email = request.POST.get("email", "").strip()
        error = None
        if not username or not password:
            error = "Username and password are required."
        elif User.objects.filter(username=username).exists():
            error = "Username already taken."
        else:
            user = User.objects.create_user(username=username, password=password, email=email)
            login(request, user)
            return redirect("dashboard")
        return self.render_to_response({"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


# ─── Dashboard ───────────────────────────────────────────────────────────────

class DashboardView(ProjectMixin, ListView):
    template_name = "dashboard.html"
    context_object_name = "runs"

    def get_queryset(self):
        return (
            AuditRun.objects.filter(project=self.request.project)
            .select_related("scenario_set_version__scenario_set")
            .order_by("-created_at")[:50]
        )

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        base = AuditRun.objects.filter(project=self.request.project)
        ctx["stats"] = {
            "total": base.count(),
            "active": base.exclude(status__in=["completed", "failed", "cancelled"]).count(),
            "completed": base.filter(status="completed").count(),
            "failed": base.filter(status="failed").count(),
        }
        return ctx


# ─── New Audit ───────────────────────────────────────────────────────────────

class NewAuditView(ProjectMixin, TemplateView):
    template_name = "new_audit.html"

    def get_context_data(self, **kw):
        p = self.request.project
        kw.update(
            sets=ScenarioSet.objects.filter(project=p),
            endpoints=ModelEndpoint.objects.filter(project=p).order_by("display_name"),
            profiles=AuditProfile.objects.filter(project=p).order_by("name"),
            error=None,
        )
        return super().get_context_data(**kw)

    def post(self, request, *args, **kwargs):
        p = request.project
        try:
            sset = ScenarioSet.objects.get(pk=request.POST["scenario_set"], project=p)
            version = sset.versions.order_by("-version").first()
            if not version:
                raise ValueError("No published version for this set.")

            # Parse optional hyperparameter overrides
            max_turns_raw = (request.POST.get("max_turns") or "").strip()
            max_turns_override = int(max_turns_raw) if max_turns_raw else None
            language_override = (request.POST.get("language") or "").strip() or None

            run = create_audit_run(
                project=p,
                user=request.user,
                name=f"Audit {timezone.now():%Y-%m-%d %H:%M}",
                scenario_set_version=version,
                target_endpoint=ModelEndpoint.objects.get(pk=request.POST["target_endpoint"], project=p),
                auditor_endpoint=ModelEndpoint.objects.get(pk=request.POST["auditor_endpoint"], project=p),
                judge_endpoint=ModelEndpoint.objects.get(pk=request.POST["judge_endpoint"], project=p),
                audit_profile=AuditProfile.objects.filter(pk=request.POST.get("profile"), project=p).first() or None,
                max_turns_override=max_turns_override,
                language_override=language_override,
            )
            submit_audit_run(run)
            return redirect(f"/audits/{run.id}/")
        except Exception as e:
            return self.render_to_response(self.get_context_data(error=str(e)))


# ─── Queue ───────────────────────────────────────────────────────────────────

class QueueView(ProjectMixin, TemplateView):
    template_name = "queue.html"

    def get_context_data(self, **kw):
        runs = (
            AuditRun.objects.filter(project=self.request.project)
            .select_related("scenario_set_version__scenario_set")
            .order_by("-created_at")[:100]
        )
        active_statuses = ["queued", "preparing", "target_execution", "auditing", "judging", "aggregation"]
        kw.update(
            active=[r for r in runs if r.status in active_statuses],
            finished=[r for r in runs if r.status not in active_statuses],
        )
        return super().get_context_data(**kw)


# ─── Scenarios ───────────────────────────────────────────────────────────────

class ScenariosView(ProjectMixin, TemplateView):
    template_name = "scenarios.html"

    def get_context_data(self, **kw):
        p = self.request.project
        sets = ScenarioSet.objects.filter(project=p).prefetch_related("versions__items__scenario").order_by("name")
        selected = None
        items = []
        if self.request.GET.get("set"):
            selected = ScenarioSet.objects.filter(pk=self.request.GET["set"], project=p).first()
            if selected:
                latest = selected.versions.order_by("-version").first()
                if latest:
                    items = list(latest.items.select_related("scenario", "revision"))
        kw.update(sets=sets, selected=selected, items=items)
        return super().get_context_data(**kw)


class ScenarioCreateView(ProjectMixin, View):
    def post(self, request):
        name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "").strip()
        desc = request.POST.get("description", "")
        set_id = request.POST.get("set_id", "").strip()
        if name:
            # Derive a stable key from the name
            key = hashlib.sha256(name.encode()).hexdigest()[:12]
            scenario, _ = Scenario.objects.get_or_create(
                project=request.project, key=key,
                defaults={"title": name, "category": category},
            )
            ScenarioRevision.objects.create(
                scenario=scenario, revision=1, description=desc,
                expected_behavior=[], content_hash=hashlib.sha256(desc.encode()).hexdigest(),
                created_by=request.user,
            )
            messages.success(request, f"Scenario '{name}' added.")
        if set_id:
            return redirect(f"/scenarios/?set={set_id}")
        return redirect("/scenarios/")


class ScenarioDeleteView(ProjectMixin, View):
    def post(self, request, scenario_id):
        Scenario.objects.filter(pk=scenario_id, project=request.project).delete()
        set_id = request.POST.get("set_id", "")
        if set_id:
            return redirect(f"/scenarios/?set={set_id}")
        return redirect("/scenarios/")


class ScenarioPublishView(ProjectMixin, View):
    def post(self, request, set_id):
        sset = ScenarioSet.objects.filter(pk=set_id, project=request.project).first()
        if not sset:
            return redirect("/scenarios/")
        scenario_ids = list(
            ScenarioSetVersionItem.objects.filter(version__scenario_set=sset)
            .values_list("scenario_id", flat=True).distinct()
        )
        # If no items yet, use all project scenarios
        if not scenario_ids:
            scenario_ids = list(Scenario.objects.filter(project=request.project).values_list("id", flat=True))
        try:
            publish_scenario_set_version(scenario_set=sset, user=request.user, scenario_ids=scenario_ids)
        except Exception:
            messages.error(request, "Failed to publish version.")
        return redirect(f"/scenarios/?set={set_id}")


class ScenarioExportView(ProjectMixin, View):
    def get(self, request, set_id):
        sset = ScenarioSet.objects.filter(pk=set_id, project=request.project).first()
        if not sset:
            return JsonResponse({"error": "Not found"}, status=404)
        latest = sset.versions.order_by("-version").first()
        scenarios = [
            {"key": it.scenario.key, "title": it.scenario.title,
             "description": it.revision.description, "category": it.scenario.category}
            for it in latest.items.select_related("scenario", "revision")
        ] if latest else []
        return JsonResponse({"set_name": sset.name, "scenarios": scenarios})


class ScenarioImportView(ProjectMixin, View):
    def post(self, request, set_id):
        sset = ScenarioSet.objects.filter(pk=set_id, project=request.project).first()
        if not sset:
            return JsonResponse({"error": "Not found"}, status=404)
        try:
            data = json.loads(request.body)
            for item in data.get("scenarios", []):
                key = item.get("key", f"imported_{int(timezone.now().timestamp())}")
                scenario, _ = Scenario.objects.get_or_create(
                    project=request.project, key=key,
                    defaults={"title": item.get("title", "Imported"), "category": item.get("category", "")},
                )
                desc = item.get("description", "")
                ScenarioRevision.objects.create(
                    scenario=scenario, revision=scenario.revisions.count() + 1,
                    description=desc, expected_behavior=[],
                    content_hash=hashlib.sha256(desc.encode()).hexdigest(),
                    created_by=request.user,
                )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
        return redirect(f"/scenarios/?set={set_id}")


# ─── Models ──────────────────────────────────────────────────────────────────

class ModelsView(ProjectMixin, TemplateView):
    template_name = "models.html"

    def get_context_data(self, **kw):
        p = self.request.project
        highlight_id = self.request.GET.get("highlight")
        kw.update(
            endpoints=ModelEndpoint.objects.filter(project=p).order_by("display_name"),
            profiles=AuditProfile.objects.filter(project=p).order_by("name"),
            highlight_id=highlight_id,
            error=None,
        )
        return super().get_context_data(**kw)

    def post(self, request, *args, **kwargs):
        p = request.project
        action = request.POST.get("action")
        error = None
        if action == "add_endpoint":
            if not all([request.POST.get(k) for k in ("display_name", "base_url", "model_id")]):
                error = "Name, URL, and model ID are required."
            else:
                ModelEndpoint.objects.create(
                    project=p, display_name=request.POST["display_name"].strip(),
                    base_url=request.POST["base_url"].strip(),
                    model_id=request.POST["model_id"].strip(),
                    provider=request.POST.get("provider", "openai"),
                    created_by=request.user,
                )
        elif action == "add_profile":
            if not request.POST.get("profile_name", "").strip():
                error = "Profile name is required."
            else:
                AuditProfile.objects.create(
                    project=p, name=request.POST["profile_name"].strip(),
                    max_turns=int(request.POST.get("max_turns", 4)),
                    temperature_target=float(request.POST.get("temp_target", 0.7)),
                    temperature_auditor=float(request.POST.get("temp_auditor", 0.2)),
                    temperature_judge=float(request.POST.get("temp_judge", 0.0)),
                    max_tokens=int(request.POST.get("max_tokens", 2048)),
                    created_by=request.user,
                )
        return self.render_to_response(self.get_context_data(error=error))


class ModelDeleteView(ProjectMixin, View):
    def post(self, request, endpoint_id):
        ModelEndpoint.objects.filter(pk=endpoint_id, project=request.project).delete()
        return redirect("/models/")


# ─── Compare ─────────────────────────────────────────────────────────────────

class CompareView(ProjectMixin, TemplateView):
    template_name = "compare.html"

    def get_context_data(self, **kw):
        kw["runs"] = AuditRun.objects.filter(project=self.request.project, status="completed").order_by("-created_at")[:20]
        kw.setdefault("result", None)
        return super().get_context_data(**kw)

    def post(self, request, *args, **kwargs):
        ids = [int(x) for x in request.POST.getlist("runs[]") if x.isdigit()]
        raw = compare_runs(request.project, ids) if len(ids) >= 2 else None
        # Reshape for template
        result = None
        if raw:
            columns = [f"#{r['id']} ({r['target'] or '?'})" for r in raw["runs"]]
            rows = []
            for entry in raw["results"]:
                values = []
                for col_run_id in [str(r["id"]) for r in raw["runs"]]:
                    rdata = entry["runs"].get(col_run_id, {})
                    values.append(rdata.get("severity") or rdata.get("status") or "—")
                rows.append({"scenario": entry["scenario_key"], "values": values})
            # Per-run link metadata
            run_meta = []
            for r in raw["runs"]:
                run_obj = AuditRun.objects.filter(id=r["id"]).select_related(
                    "target_endpoint", "auditor_endpoint", "judge_endpoint",
                    "scenario_set_version__scenario_set"
                ).first()
                run_meta.append({
                    "id": r["id"],
                    "target_endpoint_id": run_obj.target_endpoint_id if run_obj else None,
                    "auditor_endpoint_id": run_obj.auditor_endpoint_id if run_obj else None,
                    "judge_endpoint_id": run_obj.judge_endpoint_id if run_obj else None,
                    "scenario_set_id": run_obj.scenario_set_version.scenario_set_id if run_obj and run_obj.scenario_set_version else None,
                })
            result = {
                "warnings": raw["warnings"],
                "columns": columns,
                "rows": rows,
                "inputs": raw.get("inputs", []),
                "run_meta": run_meta,
                "intersection_count": raw["intersection_count"],
            }
        return self.render_to_response(self.get_context_data(result=result))


# ─── Audit Detail ────────────────────────────────────────────────────────────

class AuditDetailView(ProjectMixin, DetailView):
    template_name = "audit_detail.html"
    context_object_name = "run"
    pk_url_kwarg = "run_id"
    queryset = AuditRun.objects.select_related(
        "scenario_set_version__scenario_set", "target_endpoint", "auditor_endpoint", "judge_endpoint"
    )

    def get_queryset(self):
        return self.queryset.filter(project=self.request.project)

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        run = self.object
        set_id = run.scenario_set_version.scenario_set_id
        items = {str(vi.pk): vi for vi in ScenarioSetVersionItem.objects.filter(version=run.scenario_set_version).select_related("scenario")}
        results = []
        for sr in ScenarioResult.objects.filter(run_id=run.id):
            item = items.get(sr.version_item_id)
            r = sr.result or {}
            results.append({
                "scenario_name": item.scenario.title if item else sr.version_item_id,
                "scenario_id": item.scenario_id if item else None,
                "set_id": set_id,
                "severity": r.get("severity", sr.status),
                "summary": r.get("summary", ""),
                "status": sr.status,
            })
        ctx["results"] = results
        ctx["set_id"] = set_id
        ctx["stages"] = ["queued", "preparing", "target_execution", "auditing", "judging", "aggregation", "completed"]
        return ctx


class AuditCancelView(ProjectMixin, View):
    def post(self, request, run_id):
        run = AuditRun.objects.filter(pk=run_id, project=request.project).first()
        if run and run.status not in (AuditRun.Status.COMPLETED, AuditRun.Status.FAILED, AuditRun.Status.CANCELLED):
            run.status = AuditRun.Status.CANCELLED
            run.save(update_fields=["status"])
        return redirect(f"/audits/{run_id}/")
