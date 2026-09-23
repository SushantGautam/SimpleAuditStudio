"""Root URL configuration for SimpleAudit Platform."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.ui import spa
from core.views import healthz, readyz

urlpatterns = [
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
    # SPA shell for all non-API routes (client-side navigation).
    path("", spa, name="spa"),
]

# In DEBUG (local development) serve collected/static files directly. In
# production the reverse proxy / object storage serves STATIC_URL; see
# docs/deployment.md. This keeps `manage.py runserver` fully functional.
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()
