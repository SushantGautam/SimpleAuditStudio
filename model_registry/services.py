"""Services for model registry and audit profiles."""
from django.db import IntegrityError, transaction

from infra.exceptions import StableAPIError
from model_registry.models import AuditProfile, ModelEndpoint
from accounts.models import Project
from scenarios.services import require_project_role


def _validate_secret_reference(secret_reference: str) -> str:
    normalized = (secret_reference or "").strip()
    if not normalized:
        return ""
    if not all(char.isalnum() or char in {"_", "-"} for char in normalized):
        raise StableAPIError(detail="Secret reference must be an environment-style identifier.", code="invalid_secret_reference")
    return normalized


@transaction.atomic
def create_model_endpoint(*, project: Project, user, display_name: str, provider: str, base_url: str, model_id: str, model_revision: str = "", capabilities: dict | None = None, default_parameters: dict | None = None, secret_reference: str = "") -> ModelEndpoint:
    require_project_role(user, project)
    try:
        return ModelEndpoint.objects.create(
            project=project,
            display_name=display_name.strip(),
            provider=provider.strip(),
            base_url=base_url.strip(),
            model_id=model_id.strip(),
            model_revision=model_revision.strip(),
            capabilities=capabilities or {},
            default_parameters=default_parameters or {},
            secret_reference=_validate_secret_reference(secret_reference),
            created_by=user,
        )
    except IntegrityError as exc:
        # (project_id, display_name) is unique. Surface a clean 409 rather than
        # leaking a raw 500 to the client.
        raise StableAPIError(detail="A model endpoint with this display name already exists in the project.", code="duplicate_display_name", http_status=409) from exc


@transaction.atomic
def create_audit_profile(*, project: Project, user, name: str, max_turns: int = 4, temperature_target: float = 0.7, temperature_auditor: float = 0.2, temperature_judge: float = 0.0, top_p: float = 1.0, max_tokens: int = 2048, retry_policy: dict | None = None, timeout_seconds: int = 300, concurrency: int = 1, language: str = "en") -> AuditProfile:
    require_project_role(user, project)
    return AuditProfile.objects.create(
        project=project,
        name=name.strip(),
        max_turns=max_turns,
        temperature_target=temperature_target,
        temperature_auditor=temperature_auditor,
        temperature_judge=temperature_judge,
        top_p=top_p,
        max_tokens=max_tokens,
        retry_policy=retry_policy or {},
        timeout_seconds=timeout_seconds,
        concurrency=concurrency,
        language=language.strip() or "en",
        created_by=user,
    )
