"""Root URL configuration for SimpleAudit Platform."""
import os as _os

from django.conf import settings
from django.contrib import admin
from django.http import Http404
from django.urls import include, path
from django.views.static import serve as _static_serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.ui import spa
from core.views import healthz, readyz

# --- Static file serving ---------------------------------------------------
# For the canonical Docker Compose self-hosted deployment Django serves its
# own static files (no reverse proxy needed). collectstatic runs at image
# build time (see Dockerfile). We use django.views.static.serve (not the
# staticfiles app's serve) because the latter refuses to serve when DEBUG=False.
_STATIC_ROOT = str(settings.STATIC_ROOT)


def _serve_static(request, path):
    """Serve from STATIC_ROOT if present, else fall back to finders (dev)."""
    full_path = _os.path.join(_STATIC_ROOT, path)
    if _os.path.isfile(full_path):
        return _static_serve(request, path, document_root=_STATIC_ROOT)
    from django.contrib.staticfiles.finders import find

    found = find(path)
    if found:
        import posixpath

        return _static_serve(request, path, document_root=posixpath.dirname(found))
    raise Http404(f"Static file not found: {path}")


# --- URL patterns ----------------------------------------------------------
# Order matters: static + API routes must come BEFORE the SPA catch-all.
urlpatterns = [
    path("static/<path:path>", _serve_static, name="static-serve"),
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/auth/", include("core.auth_urls")),
    path("api/projects/", include("core.project_urls")),
    path("api/", include("core.scenario_urls")),
    path("api/", include("core.model_registry_urls")),
    path("api/", include("core.audit_urls")),
    # SPA shell for all non-API, non-static routes (client-side navigation).
    path("", spa, name="spa"),
]
