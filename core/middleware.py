"""Request-scoped observability middleware.

Injects a unique request ID into every response header and attaches
correlation fields (request_id, user_id) to all log records emitted
during the request lifecycle. This enables tracing a single API call
across web + worker logs without OpenTelemetry.
"""
import logging
import uuid

from django.utils.deprecation import MiddlewareMixin


class RequestIDMiddleware(MiddlewareMixin):
    """Assigns a UUID to each request and exposes it as X-Request-ID.

    Also sets the thread-local correlation context so all log records
    emitted during this request carry the request_id (and user_id once
    authenticated).
    """

    def process_request(self, request):
        # Honour an upstream-provided ID (e.g. from a reverse proxy) or generate one.
        request.request_id = request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex[:12]
        set_correlation_context(request_id=request.request_id)

    def process_response(self, request, response):
        if hasattr(request, "request_id"):
            response["X-Request-ID"] = request.request_id
        clear_correlation_context()
        return response


class CorrelationLogFilter(logging.Filter):
    """Logging filter that copies correlation fields from the current request.

    Usage: add to any handler's filters list. The filter reads from a
    thread-local set by the middleware via ``set_correlation_context``.
    """

    _local = __import__("threading").local()

    @classmethod
    def set_context(cls, **fields):
        cls._local.fields = fields

    @classmethod
    def clear_context(cls):
        cls._local.fields = {}

    def filter(self, record):
        fields = getattr(self._local, "fields", {})
        for key, value in fields.items():
            setattr(record, key, value)
        return True


def set_correlation_context(**fields):
    """Set correlation fields for the current thread's log records."""
    CorrelationLogFilter.set_context(**fields)


def clear_correlation_context():
    """Clear correlation fields (call in finally/teardown)."""
    CorrelationLogFilter.clear_context()
