"""
Replay ID persistence for CDC event resumption.

Stores last processed replay ID per channel to enable crash recovery.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional, Dict


logger = logging.getLogger(__name__)


class ReplayStore:
    """Thread-safe replay ID storage."""

    def __init__(self, path: str = '.replay.json'):
        """
        Initialize replay store.

        Args:
            path: Path to replay state file
        """
        self.path = Path(path)
        self._lock = threading.Lock()

        # Initialize file if it doesn't exist
        if not self.path.exists():
            self._write({})
            logger.info("Replay store initialized", extra={'path': str(self.path)})
        else:
            logger.info("Replay store loaded", extra={'path': str(self.path)})

    def get(self, channel: str) -> Optional[str]:
        """
        Get last replay ID for a channel.

        Args:
            channel: CDC channel name (e.g., '/data/LeadChangeEvent')

        Returns:
            Replay ID or None if not found
        """
        data = self._read()
        replay_id = data.get(channel)

        logger.debug(
            "Replay ID retrieved",
            extra={'channel': channel, 'replay_id': replay_id}
        )

        return replay_id

    def set(self, channel: str, replay_id: str):
        """
        Store replay ID for a channel.

        Args:
            channel: CDC channel name
            replay_id: Replay ID to store
        """
        with self._lock:
            data = self._read()
            data[channel] = replay_id
            self._write(data)

        logger.debug(
            "Replay ID stored",
            extra={'channel': channel, 'replay_id': replay_id}
        )

    def get_all(self) -> Dict[str, str]:
        """
        Get all stored replay IDs.

        Returns:
            Dictionary of channel -> replay_id
        """
        return self._read()

    def clear(self, channel: Optional[str] = None):
        """
        Clear replay state.

        Args:
            channel: Specific channel to clear (or all if None)
        """
        with self._lock:
            if channel:
                data = self._read()
                if channel in data:
                    del data[channel]
                    self._write(data)
                    logger.info("Replay ID cleared", extra={'channel': channel})
            else:
                self._write({})
                logger.info("All replay IDs cleared")

    def _read(self) -> Dict[str, str]:
        """Read replay state from disk."""
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning("Failed to read replay store, returning empty state")
            return {}

    def _write(self, data: Dict[str, str]):
        """Write replay state to disk."""
        try:
            self.path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error("Failed to write replay store", extra={'error': str(e)})
            raise
