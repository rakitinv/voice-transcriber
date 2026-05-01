"""Prometheus metrics (Phase C5, ТЗ §16)."""

from __future__ import annotations

import time
from typing import Callable

from prometheus_client import Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS_TOTAL = Counter(
    "vt_http_requests_total",
    "HTTP requests",
    ["method", "handler"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "vt_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "handler"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 60.0, 120.0),
)

UPLOAD_ACCEPTED_TOTAL = Counter(
    "vt_upload_accepted_total",
    "Upload requests accepted (HTTP 202)",
)


def metrics_response() -> Response:
    data = generate_latest()
    return Response(content=data, media_type="text/plain; version=0.0.4; charset=utf-8")


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return str(route.path)
    p = request.url.path
    if len(p) > 64:
        return p[:64] + "…"
    return p or "/"


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if request.url.path == "/metrics":
            return await call_next(request)
        method = request.method
        handler = _route_template(request)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed = time.perf_counter() - start
            HTTP_REQUESTS_TOTAL.labels(method=method, handler=handler).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, handler=handler).observe(
                elapsed
            )
