"""
Tests for CDC subscriber replay persistence.

Verifies:
- Replay IDs are persisted after event processing
- Subscriber can resume from stored replay ID
- Event handlers are invoked correctly
- Metrics are updated
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from app.cdc.subscriber import CDCSubscriber
from app.cdc.replay_store import ReplayStore


class TestCDCReplay:
    """Test suite for CDC replay persistence."""

    @pytest.fixture
    def temp_replay_file(self):
        """Create temporary replay store file."""
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as f:
            json.dump({}, f)
            temp_path = f.name

        yield temp_path

        # Cleanup
        Path(temp_path).unlink(missing_ok=True)

    @pytest.fixture
    def mock_sf_client(self):
        """Mock Salesforce client."""
        client = Mock()
        client.query = Mock(return_value=[])
        client.get_record = Mock(return_value={
            'Id': '00Qxx0000012345',
            'CreatedDate': '2025-01-15T10:00:00.000Z',
            'First_Response_At__c': None
        })
        client.update_record = Mock()
        return client

    @pytest.fixture
    def replay_store(self, temp_replay_file):
        """Create replay store with temp file."""
        return ReplayStore(store_path=temp_replay_file)

    @pytest.fixture
    def subscriber(self, mock_sf_client, replay_store):
        """Create CDC subscriber."""
        return CDCSubscriber(
            sf_client=mock_sf_client,
            replay_store=replay_store,
            use_pubsub=False,
            poll_interval=60
        )

    @pytest.fixture
    def sample_lead_event(self):
        """Load sample Lead CDC event."""
        fixture_path = Path(__file__).parent.parent / 'app' / 'cdc' / 'fixtures' / 'lead_create.json'
        with open(fixture_path) as f:
            return json.load(f)

    @pytest.fixture
    def sample_task_event(self):
        """Load sample Task CDC event."""
        fixture_path = Path(__file__).parent.parent / 'app' / 'cdc' / 'fixtures' / 'task_complete.json'
        with open(fixture_path) as f:
            return json.load(f)

    def test_replay_id_persisted_after_event(
        self,
        subscriber,
        replay_store,
        sample_lead_event
    ):
        """Test replay ID is persisted after processing event."""
        channel = '/data/LeadChangeEvent'

        # Process event
        subscriber._process_event(channel, sample_lead_event)

        # Verify replay ID was stored
        stored_replay = replay_store.get(channel)
        assert stored_replay is not None
        assert stored_replay == str(sample_lead_event['data']['event']['replayId'])

    def test_replay_id_updated_on_subsequent_events(
        self,
        subscriber,
        replay_store,
        sample_lead_event
    ):
        """Test replay ID updates with each new event."""
        channel = '/data/LeadChangeEvent'

        # Process first event
        subscriber._process_event(channel, sample_lead_event)
        first_replay = replay_store.get(channel)

        # Modify replay ID and process again
        sample_lead_event['data']['event']['replayId'] = 9999999
        subscriber._process_event(channel, sample_lead_event)
        second_replay = replay_store.get(channel)

        # Verify replay ID was updated
        assert second_replay != first_replay
        assert second_replay == "9999999"

    def test_handler_invoked_on_event(self, subscriber, sample_lead_event):
        """Test registered handler is called when event arrives."""
        channel = '/data/LeadChangeEvent'

        # Register mock handler
        mock_handler = Mock()
        subscriber.register_handler(channel, mock_handler)

        # Process event
        subscriber._process_event(channel, sample_lead_event)

        # Verify handler was called with payload
        mock_handler.assert_called_once()
        call_args = mock_handler.call_args[0][0]
        assert 'ChangeEventHeader' in call_args
        assert call_args['ChangeEventHeader']['entityName'] == 'Lead'

    def test_handler_not_invoked_for_unregistered_channel(
        self,
        subscriber,
        sample_lead_event
    ):
        """Test no error when event arrives for channel without handler."""
        channel = '/data/LeadChangeEvent'

        # Don't register handler
        # Process event (should not raise)
        subscriber._process_event(channel, sample_lead_event)

        # Should complete without error

    def test_multiple_channels_separate_replay_ids(
        self,
        subscriber,
        replay_store,
        sample_lead_event,
        sample_task_event
    ):
        """Test each channel has independent replay ID."""
        lead_channel = '/data/LeadChangeEvent'
        task_channel = '/data/TaskChangeEvent'

        # Process events on different channels
        subscriber._process_event(lead_channel, sample_lead_event)
        subscriber._process_event(task_channel, sample_task_event)

        # Verify separate replay IDs
        lead_replay = replay_store.get(lead_channel)
        task_replay = replay_store.get(task_channel)

        assert lead_replay != task_replay
        assert lead_replay == str(sample_lead_event['data']['event']['replayId'])
        assert task_replay == str(sample_task_event['data']['event']['replayId'])

    def test_extract_object_name(self, subscriber):
        """Test object name extraction from channel."""
        assert subscriber._extract_object_name('/data/LeadChangeEvent') == 'Lead'
        assert subscriber._extract_object_name('/data/TaskChangeEvent') == 'Task'
        assert subscriber._extract_object_name('/data/EmailMessageChangeEvent') == 'EmailMessage'
        assert subscriber._extract_object_name('/data/UnknownEvent') == 'Unknown'

    def test_metrics_incremented_on_event(self, subscriber, sample_lead_event):
        """Test Prometheus metrics are incremented."""
        from app.cdc.subscriber import cdc_events_total

        channel = '/data/LeadChangeEvent'

        # Get initial count
        initial_count = cdc_events_total.labels(
            object='Lead',
            change_type='CREATE'
        )._value._value

        # Process event
        subscriber._process_event(channel, sample_lead_event)

        # Verify count incremented
        final_count = cdc_events_total.labels(
            object='Lead',
            change_type='CREATE'
        )._value._value

        assert final_count > initial_count

    def test_convert_to_cdc_event(self, subscriber):
        """Test poll result converts to CDC event format."""
        record = {
            'Id': '00Qxx0000012345',
            'SystemModstamp': '2025-01-15T10:30:00.000Z',
            'CreatedDate': '2025-01-15T10:00:00.000Z',
            'Company': 'Acme Corp'
        }

        event = subscriber._convert_to_cdc_event(
            '/data/LeadChangeEvent',
            'Lead',
            record
        )

        # Verify structure
        assert event['channel'] == '/data/LeadChangeEvent'
        assert 'data' in event
        assert 'payload' in event['data']
        assert 'ChangeEventHeader' in event['data']['payload']

        header = event['data']['payload']['ChangeEventHeader']
        assert header['entityName'] == 'Lead'
        assert header['recordIds'] == ['00Qxx0000012345']
        assert header['changeType'] == 'UPDATE'

        # Verify record fields are included
        payload = event['data']['payload']
        assert payload['Id'] == '00Qxx0000012345'
        assert payload['Company'] == 'Acme Corp'

    def test_build_poll_query(self, subscriber):
        """Test SOQL query construction for polling."""
        query = subscriber._build_poll_query('Lead', '2025-01-15T10:00:00.000Z')

        # Verify query structure
        assert 'SELECT' in query
        assert 'FROM Lead' in query
        assert 'WHERE SystemModstamp >' in query
        assert '2025-01-15T10:00:00.000Z' in query
        assert 'ORDER BY SystemModstamp ASC' in query
        assert 'LIMIT 100' in query

    def test_health_status(self, subscriber, sample_lead_event):
        """Test health status reporting."""
        channel = '/data/LeadChangeEvent'

        # Process event
        subscriber._process_event(channel, sample_lead_event)

        # Get health status
        health = subscriber.get_health_status()

        # Verify structure
        assert health['mode'] == 'polling'
        assert health['channels'] == 3  # LeadChangeEvent, TaskChangeEvent, EmailMessageChangeEvent
        assert health['handlers_registered'] >= 0
        assert 'replay_ids' in health
        assert 'last_event_times' in health

        # Verify replay ID is in health status
        assert channel in health['replay_ids']

    def test_error_handling_invalid_event(self, subscriber):
        """Test error handling for malformed event."""
        channel = '/data/LeadChangeEvent'

        # Create invalid event (missing required fields)
        invalid_event = {'invalid': 'structure'}

        # Should not raise exception
        subscriber._process_event(channel, invalid_event)

        # Error should be logged and metrics incremented
        from app.cdc.subscriber import cdc_errors_total
        errors = cdc_errors_total.labels(
            object='Lead',
            error_type='KeyError'
        )._value._value

        assert errors > 0

    def test_subscriber_initialization(self, mock_sf_client, replay_store):
        """Test subscriber initializes with correct configuration."""
        subscriber = CDCSubscriber(
            sf_client=mock_sf_client,
            replay_store=replay_store,
            use_pubsub=True,
            poll_interval=30
        )

        assert subscriber.use_pubsub is True
        assert subscriber.poll_interval == 30
        assert len(subscriber.channels) == 3
        assert '/data/LeadChangeEvent' in subscriber.channels
        assert '/data/TaskChangeEvent' in subscriber.channels
        assert '/data/EmailMessageChangeEvent' in subscriber.channels

    def test_lag_calculation(self, subscriber, sample_lead_event):
        """Test CDC lag is calculated and recorded."""
        from app.cdc.subscriber import cdc_lag_seconds

        channel = '/data/LeadChangeEvent'

        # Process event
        subscriber._process_event(channel, sample_lead_event)

        # Verify lag was calculated (should be non-zero since event is from past)
        lag = cdc_lag_seconds.labels(object='Lead')._value._value
        assert lag > 0  # Event from fixture is in the past

    def test_handler_registration(self, subscriber):
        """Test handler registration."""
        channel = '/data/LeadChangeEvent'
        handler = Mock()

        # Register handler
        subscriber.register_handler(channel, handler)

        # Verify handler is stored
        assert channel in subscriber.handlers
        assert subscriber.handlers[channel] == handler
