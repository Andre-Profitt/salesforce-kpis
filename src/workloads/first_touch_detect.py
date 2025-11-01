"""
First touch detection workload.

Detects first response to a lead and calculates time-to-first-response (TTFR).
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional
import structlog
from dateutil import parser as date_parser
from src.salesforce.api_client import SalesforceAPIClient
from src.flywheel.logger import FlywheelLogger

logger = structlog.get_logger()


class FirstTouchDetector:
    """Detects and tracks first responses to leads."""

    def __init__(
        self,
        sf_client: SalesforceAPIClient,
        flywheel_logger: FlywheelLogger
    ):
        """
        Initialize first touch detector.

        Args:
            sf_client: Salesforce API client
            flywheel_logger: Flywheel logger
        """
        self.sf_client = sf_client
        self.flywheel_logger = flywheel_logger

    def detect_first_touch(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """
        Detect first touch for a lead and update Salesforce.

        Args:
            lead_id: Salesforce Lead ID

        Returns:
            First touch details or None if already tracked or not found
        """
        logger.info("detecting_first_touch", lead_id=lead_id)

        # Check if lead already has first response tracked
        lead = self.sf_client.get_record(
            "Lead",
            lead_id,
            fields=["Id", "CreatedDate", "First_Response_At__c", "First_Response_User__c"]
        )

        if lead.get("First_Response_At__c"):
            logger.info("first_touch_already_tracked", lead_id=lead_id)
            return None

        # Get first response from Tasks/EmailMessages
        first_response = self.sf_client.get_lead_first_response(lead_id)

        if not first_response:
            logger.info("no_first_response_found", lead_id=lead_id)
            return None

        # Calculate TTFR
        lead_created = date_parser.parse(lead["CreatedDate"])
        first_response_at = date_parser.parse(first_response["datetime"])

        ttfr_delta = first_response_at - lead_created
        ttfr_minutes = ttfr_delta.total_seconds() / 60

        logger.info(
            "first_touch_detected",
            lead_id=lead_id,
            ttfr_minutes=ttfr_minutes,
            response_type=first_response["type"]
        )

        # Update lead in Salesforce
        try:
            self.sf_client.update_lead_first_response(
                lead_id=lead_id,
                first_response_at=first_response["datetime"],
                first_response_user_id=first_response["user_id"],
                ttfr_minutes=ttfr_minutes
            )

            result = {
                "lead_id": lead_id,
                "first_response_at": first_response["datetime"],
                "first_response_user": first_response["user_name"],
                "first_response_user_id": first_response["user_id"],
                "ttfr_minutes": ttfr_minutes,
                "response_type": first_response["type"],
                "status": "tracked"
            }

            # Log to flywheel
            self.flywheel_logger.log_first_touch_detect(
                lead_id=lead_id,
                first_response_data=first_response,
                ttfr_minutes=ttfr_minutes
            )

            logger.info("first_touch_tracked", lead_id=lead_id, ttfr_minutes=ttfr_minutes)

            return result

        except Exception as e:
            logger.error("first_touch_tracking_failed", lead_id=lead_id, error=str(e))
            return {
                "lead_id": lead_id,
                "status": "failed",
                "error": str(e)
            }

    def backfill_missing_first_touches(self, days: int = 30) -> Dict[str, Any]:
        """
        Backfill first touch tracking for leads missing it.

        Args:
            days: Number of days to look back

        Returns:
            Summary of backfill results
        """
        logger.info("starting_first_touch_backfill", days=days)

        # Query leads without first response tracking
        soql = f"""
            SELECT Id, CreatedDate
            FROM Lead
            WHERE CreatedDate = LAST_N_DAYS:{days}
            AND First_Response_At__c = null
            AND IsConverted = false
        """

        leads = self.sf_client.query(soql)

        results = {
            "total_leads": len(leads),
            "tracked": 0,
            "no_response": 0,
            "errors": 0
        }

        for lead in leads:
            result = self.detect_first_touch(lead["Id"])

            if result is None:
                results["no_response"] += 1
            elif result.get("status") == "tracked":
                results["tracked"] += 1
            else:
                results["errors"] += 1

        logger.info("first_touch_backfill_complete", results=results)

        return results


def detect_first_touch_from_event(lead_id: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to detect first touch from CDC event.

    Args:
        lead_id: Lead ID from CDC event

    Returns:
        First touch details or None
    """
    from src.auth.jwt_auth import create_auth_from_env
    from src.flywheel.logger import create_logger_from_env

    auth = create_auth_from_env()
    sf_client = SalesforceAPIClient(auth)
    flywheel_logger = create_logger_from_env()

    detector = FirstTouchDetector(sf_client, flywheel_logger)
    return detector.detect_first_touch(lead_id)


if __name__ == "__main__":
    # Test first touch detection
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--backfill":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            from src.auth.jwt_auth import create_auth_from_env
            from src.flywheel.logger import create_logger_from_env

            auth = create_auth_from_env()
            sf_client = SalesforceAPIClient(auth)
            flywheel_logger = create_logger_from_env()

            detector = FirstTouchDetector(sf_client, flywheel_logger)
            result = detector.backfill_missing_first_touches(days)
            print(json.dumps(result, indent=2))
        else:
            lead_id = sys.argv[1]
            result = detect_first_touch_from_event(lead_id)
            if result:
                print(json.dumps(result, indent=2))
            else:
                print("No first touch detected or already tracked")
    else:
        print("Usage: python first_touch_detect.py <lead_id>")
        print("       python first_touch_detect.py --backfill [days]")
