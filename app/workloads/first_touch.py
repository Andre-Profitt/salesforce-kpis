"""
Idempotent TTFR (Time-to-First-Response) detection.

Single source of truth for first response detection with strict ordering
and idempotency guarantees.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from dateutil import parser as date_parser
from prometheus_client import Histogram, Counter

logger = logging.getLogger(__name__)

# Metrics
first_response_latency_seconds = Histogram(
    'first_response_latency_seconds',
    'Time from lead creation to first response',
    buckets=[60, 300, 900, 1800, 3600, 7200, 14400, 28800, 86400]  # 1m to 24h
)

first_response_updates = Counter(
    'first_response_updates_total',
    'First response updates',
    ['outcome']  # updated, skipped_later, skipped_existing
)


def parse_dt(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string."""
    if not dt_str:
        return None
    try:
        return date_parser.parse(dt_str)
    except Exception:
        return None


def iso(dt: datetime) -> str:
    """Format datetime as ISO string."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')


class FirstTouchDetector:
    """
    Idempotent first touch detection.

    Guarantees:
    - Only writes if candidate response is strictly earlier than existing
    - Handles Task vs EmailMessage ordering correctly
    - All 4 fields updated atomically
    """

    def __init__(self, sf_client):
        """
        Initialize detector.

        Args:
            sf_client: Salesforce API client (must have get_record, update_record methods)
        """
        self.sf = sf_client

    def detect_first_touch(
        self,
        lead_id: str,
        candidate_dt: datetime,
        user_id: str,
        source: str
    ) -> Dict[str, Any]:
        """
        Detect and record first touch (idempotent).

        Args:
            lead_id: Salesforce Lead ID
            candidate_dt: DateTime of potential first response
            user_id: Salesforce User ID who responded
            source: Source type ('Task' or 'EmailMessage')

        Returns:
            Result dict with status and details
        """
        logger.info(
            "Checking first touch",
            extra={
                'lead_id': lead_id,
                'candidate_dt': candidate_dt.isoformat(),
                'user_id': user_id,
                'source': source
            }
        )

        # Get current first response state
        try:
            lead = self.sf.get_record(
                'Lead',
                lead_id,
                fields=[
                    'Id',
                    'CreatedDate',
                    'First_Response_At__c',
                    'First_Response_User__c',
                    'First_Response_Source__c',
                    'Time_to_First_Response__c'
                ]
            )
        except Exception as e:
            logger.error(
                "Failed to get lead",
                extra={'lead_id': lead_id, 'error': str(e)}
            )
            first_response_updates.labels(outcome='error').inc()
            return {'status': 'error', 'error': str(e)}

        # Check if existing first response is earlier
        existing_dt = parse_dt(lead.get('First_Response_At__c'))

        if existing_dt:
            if existing_dt <= candidate_dt:
                logger.info(
                    "Existing first response is earlier, skipping",
                    extra={
                        'lead_id': lead_id,
                        'existing': existing_dt.isoformat(),
                        'candidate': candidate_dt.isoformat()
                    }
                )
                first_response_updates.labels(outcome='skipped_earlier').inc()
                return {
                    'status': 'skipped',
                    'reason': 'existing_earlier',
                    'existing_dt': existing_dt.isoformat(),
                    'candidate_dt': candidate_dt.isoformat()
                }

        # Candidate is earlier (or no existing) - update
        created_dt = parse_dt(lead['CreatedDate'])
        if not created_dt:
            logger.error("Lead missing CreatedDate", extra={'lead_id': lead_id})
            first_response_updates.labels(outcome='error').inc()
            return {'status': 'error', 'error': 'Missing CreatedDate'}

        # Calculate TTFR in minutes
        ttfr_seconds = (candidate_dt - created_dt).total_seconds()
        ttfr_minutes = int(ttfr_seconds / 60)

        # Update all 4 fields atomically
        try:
            self.sf.update_record(
                'Lead',
                lead_id,
                {
                    'First_Response_At__c': iso(candidate_dt),
                    'First_Response_User__c': user_id,
                    'First_Response_Source__c': source,
                    'Time_to_First_Response__c': ttfr_minutes
                }
            )

            # Record metrics
            first_response_latency_seconds.observe(ttfr_seconds)
            first_response_updates.labels(outcome='updated').inc()

            logger.info(
                "First touch recorded",
                extra={
                    'lead_id': lead_id,
                    'ttfr_minutes': ttfr_minutes,
                    'source': source,
                    'user_id': user_id
                }
            )

            return {
                'status': 'updated',
                'lead_id': lead_id,
                'first_response_at': candidate_dt.isoformat(),
                'first_response_user_id': user_id,
                'first_response_source': source,
                'ttfr_minutes': ttfr_minutes,
                'ttfr_seconds': ttfr_seconds,
                'replaced_existing': existing_dt is not None
            }

        except Exception as e:
            logger.error(
                "Failed to update first touch",
                extra={'lead_id': lead_id, 'error': str(e)}
            )
            first_response_updates.labels(outcome='error').inc()
            return {'status': 'error', 'error': str(e)}

    def find_and_record_first_touch(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """
        Query for first response and record if found.

        Single source of truth for what constitutes "first response":
        - Earliest Completed Task with Type in (Call, Email, Meeting) and WhoId = Lead
        - OR earliest EmailMessage related to Lead

        Args:
            lead_id: Salesforce Lead ID

        Returns:
            Result dict or None if no response found
        """
        # Query earliest Task
        task_soql = f"""
            SELECT Id, CreatedDate, OwnerId, Type
            FROM Task
            WHERE WhoId = '{lead_id}'
            AND Status = 'Completed'
            AND Type IN ('Call', 'Email', 'Meeting')
            ORDER BY CreatedDate ASC
            LIMIT 1
        """

        # Query earliest EmailMessage
        email_soql = f"""
            SELECT Id, MessageDate, CreatedById
            FROM EmailMessage
            WHERE RelatedToId = '{lead_id}'
            ORDER BY MessageDate ASC
            LIMIT 1
        """

        try:
            tasks = self.sf.query(task_soql)
            emails = self.sf.query(email_soql)
        except Exception as e:
            logger.error("Failed to query first response", extra={'error': str(e)})
            return {'status': 'error', 'error': str(e)}

        # Determine earliest
        earliest_task_dt = None
        earliest_email_dt = None
        task_user_id = None
        email_user_id = None

        if tasks:
            earliest_task_dt = parse_dt(tasks[0]['CreatedDate'])
            task_user_id = tasks[0]['OwnerId']

        if emails:
            earliest_email_dt = parse_dt(emails[0]['MessageDate'])
            email_user_id = emails[0]['CreatedById']

        # Pick the earliest
        if earliest_task_dt and earliest_email_dt:
            if earliest_task_dt <= earliest_email_dt:
                return self.detect_first_touch(
                    lead_id, earliest_task_dt, task_user_id, 'Task'
                )
            else:
                return self.detect_first_touch(
                    lead_id, earliest_email_dt, email_user_id, 'EmailMessage'
                )
        elif earliest_task_dt:
            return self.detect_first_touch(
                lead_id, earliest_task_dt, task_user_id, 'Task'
            )
        elif earliest_email_dt:
            return self.detect_first_touch(
                lead_id, earliest_email_dt, email_user_id, 'EmailMessage'
            )

        # No response found
        logger.info("No first response found", extra={'lead_id': lead_id})
        return None
