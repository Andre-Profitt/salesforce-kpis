#!/usr/bin/env python3
"""
Local CDC subscriber test runner.

Feeds sample CDC events through the subscriber to test:
- Replay ID persistence
- Handler invocation
- Metrics collection
- Health status

Usage:
    python scripts/run_cdc_local.py

Environment:
    Requires SF_* environment variables (see .env.example)
"""

import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cdc.subscriber import CDCSubscriber
from app.cdc.replay_store import ReplayStore
from app.workloads.first_touch import FirstTouchDetector
from app.auth.jwt import SalesforceJWT
from app.config import load_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def load_fixture(filename: str) -> dict:
    """Load CDC event fixture."""
    fixture_path = Path(__file__).parent.parent / 'app' / 'cdc' / 'fixtures' / filename
    with open(fixture_path) as f:
        return json.load(f)


def handle_lead_change(payload: dict):
    """Handler for LeadChangeEvent."""
    header = payload.get('ChangeEventHeader', {})
    change_type = header.get('changeType')
    record_ids = header.get('recordIds', [])

    logger.info(
        "Lead change detected",
        extra={
            'change_type': change_type,
            'lead_ids': record_ids,
            'entity': header.get('entityName')
        }
    )

    # In production, this would trigger routing logic
    # For local testing, just log
    if change_type == 'CREATE':
        logger.info("Would trigger lead routing for: %s", record_ids)


def handle_task_change(payload: dict, first_touch_detector: FirstTouchDetector):
    """Handler for TaskChangeEvent."""
    header = payload.get('ChangeEventHeader', {})
    change_type = header.get('changeType')

    logger.info(
        "Task change detected",
        extra={
            'change_type': change_type,
            'entity': header.get('entityName')
        }
    )

    # Check if this is a first touch
    if change_type in ['CREATE', 'UPDATE']:
        who_id = payload.get('WhoId')
        completed_dt_str = payload.get('CompletedDateTime')
        owner_id = payload.get('OwnerId')

        if who_id and who_id.startswith('00Q') and completed_dt_str:
            # This is a completed task on a Lead
            logger.info("Checking for first touch: Lead=%s", who_id)

            completed_dt = datetime.fromisoformat(
                completed_dt_str.replace('Z', '+00:00')
            )

            result = first_touch_detector.detect_first_touch(
                lead_id=who_id,
                candidate_dt=completed_dt,
                user_id=owner_id,
                source='Task'
            )

            logger.info("First touch result: %s", result)


def handle_email_change(payload: dict, first_touch_detector: FirstTouchDetector):
    """Handler for EmailMessageChangeEvent."""
    header = payload.get('ChangeEventHeader', {})
    change_type = header.get('changeType')

    logger.info(
        "EmailMessage change detected",
        extra={
            'change_type': change_type,
            'entity': header.get('entityName')
        }
    )

    # Check if this is a first touch
    if change_type == 'CREATE':
        related_to_id = payload.get('RelatedToId')
        message_dt_str = payload.get('MessageDate')
        from_address = payload.get('FromAddress')

        if related_to_id and related_to_id.startswith('00Q') and message_dt_str:
            # This is an email related to a Lead
            logger.info("Checking for first touch: Lead=%s", related_to_id)

            message_dt = datetime.fromisoformat(
                message_dt_str.replace('Z', '+00:00')
            )

            result = first_touch_detector.detect_first_touch(
                lead_id=related_to_id,
                candidate_dt=message_dt,
                user_id=from_address,  # Use email as user identifier
                source='EmailMessage'
            )

            logger.info("First touch result: %s", result)


def main():
    """Run local CDC test."""
    logger.info("=" * 60)
    logger.info("CDC Subscriber Local Test")
    logger.info("=" * 60)

    # Load config
    try:
        config = load_config()
        logger.info("Configuration loaded")
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        logger.info("Make sure .env file exists with SF_* variables")
        sys.exit(1)

    # Initialize Salesforce client
    try:
        sf_auth = SalesforceJWT(config.salesforce)
        token = sf_auth.token()
        logger.info("Salesforce authentication successful")

        # Create SF client (simplified - in production use full client)
        from simple_salesforce import Salesforce
        sf = Salesforce(
            instance_url=config.salesforce.instance_url,
            session_id=token,
            version=config.salesforce.api_version
        )
        logger.info("Salesforce client initialized")

    except Exception as e:
        logger.error("Failed to authenticate with Salesforce: %s", e)
        sys.exit(1)

    # Initialize components
    replay_store = ReplayStore()
    subscriber = CDCSubscriber(
        sf_client=sf,
        replay_store=replay_store,
        use_pubsub=False,
        poll_interval=60
    )

    first_touch_detector = FirstTouchDetector(sf_client=sf)

    logger.info("Components initialized")

    # Register handlers
    subscriber.register_handler(
        '/data/LeadChangeEvent',
        lambda payload: handle_lead_change(payload)
    )

    subscriber.register_handler(
        '/data/TaskChangeEvent',
        lambda payload: handle_task_change(payload, first_touch_detector)
    )

    subscriber.register_handler(
        '/data/EmailMessageChangeEvent',
        lambda payload: handle_email_change(payload, first_touch_detector)
    )

    logger.info("Handlers registered")

    # Load and process fixtures
    logger.info("")
    logger.info("Processing sample CDC events...")
    logger.info("-" * 60)

    fixtures = [
        ('lead_create.json', '/data/LeadChangeEvent'),
        ('task_complete.json', '/data/TaskChangeEvent'),
        ('emailmessage.json', '/data/EmailMessageChangeEvent')
    ]

    for filename, channel in fixtures:
        try:
            logger.info("")
            logger.info("Processing: %s", filename)
            event = load_fixture(filename)

            # Process event
            subscriber._process_event(channel, event)

            # Small delay for readability
            time.sleep(0.5)

        except FileNotFoundError:
            logger.warning("Fixture not found: %s", filename)
        except Exception as e:
            logger.error("Error processing %s: %s", filename, e)

    # Show replay IDs
    logger.info("")
    logger.info("-" * 60)
    logger.info("Replay IDs persisted:")
    for channel in subscriber.channels:
        replay_id = replay_store.get(channel)
        logger.info("  %s: %s", channel, replay_id or 'None')

    # Show health status
    logger.info("")
    logger.info("-" * 60)
    logger.info("Health Status:")
    health = subscriber.get_health_status()
    logger.info(json.dumps(health, indent=2))

    # Show metrics (if prometheus_client is available)
    logger.info("")
    logger.info("-" * 60)
    logger.info("Metrics:")
    try:
        from prometheus_client import REGISTRY

        for metric in REGISTRY.collect():
            if metric.name.startswith('cdc_'):
                logger.info("  %s:", metric.name)
                for sample in metric.samples:
                    if sample.value > 0:
                        logger.info("    %s = %s", sample.labels, sample.value)
    except Exception as e:
        logger.warning("Could not collect metrics: %s", e)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Local test complete!")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. Check replay IDs were persisted to data/replay_ids.json")
    logger.info("  2. Run again to verify resumption from stored replay IDs")
    logger.info("  3. Check Salesforce Lead records for First_Response_At__c updates")
    logger.info("")


if __name__ == '__main__':
    main()
