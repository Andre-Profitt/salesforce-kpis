"""
FastAPI server for observability endpoints.

Provides:
- GET /metrics - Prometheus metrics in exposition format
- GET /healthz - Health check endpoint
- GET /ready - Readiness probe
- GET /version - Version information
"""

import os
import time
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import FastAPI, Response, status
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import structlog

from app.web.metrics import metrics_registry, system_info
from app.web.logging import configure_logging

# Configure logging
logger = configure_logging(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    json_format=os.getenv('LOG_FORMAT', 'json') == 'json',
    service_name='salesforce-kpis'
)

# Create FastAPI app
app = FastAPI(
    title="Salesforce KPIs",
    description="Real-time lead routing and TTFR tracking with Salesforce CDC",
    version=os.getenv('APP_VERSION', 'v2.0.0'),
    docs_url="/docs",
    redoc_url="/redoc"
)

# Application state
app_state = {
    'started_at': datetime.utcnow().isoformat() + 'Z',
    'ready': False,
    'health_checks': {}
}


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    logger.info("Application starting", version=app.version)

    # Set system info metric
    system_info.labels(
        version=app.version,
        environment=os.getenv('ENVIRONMENT', 'development')
    ).set(1)

    logger.info("Application started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on shutdown."""
    logger.info("Application shutting down")


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus exposition format.

    Exposed metrics:
    - cdc_events_total{object, change_type}
    - cdc_lag_seconds{object}
    - cdc_errors_total{object, error_type}
    - first_response_latency_seconds (histogram)
    - first_response_updates_total{outcome}
    - decisions_total{workload, outcome}
    - assignment_latency_seconds (histogram)
    - auth_requests_total{status}
    - auth_latency_seconds (histogram)
    - errors_total{area, error_type}
    - system_info{version, environment}
    """
    return Response(
        content=generate_latest(metrics_registry),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/healthz")
async def healthz():
    """
    Health check endpoint.

    Returns 200 if service is alive (responds to requests).
    Used by Kubernetes liveness probes.

    Returns:
        Health status with uptime
    """
    uptime_seconds = (
        datetime.utcnow() -
        datetime.fromisoformat(app_state['started_at'].replace('Z', '+00:00'))
    ).total_seconds()

    return {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'uptime_seconds': int(uptime_seconds),
        'version': app.version
    }


@app.get("/ready")
async def readyz(response: Response):
    """
    Readiness check endpoint.

    Returns 200 if service is ready to accept traffic.
    Returns 503 if not ready (e.g., still initializing).
    Used by Kubernetes readiness probes.

    Returns:
        Readiness status with component checks
    """
    # Check if all required components are ready
    checks = {
        'metrics': True,  # Metrics always available
        'logging': True,  # Logging always available
    }

    # Add additional health checks from app state
    checks.update(app_state.get('health_checks', {}))

    all_ready = all(checks.values())

    if not all_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        'ready': all_ready,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'checks': checks,
        'version': app.version
    }


@app.get("/version")
async def version():
    """
    Version information endpoint.

    Returns:
        Version and build information
    """
    return {
        'version': app.version,
        'environment': os.getenv('ENVIRONMENT', 'development'),
        'python_version': os.getenv('PYTHON_VERSION', 'unknown'),
        'started_at': app_state['started_at']
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.

    Returns:
        API information and available endpoints
    """
    return {
        'service': 'Salesforce KPIs',
        'version': app.version,
        'endpoints': {
            'metrics': '/metrics',
            'health': '/healthz',
            'ready': '/ready',
            'version': '/version',
            'docs': '/docs'
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }


def set_health_check(component: str, healthy: bool):
    """
    Update health check status for a component.

    Args:
        component: Component name (e.g., 'cdc_subscriber', 'salesforce')
        healthy: Whether component is healthy
    """
    app_state['health_checks'][component] = healthy
    logger.info(
        "Health check updated",
        component=component,
        healthy=healthy
    )


def mark_ready():
    """Mark application as ready to accept traffic."""
    app_state['ready'] = True
    logger.info("Application marked ready")


def mark_not_ready():
    """Mark application as not ready (e.g., during graceful shutdown)."""
    app_state['ready'] = False
    logger.info("Application marked not ready")


# Development server
if __name__ == '__main__':
    import uvicorn

    uvicorn.run(
        "app.web.server:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info"
    )
