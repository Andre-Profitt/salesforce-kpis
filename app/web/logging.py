"""
Structured JSON logging configuration.

Provides:
- JSON-formatted logs for production
- Human-readable logs for development
- Request ID tracking
- Contextual logging with extra fields
"""

import sys
import logging
import structlog
from typing import Any, Dict
from datetime import datetime


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
    service_name: str = "salesforce-kpis"
):
    """
    Configure structured logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON output (True) or human-readable (False)
        service_name: Service name to include in logs
    """
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper())
    )

    # Configure structlog
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_format:
        # JSON output for production
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Human-readable for development
        processors.extend([
            structlog.dev.ConsoleRenderer(colors=True)
        ])

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Add service name to all logs
    logger = structlog.get_logger()
    logger = logger.bind(service=service_name)

    return logger


def add_request_context(request_id: str, user_id: str = None) -> Dict[str, Any]:
    """
    Create request context for logging.

    Args:
        request_id: Unique request identifier
        user_id: Optional user identifier

    Returns:
        Context dictionary
    """
    context = {
        'request_id': request_id,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }

    if user_id:
        context['user_id'] = user_id

    return context


class LogContext:
    """
    Context manager for structured logging.

    Usage:
        with LogContext(logger, request_id='abc123', lead_id='00Qxx...'):
            logger.info("Processing lead")
    """

    def __init__(self, logger, **context):
        self.logger = logger
        self.context = context
        self.bound_logger = None

    def __enter__(self):
        self.bound_logger = self.logger.bind(**self.context)
        return self.bound_logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.bound_logger.error(
                "Exception in context",
                exc_info=(exc_type, exc_val, exc_tb)
            )
        return False


def log_decision(
    logger,
    workload: str,
    lead_id: str,
    decision: Dict[str, Any],
    latency_ms: float
):
    """
    Log a routing or template decision.

    Args:
        logger: Structured logger
        workload: Workload type (e.g., 'lead.route', 'template.recommend')
        lead_id: Lead ID
        decision: Decision dictionary
        latency_ms: Decision latency in milliseconds
    """
    logger.info(
        "Decision made",
        workload=workload,
        lead_id=lead_id,
        decision=decision,
        latency_ms=latency_ms
    )


def log_first_response(
    logger,
    lead_id: str,
    response_at: str,
    user_id: str,
    source: str,
    ttfr_minutes: int,
    outcome: str
):
    """
    Log a first response detection.

    Args:
        logger: Structured logger
        lead_id: Lead ID
        response_at: Response timestamp
        user_id: Responding user
        source: Response source (Task, EmailMessage)
        ttfr_minutes: Time to first response in minutes
        outcome: Detection outcome (updated, skipped_earlier, etc.)
    """
    logger.info(
        "First response detected",
        lead_id=lead_id,
        response_at=response_at,
        user_id=user_id,
        source=source,
        ttfr_minutes=ttfr_minutes,
        outcome=outcome
    )


def log_cdc_event(
    logger,
    channel: str,
    change_type: str,
    record_ids: list,
    replay_id: str,
    lag_seconds: float
):
    """
    Log a CDC event processing.

    Args:
        logger: Structured logger
        channel: CDC channel
        change_type: Change type (CREATE, UPDATE, DELETE)
        record_ids: Affected record IDs
        replay_id: Replay ID
        lag_seconds: Processing lag in seconds
    """
    logger.info(
        "CDC event processed",
        channel=channel,
        change_type=change_type,
        record_ids=record_ids,
        replay_id=replay_id,
        lag_seconds=lag_seconds
    )


def log_error(
    logger,
    area: str,
    error_type: str,
    message: str,
    **context
):
    """
    Log an error with context.

    Args:
        logger: Structured logger
        area: Error area (e.g., 'cdc', 'auth', 'routing')
        error_type: Error type (e.g., 'AuthenticationError', 'ValidationError')
        message: Error message
        **context: Additional context
    """
    logger.error(
        message,
        area=area,
        error_type=error_type,
        **context
    )
