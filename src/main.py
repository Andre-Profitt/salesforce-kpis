"""
Main entry point for Salesforce Flywheel Integration.

Starts CDC listener and wires workloads to handle events.
"""

import asyncio
import os
import signal
import sys
from dotenv import load_dotenv
import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

# Import components
from src.auth.jwt_auth import create_auth_from_env
from src.salesforce.api_client import SalesforceAPIClient
from src.flywheel.logger import create_logger_from_env
from src.listeners.cdc_listener import CDCListener, PollingListener
from src.workloads.lead_route import LeadRouter
from src.workloads.first_touch_detect import FirstTouchDetector
from src.workloads.template_suggest import TemplateSuggester


class FlywheelIntegration:
    """Main integration orchestrator."""

    def __init__(self, use_polling: bool = False):
        """
        Initialize Flywheel integration.

        Args:
            use_polling: Use polling instead of CDC (for orgs without CDC access)
        """
        # Load environment
        load_dotenv()

        # Initialize core components
        self.auth = create_auth_from_env()
        self.sf_client = SalesforceAPIClient(self.auth)
        self.flywheel_logger = create_logger_from_env()

        # Initialize workloads
        self.lead_router = LeadRouter(self.sf_client, self.flywheel_logger)
        self.first_touch_detector = FirstTouchDetector(self.sf_client, self.flywheel_logger)
        self.template_suggester = TemplateSuggester(self.sf_client, self.flywheel_logger)

        # Initialize listener
        self.use_polling = use_polling
        if use_polling:
            self.listener = PollingListener(
                sf_client=self.sf_client,
                poll_interval=int(os.getenv('POLL_INTERVAL', '60'))
            )
        else:
            access_token = self.auth.get_access_token()
            self.listener = CDCListener(
                instance_url=self.auth.instance_url,
                access_token=access_token,
                api_version=os.getenv('SF_API_VERSION', '59.0')
            )

        # Register event handlers
        self._register_handlers()

        logger.info(
            "flywheel_integration_initialized",
            mode="polling" if use_polling else "cdc"
        )

    def _register_handlers(self):
        """Register event handlers for CDC/polling."""
        if self.use_polling:
            self.listener.register_handler('Lead', self._handle_lead_change)
            self.listener.register_handler('Task', self._handle_task_change)
            self.listener.register_handler('EmailMessage', self._handle_email_change)
        else:
            self.listener.register_handler('/data/LeadChangeEvent', self._handle_lead_change)
            self.listener.register_handler('/data/TaskChangeEvent', self._handle_task_change)
            self.listener.register_handler('/data/EmailMessageChangeEvent', self._handle_email_change)

        logger.info("event_handlers_registered")

    async def _handle_lead_change(self, event: dict):
        """
        Handle Lead change event.

        Triggers:
        - Lead routing (for new leads)
        - Template suggestion (if description indicates inquiry)
        """
        try:
            # Extract lead ID based on event type
            if self.use_polling:
                lead_id = event.get('Id')
                change_type = event.get('__change_type', 'UPDATE')
            else:
                change_event_header = event.get('ChangeEventHeader', {})
                entity_name = change_event_header.get('entityName')
                change_type = change_event_header.get('changeType')
                record_ids = change_event_header.get('recordIds', [])
                lead_id = record_ids[0] if record_ids else None

            if not lead_id:
                logger.warning("lead_event_missing_id", event=event)
                return

            logger.info("processing_lead_event", lead_id=lead_id, change_type=change_type)

            # Route new leads
            if change_type == 'CREATE':
                logger.info("routing_new_lead", lead_id=lead_id)
                routing_result = self.lead_router.route_lead(lead_id)
                logger.info("lead_routed", lead_id=lead_id, result=routing_result)

                # Suggest template for new leads
                template_result = self.template_suggester.suggest_template(lead_id)
                logger.info("template_suggested", lead_id=lead_id, template=template_result.get('template_id'))

        except Exception as e:
            logger.error("lead_event_handler_error", error=str(e), event=event)

    async def _handle_task_change(self, event: dict):
        """
        Handle Task change event.

        Triggers:
        - First touch detection (for completed tasks related to leads)
        """
        try:
            # Extract task data
            if self.use_polling:
                task_id = event.get('Id')
                who_id = event.get('WhoId')
                status = event.get('Status')
            else:
                change_event_header = event.get('ChangeEventHeader', {})
                record_ids = change_event_header.get('recordIds', [])
                task_id = record_ids[0] if record_ids else None
                who_id = event.get('WhoId')
                status = event.get('Status')

            if not task_id or not who_id:
                return

            # Check if this is a lead-related task
            if who_id.startswith('00Q'):  # Lead ID prefix
                logger.info("processing_task_event", task_id=task_id, lead_id=who_id)

                # Detect first touch if task is completed
                if status == 'Completed':
                    result = self.first_touch_detector.detect_first_touch(who_id)
                    if result:
                        logger.info("first_touch_detected_from_task", lead_id=who_id, ttfr=result.get('ttfr_minutes'))

        except Exception as e:
            logger.error("task_event_handler_error", error=str(e), event=event)

    async def _handle_email_change(self, event: dict):
        """
        Handle EmailMessage change event (Enhanced Email).

        Triggers:
        - First touch detection (for emails related to leads)
        """
        try:
            # Extract email data
            if self.use_polling:
                email_id = event.get('Id')
                related_to_id = event.get('RelatedToId')
            else:
                change_event_header = event.get('ChangeEventHeader', {})
                record_ids = change_event_header.get('recordIds', [])
                email_id = record_ids[0] if record_ids else None
                related_to_id = event.get('RelatedToId')

            if not email_id or not related_to_id:
                return

            # Check if this is a lead-related email
            if related_to_id.startswith('00Q'):  # Lead ID prefix
                logger.info("processing_email_event", email_id=email_id, lead_id=related_to_id)

                # Detect first touch
                result = self.first_touch_detector.detect_first_touch(related_to_id)
                if result:
                    logger.info("first_touch_detected_from_email", lead_id=related_to_id, ttfr=result.get('ttfr_minutes'))

        except Exception as e:
            logger.error("email_event_handler_error", error=str(e), event=event)

    async def start(self):
        """Start the integration."""
        logger.info("starting_flywheel_integration")

        try:
            await self.listener.start()
        except KeyboardInterrupt:
            logger.info("shutdown_signal_received")
            await self.stop()
        except Exception as e:
            logger.error("integration_error", error=str(e))
            await self.stop()

    async def stop(self):
        """Stop the integration."""
        logger.info("stopping_flywheel_integration")

        if hasattr(self.listener, 'stop'):
            if asyncio.iscoroutinefunction(self.listener.stop):
                await self.listener.stop()
            else:
                self.listener.stop()

        logger.info("flywheel_integration_stopped")


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info("signal_received", signal=signum)
    sys.exit(0)


def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Check for polling mode
    use_polling = '--polling' in sys.argv or os.getenv('USE_POLLING', 'false').lower() == 'true'

    # Create and start integration
    integration = FlywheelIntegration(use_polling=use_polling)

    # Run event loop
    try:
        asyncio.run(integration.start())
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
    except Exception as e:
        logger.error("main_error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
