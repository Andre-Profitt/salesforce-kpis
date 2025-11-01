"""
CDC Subscriber with Pub/Sub and replay resumption.

Supports both Pub/Sub API (gRPC) and polling fallback for organizations
without CDC access.
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Callable
from prometheus_client import Counter, Gauge

from app.cdc.replay_store import ReplayStore

logger = logging.getLogger(__name__)

# Metrics
cdc_events_total = Counter(
    'cdc_events_total',
    'Total CDC events processed',
    ['object', 'change_type']
)

cdc_lag_seconds = Gauge(
    'cdc_lag_seconds',
    'Seconds behind latest CDC event',
    ['object']
)

cdc_errors_total = Counter(
    'cdc_errors_total',
    'Total CDC processing errors',
    ['object', 'error_type']
)


class CDCSubscriber:
    """
    CDC event subscriber with replay persistence.

    Handles both Pub/Sub (gRPC) and polling fallback modes.
    """

    def __init__(
        self,
        sf_client,
        replay_store: Optional[ReplayStore] = None,
        use_pubsub: bool = True,
        poll_interval: int = 60
    ):
        """
        Initialize CDC subscriber.

        Args:
            sf_client: Salesforce API client
            replay_store: Replay ID persistence (created if None)
            use_pubsub: Use Pub/Sub API (vs polling)
            poll_interval: Polling interval in seconds (if not using Pub/Sub)
        """
        self.sf = sf_client
        self.replay_store = replay_store or ReplayStore()
        self.use_pubsub = use_pubsub
        self.poll_interval = poll_interval

        # Event handlers
        self.handlers: Dict[str, Callable] = {}

        # Channel definitions
        self.channels = [
            '/data/LeadChangeEvent',
            '/data/TaskChangeEvent',
            '/data/EmailMessageChangeEvent'
        ]

        # Last event timestamps for lag calculation
        self.last_event_ts: Dict[str, float] = {}

        logger.info(
            "CDC subscriber initialized",
            extra={
                'mode': 'pubsub' if use_pubsub else 'polling',
                'channels': len(self.channels),
                'poll_interval': poll_interval
            }
        )

    def register_handler(self, channel: str, handler: Callable):
        """
        Register event handler for a channel.

        Args:
            channel: CDC channel name (e.g., '/data/LeadChangeEvent')
            handler: Async handler function(event_payload: dict) -> None
        """
        self.handlers[channel] = handler
        logger.info("Handler registered", extra={'channel': channel})

    def _extract_object_name(self, channel: str) -> str:
        """Extract object name from channel."""
        if 'Lead' in channel:
            return 'Lead'
        elif 'Task' in channel:
            return 'Task'
        elif 'EmailMessage' in channel:
            return 'EmailMessage'
        return 'Unknown'

    def _process_event(self, channel: str, event: Dict[str, Any]):
        """
        Process a single CDC event.

        Args:
            channel: CDC channel
            event: Event payload
        """
        object_name = self._extract_object_name(channel)

        try:
            # Extract change event header
            payload = event.get('data', {}).get('payload', {})
            header = payload.get('ChangeEventHeader', {})
            change_type = header.get('changeType', 'UNKNOWN')

            # Update metrics
            cdc_events_total.labels(
                object=object_name,
                change_type=change_type
            ).inc()

            # Calculate lag
            commit_timestamp = header.get('commitTimestamp')
            if commit_timestamp:
                now_ms = int(time.time() * 1000)
                lag_ms = now_ms - commit_timestamp
                lag_seconds = lag_ms / 1000.0
                cdc_lag_seconds.labels(object=object_name).set(lag_seconds)
                self.last_event_ts[object_name] = time.time()

            # Extract and persist replay ID
            replay_id = event.get('data', {}).get('event', {}).get('replayId')
            if replay_id:
                self.replay_store.set(channel, str(replay_id))

            # Call handler
            handler = self.handlers.get(channel)
            if handler:
                logger.debug(
                    "Dispatching event to handler",
                    extra={
                        'channel': channel,
                        'change_type': change_type,
                        'replay_id': replay_id
                    }
                )
                handler(payload)
            else:
                logger.warning(
                    "No handler for channel",
                    extra={'channel': channel}
                )

        except Exception as e:
            logger.error(
                "Error processing CDC event",
                extra={
                    'channel': channel,
                    'error': str(e),
                    'event': event
                }
            )
            cdc_errors_total.labels(
                object=object_name,
                error_type=type(e).__name__
            ).inc()

    def start_polling(self):
        """
        Start polling mode (fallback when Pub/Sub unavailable).

        Polls Salesforce REST API at regular intervals.
        """
        logger.info("Starting polling mode", extra={'interval': self.poll_interval})

        # Track last poll times per object
        last_poll_times: Dict[str, str] = {}

        while True:
            for channel in self.channels:
                object_name = self._extract_object_name(channel)

                try:
                    # Get last poll time or default to 1 hour ago
                    last_poll = last_poll_times.get(
                        object_name,
                        datetime.utcnow().isoformat() + 'Z'
                    )

                    # Query for new/updated records
                    soql = self._build_poll_query(object_name, last_poll)
                    records = self.sf.query(soql)

                    if records:
                        logger.info(
                            "Poll found records",
                            extra={
                                'object': object_name,
                                'count': len(records)
                            }
                        )

                        for record in records:
                            # Convert to CDC-like event format
                            event = self._convert_to_cdc_event(
                                channel,
                                object_name,
                                record
                            )
                            self._process_event(channel, event)

                        # Update last poll time
                        last_poll_times[object_name] = records[-1]['SystemModstamp']

                except Exception as e:
                    logger.error(
                        "Polling error",
                        extra={'object': object_name, 'error': str(e)}
                    )
                    cdc_errors_total.labels(
                        object=object_name,
                        error_type='polling_error'
                    ).inc()

            # Sleep before next poll
            time.sleep(self.poll_interval)

    def _build_poll_query(self, object_name: str, last_poll: str) -> str:
        """Build SOQL for polling."""
        # Basic query - customize field list as needed
        return f"""
            SELECT Id, SystemModstamp, CreatedDate, LastModifiedDate
            FROM {object_name}
            WHERE SystemModstamp > {last_poll}
            ORDER BY SystemModstamp ASC
            LIMIT 100
        """

    def _convert_to_cdc_event(
        self,
        channel: str,
        object_name: str,
        record: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Convert poll result to CDC event format.

        Args:
            channel: CDC channel
            object_name: SObject name
            record: Salesforce record

        Returns:
            CDC-like event structure
        """
        return {
            'channel': channel,
            'data': {
                'payload': {
                    'ChangeEventHeader': {
                        'entityName': object_name,
                        'recordIds': [record['Id']],
                        'changeType': 'UPDATE',  # Polling can't distinguish CREATE vs UPDATE
                        'commitTimestamp': int(time.time() * 1000)
                    },
                    **record
                },
                'event': {
                    'replayId': record.get('SystemModstamp', '')
                }
            }
        }

    def start_pubsub(self):
        """
        Start Pub/Sub mode (gRPC).

        NOTE: This is a placeholder. Full Pub/Sub implementation requires
        the Salesforce Pub/Sub API client library (currently in beta).

        For now, this logs a warning and falls back to polling.
        """
        logger.warning(
            "Pub/Sub mode not yet implemented, falling back to polling. "
            "To implement: install salesforce-pubsub-api-client and integrate gRPC stream."
        )

        # Get replay IDs for each channel
        for channel in self.channels:
            replay_id = self.replay_store.get(channel)
            logger.info(
                "Would subscribe to channel",
                extra={'channel': channel, 'replay_id': replay_id or 'latest'}
            )

        # Fallback to polling
        self.start_polling()

    def start(self):
        """Start subscriber (Pub/Sub or polling based on config)."""
        if self.use_pubsub:
            self.start_pubsub()
        else:
            self.start_polling()

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get subscriber health status.

        Returns:
            Health status dictionary
        """
        now = time.time()
        health = {
            'mode': 'pubsub' if self.use_pubsub else 'polling',
            'channels': len(self.channels),
            'handlers_registered': len(self.handlers),
            'replay_ids': self.replay_store.get_all(),
            'last_event_times': {}
        }

        # Calculate time since last event per object
        for obj, last_ts in self.last_event_ts.items():
            health['last_event_times'][obj] = {
                'timestamp': last_ts,
                'seconds_ago': int(now - last_ts)
            }

        return health
