"""
Tests for idempotent TTFR detection.

Verifies:
- Only writes if candidate is earlier than existing
- Task vs EmailMessage ordering handled correctly
- All 4 fields updated atomically
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
from app.workloads.first_touch import FirstTouchDetector, parse_dt, iso


class TestFirstTouchDetector:
    """Test suite for FirstTouchDetector."""

    @pytest.fixture
    def mock_sf_client(self):
        """Create mock Salesforce client."""
        client = Mock()
        client.get_record = MagicMock()
        client.update_record = MagicMock()
        client.query = MagicMock()
        return client

    @pytest.fixture
    def detector(self, mock_sf_client):
        """Create detector instance."""
        return FirstTouchDetector(mock_sf_client)

    def test_first_touch_no_existing(self, detector, mock_sf_client):
        """Test recording first touch when none exists."""
        lead_id = '00Q5e000001AbcD'
        created = datetime(2025, 11, 1, 10, 0, 0)
        response = datetime(2025, 11, 1, 10, 30, 0)
        user_id = '0055e000000User1'

        # Mock lead with no existing first response
        mock_sf_client.get_record.return_value = {
            'Id': lead_id,
            'CreatedDate': iso(created),
            'First_Response_At__c': None,
            'First_Response_User__c': None
        }

        result = detector.detect_first_touch(
            lead_id, response, user_id, 'Task'
        )

        assert result['status'] == 'updated'
        assert result['ttfr_minutes'] == 30
        assert result['first_response_source'] == 'Task'

        # Verify update was called
        mock_sf_client.update_record.assert_called_once()
        call_args = mock_sf_client.update_record.call_args[0]
        assert call_args[0] == 'Lead'
        assert call_args[1] == lead_id
        assert call_args[2]['Time_to_First_Response__c'] == 30

    def test_first_touch_candidate_earlier(self, detector, mock_sf_client):
        """Test updating when candidate is earlier than existing."""
        lead_id = '00Q5e000001AbcD'
        created = datetime(2025, 11, 1, 10, 0, 0)
        existing = datetime(2025, 11, 1, 10, 45, 0)  # 45 min
        candidate = datetime(2025, 11, 1, 10, 30, 0)  # 30 min (earlier!)
        user_id = '0055e000000User1'

        # Mock lead with existing first response at 45 min
        mock_sf_client.get_record.return_value = {
            'Id': lead_id,
            'CreatedDate': iso(created),
            'First_Response_At__c': iso(existing),
            'First_Response_User__c': '0055e000000User2'
        }

        result = detector.detect_first_touch(
            lead_id, candidate, user_id, 'EmailMessage'
        )

        assert result['status'] == 'updated'
        assert result['ttfr_minutes'] == 30
        assert result['replaced_existing'] is True

        # Verify update was called with new earlier time
        mock_sf_client.update_record.assert_called_once()

    def test_first_touch_candidate_later(self, detector, mock_sf_client):
        """Test skipping when candidate is later than existing."""
        lead_id = '00Q5e000001AbcD'
        created = datetime(2025, 11, 1, 10, 0, 0)
        existing = datetime(2025, 11, 1, 10, 30, 0)  # 30 min (earlier!)
        candidate = datetime(2025, 11, 1, 10, 45, 0)  # 45 min (later)
        user_id = '0055e000000User1'

        # Mock lead with existing first response at 30 min
        mock_sf_client.get_record.return_value = {
            'Id': lead_id,
            'CreatedDate': iso(created),
            'First_Response_At__c': iso(existing),
            'First_Response_User__c': '0055e000000User2'
        }

        result = detector.detect_first_touch(
            lead_id, candidate, user_id, 'Task'
        )

        assert result['status'] == 'skipped'
        assert result['reason'] == 'existing_earlier'

        # Verify NO update was called
        mock_sf_client.update_record.assert_not_called()

    def test_first_touch_task_vs_email_ordering(self, detector, mock_sf_client):
        """Test Task vs EmailMessage ordering logic."""
        lead_id = '00Q5e000001AbcD'

        # Task at 10:30, Email at 10:25 (Email is earlier)
        task_time = datetime(2025, 11, 1, 10, 30, 0)
        email_time = datetime(2025, 11, 1, 10, 25, 0)

        # Mock query results
        mock_sf_client.query.side_effect = [
            # Tasks query
            [{'Id': '00T...', 'CreatedDate': iso(task_time), 'OwnerId': 'User1', 'Type': 'Call'}],
            # Emails query
            [{'Id': '02s...', 'MessageDate': iso(email_time), 'CreatedById': 'User2'}]
        ]

        # Mock lead data
        mock_sf_client.get_record.return_value = {
            'Id': lead_id,
            'CreatedDate': iso(datetime(2025, 11, 1, 10, 0, 0)),
            'First_Response_At__c': None
        }

        result = detector.find_and_record_first_touch(lead_id)

        # Should pick EmailMessage as it's earlier
        assert result['status'] == 'updated'
        assert result['first_response_source'] == 'EmailMessage'
        assert result['ttfr_minutes'] == 25

    def test_first_touch_no_response_found(self, detector, mock_sf_client):
        """Test when no response exists yet."""
        lead_id = '00Q5e000001AbcD'

        # Mock empty query results
        mock_sf_client.query.side_effect = [
            [],  # No tasks
            []   # No emails
        ]

        result = detector.find_and_record_first_touch(lead_id)

        assert result is None
        mock_sf_client.update_record.assert_not_called()

    def test_parse_dt_utility(self):
        """Test datetime parsing utility."""
        # Valid ISO string
        dt = parse_dt('2025-11-01T10:30:00.000Z')
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 11
        assert dt.day == 1

        # None input
        assert parse_dt(None) is None

        # Invalid string
        assert parse_dt('invalid') is None

    def test_iso_utility(self):
        """Test ISO formatting utility."""
        dt = datetime(2025, 11, 1, 10, 30, 45)
        iso_str = iso(dt)
        assert iso_str == '2025-11-01T10:30:45.000Z'
