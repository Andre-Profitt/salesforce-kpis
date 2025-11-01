"""
Centralized Prometheus metrics registry.

Aggregates all metrics from across the application:
- CDC metrics (from app.cdc.subscriber)
- First touch metrics (from app.workloads.first_touch)
- Auth metrics (from app.auth.jwt)
- Decision metrics (for routing and template workloads)
"""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, REGISTRY

# Export default registry for use across application
metrics_registry = REGISTRY

# Decision tracking (routing, template recommendation)
decisions_total = Counter(
    'decisions_total',
    'Total decisions made',
    ['workload', 'outcome']
)

# Assignment latency (lead created → owner assigned)
assignment_latency_seconds = Histogram(
    'assignment_latency_seconds',
    'Time from lead creation to owner assignment',
    buckets=[60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400]  # 1m to 24h
)

# General error tracking
errors_total = Counter(
    'errors_total',
    'Total errors by area',
    ['area', 'error_type']
)

# Active workers gauge
active_workers = Gauge(
    'active_workers',
    'Number of active worker threads/processes',
    ['workload']
)

# API request tracking
api_requests_total = Counter(
    'api_requests_total',
    'Total API requests to Salesforce',
    ['method', 'object', 'status']
)

api_request_duration_seconds = Histogram(
    'api_request_duration_seconds',
    'API request duration',
    ['method', 'object'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# Queue depth (if using internal queues)
queue_depth = Gauge(
    'queue_depth',
    'Number of items in processing queue',
    ['queue_name']
)

# System metrics
system_info = Gauge(
    'system_info',
    'System information',
    ['version', 'environment']
)


def get_all_metrics() -> dict:
    """
    Get all current metric values.

    Returns:
        Dictionary of metric families and their current values
    """
    metrics = {}

    for metric in metrics_registry.collect():
        metric_data = {
            'name': metric.name,
            'type': metric.type,
            'documentation': metric.documentation,
            'samples': []
        }

        for sample in metric.samples:
            metric_data['samples'].append({
                'name': sample.name,
                'labels': sample.labels,
                'value': sample.value
            })

        metrics[metric.name] = metric_data

    return metrics


def reset_metrics():
    """
    Reset all metrics (for testing).

    WARNING: Only use in test environments!
    """
    # This is intentionally minimal - in production, metrics should never reset
    pass
