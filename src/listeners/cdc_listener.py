"""
Salesforce Change Data Capture (CDC) event listener.

Subscribes to LeadChangeEvent, TaskChangeEvent, and EmailMessageChangeEvent
to trigger agent workloads in real-time.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import structlog
from aiohttp import ClientSession
import time

logger = structlog.get_logger()


class CDCListener:
    """
    Listens to Salesforce CDC events via CometD protocol.

    Note: This is a simplified implementation. For production, consider using
    the Salesforce Pub/Sub API (gRPC) or a robust CometD client library.
    """

    def __init__(
        self,
        instance_url: str,
        access_token: str,
        api_version: str = "59.0"
    ):
        """
        Initialize CDC listener.

        Args:
            instance_url: Salesforce instance URL
            access_token: OAuth access token
            api_version: Salesforce API version
        """
        self.instance_url = instance_url.rstrip('/')
        self.access_token = access_token
        self.api_version = api_version
        self.cometd_url = f"{instance_url}/cometd/{api_version}"

        self.client_id: Optional[str] = None
        self.session: Optional[ClientSession] = None
        self.message_id = 0

        # Event handlers
        self.handlers: Dict[str, callable] = {}

    def register_handler(self, channel: str, handler: callable):
        """
        Register event handler for a CDC channel.

        Args:
            channel: CDC channel name (e.g., '/data/LeadChangeEvent')
            handler: Async function to handle events
        """
        self.handlers[channel] = handler
        logger.info("handler_registered", channel=channel)

    async def _get_next_message_id(self) -> int:
        """Get next message ID for CometD."""
        self.message_id += 1
        return self.message_id

    async def _handshake(self) -> bool:
        """
        Perform CometD handshake.

        Returns:
            True if successful
        """
        message = [{
            "channel": "/meta/handshake",
            "version": "1.0",
            "minimumVersion": "1.0",
            "supportedConnectionTypes": ["long-polling"],
            "id": str(await self._get_next_message_id())
        }]

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        try:
            async with self.session.post(
                self.cometd_url,
                json=message,
                headers=headers
            ) as response:
                result = await response.json()

                if result and result[0].get("successful"):
                    self.client_id = result[0].get("clientId")
                    logger.info("cdc_handshake_successful", client_id=self.client_id)
                    return True
                else:
                    logger.error("cdc_handshake_failed", result=result)
                    return False

        except Exception as e:
            logger.error("cdc_handshake_error", error=str(e))
            return False

    async def _subscribe(self, channel: str) -> bool:
        """
        Subscribe to a CDC channel.

        Args:
            channel: CDC channel (e.g., '/data/LeadChangeEvent')

        Returns:
            True if successful
        """
        message = [{
            "channel": "/meta/subscribe",
            "clientId": self.client_id,
            "subscription": channel,
            "id": str(await self._get_next_message_id())
        }]

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        try:
            async with self.session.post(
                self.cometd_url,
                json=message,
                headers=headers
            ) as response:
                result = await response.json()

                if result and result[0].get("successful"):
                    logger.info("cdc_subscription_successful", channel=channel)
                    return True
                else:
                    logger.error("cdc_subscription_failed", channel=channel, result=result)
                    return False

        except Exception as e:
            logger.error("cdc_subscription_error", channel=channel, error=str(e))
            return False

    async def _connect(self) -> Optional[list]:
        """
        Connect and receive messages (long-polling).

        Returns:
            List of received messages or None
        """
        message = [{
            "channel": "/meta/connect",
            "clientId": self.client_id,
            "connectionType": "long-polling",
            "id": str(await self._get_next_message_id())
        }]

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        try:
            # Long-polling with extended timeout
            async with self.session.post(
                self.cometd_url,
                json=message,
                headers=headers,
                timeout=120
            ) as response:
                result = await response.json()
                return result

        except asyncio.TimeoutError:
            # Timeout is expected in long-polling
            return []
        except Exception as e:
            logger.error("cdc_connect_error", error=str(e))
            return None

    async def _process_message(self, message: Dict[str, Any]):
        """
        Process a CDC event message.

        Args:
            message: CDC event message
        """
        channel = message.get("channel")

        if not channel or channel.startswith("/meta/"):
            return

        logger.info("cdc_event_received", channel=channel)

        # Extract event data
        data = message.get("data", {})
        payload = data.get("payload", {})

        # Get handler for this channel
        handler = self.handlers.get(channel)

        if handler:
            try:
                await handler(payload)
            except Exception as e:
                logger.error("handler_error", channel=channel, error=str(e))
        else:
            logger.warning("no_handler_for_channel", channel=channel)

    async def start(self):
        """Start listening to CDC events."""
        logger.info("starting_cdc_listener")

        self.session = ClientSession()

        # Handshake
        if not await self._handshake():
            logger.error("cdc_handshake_failed_cannot_start")
            return

        # Subscribe to registered channels
        for channel in self.handlers.keys():
            await self._subscribe(channel)

        # Listen loop
        logger.info("cdc_listener_active")

        while True:
            messages = await self._connect()

            if messages is None:
                logger.error("cdc_connection_lost_reconnecting")
                await asyncio.sleep(5)
                # Re-handshake
                await self._handshake()
                continue

            # Process messages
            for message in messages:
                await self._process_message(message)

    async def stop(self):
        """Stop listening."""
        if self.session:
            await self.session.close()
        logger.info("cdc_listener_stopped")


class PollingListener:
    """
    Alternative polling-based listener for environments without CDC access.

    Polls Salesforce REST API for new records at regular intervals.
    """

    def __init__(
        self,
        sf_client,
        poll_interval: int = 60
    ):
        """
        Initialize polling listener.

        Args:
            sf_client: SalesforceAPIClient instance
            poll_interval: Polling interval in seconds
        """
        self.sf_client = sf_client
        self.poll_interval = poll_interval
        self.handlers: Dict[str, callable] = {}
        self.last_poll_times: Dict[str, str] = {}
        self.running = False

    def register_handler(self, sobject_type: str, handler: callable):
        """
        Register handler for SObject changes.

        Args:
            sobject_type: SObject type (e.g., 'Lead', 'Task')
            handler: Function to handle new records
        """
        self.handlers[sobject_type] = handler
        logger.info("polling_handler_registered", sobject=sobject_type)

    async def _poll_object(self, sobject_type: str):
        """Poll for new records of a specific SObject type."""
        handler = self.handlers.get(sobject_type)
        if not handler:
            return

        # Get last poll time or default to last hour
        last_poll = self.last_poll_times.get(
            sobject_type,
            (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        )

        # Query for new/updated records
        soql = f"""
            SELECT FIELDS(STANDARD)
            FROM {sobject_type}
            WHERE SystemModstamp > {last_poll}
            ORDER BY SystemModstamp ASC
            LIMIT 100
        """

        try:
            records = self.sf_client.query(soql)

            if records:
                logger.info("polling_found_records", sobject=sobject_type, count=len(records))

                for record in records:
                    try:
                        await handler(record)
                    except Exception as e:
                        logger.error(
                            "polling_handler_error",
                            sobject=sobject_type,
                            record_id=record.get("Id"),
                            error=str(e)
                        )

                # Update last poll time
                self.last_poll_times[sobject_type] = records[-1]["SystemModstamp"]

        except Exception as e:
            logger.error("polling_query_error", sobject=sobject_type, error=str(e))

    async def start(self):
        """Start polling."""
        self.running = True
        logger.info("polling_listener_started", interval=self.poll_interval)

        while self.running:
            for sobject_type in self.handlers.keys():
                await self._poll_object(sobject_type)

            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stop polling."""
        self.running = False
        logger.info("polling_listener_stopped")
