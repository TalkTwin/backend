# Prometheus metrics (doc 9.2). Own registry (test-safe), route-template labels
# (never raw ids — cardinality), /metrics itself excluded from recording.
import time

from prometheus_client import CollectorRegistry, Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector
from starlette.middleware.base import BaseHTTPMiddleware

registry = CollectorRegistry()
ProcessCollector(registry=registry)
PlatformCollector(registry=registry)

REQUESTS = Counter(
    "http_requests_total", "HTTP requests",
    ["method", "route", "status"], registry=registry,
)
LATENCY = Histogram(
    "http_request_seconds", "HTTP latency",
    ["route"], registry=registry,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        # template from path_params (keeps /v1 prefixes, never raw ids)
        template = request.url.path
        for key, val in request.scope.get("path_params", {}).items():
            template = template.replace(str(val), "{" + key + "}", 1)
        REQUESTS.labels(request.method, template, response.status_code).inc()
        LATENCY.labels(template).observe(time.perf_counter() - start)
        return response


def exposition() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
