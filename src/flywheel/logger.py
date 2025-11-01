"""
Flywheel logging system.

Captures all agent workload decisions for continuous optimization.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger()


class FlywheelLogger:
    """Logs agent workload decisions in flywheel format."""

    def __init__(self, client_id: str, log_path: str = "./logs/flywheel"):
        """
        Initialize flywheel logger.

        Args:
            client_id: Client identifier (e.g., 'salesforce-prod')
            log_path: Directory for log files
        """
        self.client_id = client_id
        self.log_path = Path(log_path)
        self.log_path.mkdir(parents=True, exist_ok=True)

    def _get_log_file(self, workload_id: str) -> Path:
        """Get log file path for workload."""
        date_str = datetime.utcnow().strftime('%Y-%m-%d')
        filename = f"{workload_id}_{date_str}.jsonl"
        return self.log_path / filename

    def log_decision(
        self,
        workload_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a workload decision in flywheel format.

        Args:
            workload_id: Workload identifier (e.g., 'lead.route', 'outreach.template_suggest')
            request: Input to the workload (messages, context)
            response: Output from the workload (decisions, recommendations)
            metadata: Additional metadata (lead_id, user_id, etc.)
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "client_id": self.client_id,
            "workload_id": workload_id,
            "request": request,
            "response": response
        }

        if metadata:
            log_entry["metadata"] = metadata

        log_file = self._get_log_file(workload_id)

        try:
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

            logger.info(
                "flywheel_log_written",
                workload=workload_id,
                file=str(log_file)
            )

        except Exception as e:
            logger.error("failed_to_write_flywheel_log", error=str(e), workload=workload_id)

    def log_lead_route(
        self,
        lead_id: str,
        lead_data: Dict[str, Any],
        routing_decision: Dict[str, Any],
        model_used: str = "gpt-4"
    ) -> None:
        """
        Log lead routing decision.

        Args:
            lead_id: Lead ID
            lead_data: Lead fields used for routing
            routing_decision: Routing decision (segment, region, owner, reason)
            model_used: LLM model identifier
        """
        request = {
            "messages": [
                {
                    "role": "user",
                    "content": f"Lead: {lead_data.get('Company', 'Unknown')}; "
                               f"{lead_data.get('NumberOfEmployees', 'N/A')} employees; "
                               f"{lead_data.get('Country', 'Unknown')}; "
                               f"product={lead_data.get('Product_Interest__c', 'Unknown')}"
                }
            ],
            "model": model_used
        }

        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(routing_decision)
                    }
                }
            ]
        }

        metadata = {
            "lead_id": lead_id,
            "assigned_to": routing_decision.get("owner")
        }

        self.log_decision("lead.route", request, response, metadata)

    def log_first_touch_detect(
        self,
        lead_id: str,
        first_response_data: Dict[str, Any],
        ttfr_minutes: float
    ) -> None:
        """
        Log first touch detection.

        Args:
            lead_id: Lead ID
            first_response_data: First response details
            ttfr_minutes: Time to first response in minutes
        """
        request = {
            "lead_id": lead_id,
            "detection_method": "task_and_email_query"
        }

        response = {
            "first_response_at": first_response_data.get("datetime"),
            "first_response_user": first_response_data.get("user_id"),
            "ttfr_minutes": ttfr_minutes,
            "response_type": first_response_data.get("type")
        }

        metadata = {
            "lead_id": lead_id,
            "ttfr_minutes": ttfr_minutes
        }

        self.log_decision("lead.first_touch_detect", request, response, metadata)

    def log_template_suggest(
        self,
        lead_id: str,
        inquiry_text: str,
        template_suggestion: Dict[str, Any],
        model_used: str = "claude-3-sonnet"
    ) -> None:
        """
        Log template suggestion.

        Args:
            lead_id: Lead ID
            inquiry_text: Inbound inquiry text
            template_suggestion: Template recommendation (template_id, subject, body, reason)
            model_used: LLM model identifier
        """
        request = {
            "messages": [
                {
                    "role": "user",
                    "content": f"Inbound inquiry: {inquiry_text}"
                }
            ],
            "model": model_used
        }

        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(template_suggestion)
                    }
                }
            ]
        }

        metadata = {
            "lead_id": lead_id,
            "template_id": template_suggestion.get("template_id")
        }

        self.log_decision("outreach.template_suggest", request, response, metadata)

    def get_logs(self, workload_id: str, days: int = 7) -> List[Dict[str, Any]]:
        """
        Retrieve logs for a workload.

        Args:
            workload_id: Workload identifier
            days: Number of days to retrieve

        Returns:
            List of log entries
        """
        logs = []

        for i in range(days):
            date = datetime.utcnow() - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            filename = f"{workload_id}_{date_str}.jsonl"
            log_file = self.log_path / filename

            if log_file.exists():
                try:
                    with open(log_file, 'r') as f:
                        for line in f:
                            logs.append(json.loads(line))
                except Exception as e:
                    logger.error("failed_to_read_flywheel_log", error=str(e), file=str(log_file))

        return logs


def create_logger_from_env() -> FlywheelLogger:
    """
    Create FlywheelLogger from environment variables.

    Required environment variables:
        - FLYWHEEL_CLIENT_ID
        - FLYWHEEL_LOG_PATH (optional, defaults to ./logs/flywheel)

    Returns:
        Configured FlywheelLogger instance
    """
    client_id = os.getenv('FLYWHEEL_CLIENT_ID', 'salesforce-prod')
    log_path = os.getenv('FLYWHEEL_LOG_PATH', './logs/flywheel')

    return FlywheelLogger(client_id=client_id, log_path=log_path)
