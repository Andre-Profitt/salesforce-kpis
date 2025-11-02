"""
Flywheel decision log emitter.

Emits decision logs in OpenAI-compatible JSONL format for:
- LLM training data collection
- Decision history and audit trail
- Continuous improvement via flywheel

Each log entry contains:
- Request context (lead data, policy version)
- Response (decision, owner assignment)
- Metadata (timestamps, latency, outcome)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from threading import Lock

from app.flywheel.schema import FlywheelRecord, Request, Response, Message

logger = logging.getLogger(__name__)


class FlywheelEmitter:
    """
    Emits flywheel decision logs to JSONL files.

    Thread-safe append-only logging for decision history.
    """

    def __init__(self, log_dir: str = "data/flywheel"):
        """
        Initialize emitter.

        Args:
            log_dir: Directory for flywheel logs (default: data/flywheel)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._lock = Lock()

        logger.info(
            "FlywheelEmitter initialized",
            extra={'log_dir': str(self.log_dir)}
        )

    def _get_log_file(self, workload_id: str) -> Path:
        """
        Get log file path for workload.

        Args:
            workload_id: Workload identifier (e.g., 'lead.route', 'first_touch')

        Returns:
            Path to log file (e.g., data/flywheel/lead.route.jsonl)
        """
        # Sanitize workload_id for filename
        safe_workload = workload_id.replace('/', '_').replace(' ', '_')
        return self.log_dir / f"{safe_workload}.jsonl"

    def emit(self, record: FlywheelRecord):
        """
        Emit a flywheel record to JSONL log.

        Args:
            record: Flywheel record (validated Pydantic model)
        """
        log_file = self._get_log_file(record.workload_id)

        # Serialize to JSON
        record_json = record.model_dump_json()

        # Thread-safe append
        with self._lock:
            with open(log_file, 'a') as f:
                f.write(record_json + '\n')

        logger.debug(
            "Flywheel record emitted",
            extra={
                'workload_id': record.workload_id,
                'client_id': record.client_id,
                'log_file': str(log_file)
            }
        )

    def emit_routing_decision(
        self,
        lead_id: str,
        lead_data: Dict[str, Any],
        decision: Dict[str, Any],
        policy_version: str,
        latency_ms: float
    ):
        """
        Emit a lead routing decision.

        Args:
            lead_id: Lead ID
            lead_data: Lead context (company, employees, country)
            decision: Routing decision (segment, region, owner)
            policy_version: Policy version used
            latency_ms: Decision latency in milliseconds
        """
        # Build request messages
        system_prompt = f"""You are a lead routing assistant using policy {policy_version}.

Route leads to the appropriate owner based on:
- Segment (based on employee count)
- Region (based on country)
- Owner availability"""

        user_prompt = f"""Route this lead:
Company: {lead_data.get('Company', 'Unknown')}
Employees: {lead_data.get('NumberOfEmployees', 0)}
Country: {lead_data.get('Country', 'Unknown')}"""

        request = Request(
            model="policy-based-routing",
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ]
        )

        # Build response
        response_content = json.dumps({
            'segment': decision.get('segment'),
            'region': decision.get('region'),
            'owner_id': decision.get('owner_id'),
            'outcome': decision.get('outcome')
        })

        response = Response(
            id=f"routing-{lead_id}-{int(datetime.utcnow().timestamp())}",
            created=int(datetime.utcnow().timestamp()),
            model="policy-based-routing",
            choices=[{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': response_content
                },
                'finish_reason': 'stop'
            }]
        )

        # Create flywheel record
        record = FlywheelRecord(
            timestamp=int(datetime.utcnow().timestamp()),
            client_id=lead_id,
            workload_id="lead.route",
            request=request,
            response=response,
            lead_id=lead_id,
            policy_version=policy_version,
            metadata={
                'latency_ms': latency_ms,
                'outcome': decision.get('outcome'),
                'lead_data': lead_data
            }
        )

        self.emit(record)

    def emit_first_touch_detection(
        self,
        lead_id: str,
        candidate_response: Dict[str, Any],
        detection_result: Dict[str, Any],
        latency_ms: float
    ):
        """
        Emit a first touch detection event.

        Args:
            lead_id: Lead ID
            candidate_response: Candidate response info (timestamp, user, source)
            detection_result: Detection result (status, reason, TTFR)
            latency_ms: Detection latency in milliseconds
        """
        system_prompt = """You are a first response detector.

Determine if a candidate response is the earliest response to a lead.
Only update if the candidate is strictly earlier than existing response."""

        user_prompt = f"""Candidate response:
Source: {candidate_response.get('source')}
User: {candidate_response.get('user_id')}
Timestamp: {candidate_response.get('timestamp')}
Existing: {candidate_response.get('existing_timestamp', 'None')}"""

        request = Request(
            model="idempotent-first-touch",
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ]
        )

        response_content = json.dumps({
            'status': detection_result.get('status'),
            'reason': detection_result.get('reason'),
            'ttfr_minutes': detection_result.get('ttfr_minutes')
        })

        response = Response(
            id=f"first-touch-{lead_id}-{int(datetime.utcnow().timestamp())}",
            created=int(datetime.utcnow().timestamp()),
            model="idempotent-first-touch",
            choices=[{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': response_content
                },
                'finish_reason': 'stop'
            }]
        )

        record = FlywheelRecord(
            timestamp=int(datetime.utcnow().timestamp()),
            client_id=lead_id,
            workload_id="first_touch.detect",
            request=request,
            response=response,
            lead_id=lead_id,
            metadata={
                'latency_ms': latency_ms,
                'outcome': detection_result.get('status'),
                'candidate_response': candidate_response
            }
        )

        self.emit(record)

    def get_workload_logs(self, workload_id: str, limit: Optional[int] = None) -> list:
        """
        Read flywheel logs for a workload.

        Args:
            workload_id: Workload identifier
            limit: Optional limit on number of records (reads last N)

        Returns:
            List of flywheel records
        """
        log_file = self._get_log_file(workload_id)

        if not log_file.exists():
            return []

        records = []

        with open(log_file, 'r') as f:
            for line in f:
                if line.strip():
                    record_dict = json.loads(line)
                    records.append(record_dict)

        # Apply limit (last N records)
        if limit:
            records = records[-limit:]

        return records

    def get_stats(self, workload_id: str) -> Dict[str, Any]:
        """
        Get statistics for a workload's flywheel logs.

        Args:
            workload_id: Workload identifier

        Returns:
            Statistics dictionary
        """
        records = self.get_workload_logs(workload_id)

        if not records:
            return {
                'total_records': 0,
                'workload_id': workload_id
            }

        # Calculate stats
        outcomes = {}
        for record in records:
            outcome = record.get('metadata', {}).get('outcome', 'unknown')
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

        return {
            'total_records': len(records),
            'workload_id': workload_id,
            'outcomes': outcomes,
            'first_timestamp': records[0].get('timestamp') if records else None,
            'last_timestamp': records[-1].get('timestamp') if records else None
        }
