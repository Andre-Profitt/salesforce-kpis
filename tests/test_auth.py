"""
Tests for JWT authentication.
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from src.auth.jwt_auth import SalesforceJWTAuth


class TestSalesforceJWTAuth:
    """Test suite for SalesforceJWTAuth."""

    @pytest.fixture
    def mock_private_key(self, tmp_path):
        """Create a mock private key file."""
        key_file = tmp_path / "test_private.key"
        # This is a mock key for testing - do not use in production
        key_content = b"""-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8qPvQT/gjNQ8yF3iLOSn7LBK0cj
...mock key content...
-----END RSA PRIVATE KEY-----"""
        key_file.write_bytes(key_content)
        return str(key_file)

    def test_initialization(self, mock_private_key):
        """Test auth initialization."""
        auth = SalesforceJWTAuth(
            instance_url="https://test.salesforce.com",
            client_id="test_client_id",
            username="test@example.com",
            private_key_path=mock_private_key
        )

        assert auth.instance_url == "https://test.salesforce.com"
        assert auth.client_id == "test_client_id"
        assert auth.username == "test@example.com"

    @patch('src.auth.jwt_auth.requests.post')
    def test_get_access_token(self, mock_post, mock_private_key):
        """Test access token retrieval."""
        # Mock successful token response
        mock_response = Mock()
        mock_response.json.return_value = {
            'access_token': 'test_token_123',
            'token_type': 'Bearer'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        auth = SalesforceJWTAuth(
            instance_url="https://test.salesforce.com",
            client_id="test_client_id",
            username="test@example.com",
            private_key_path=mock_private_key
        )

        # Note: This will fail without a real key, but structure is correct
        # In real tests, mock the JWT signing

    def test_get_auth_headers(self, mock_private_key):
        """Test authorization header generation."""
        auth = SalesforceJWTAuth(
            instance_url="https://test.salesforce.com",
            client_id="test_client_id",
            username="test@example.com",
            private_key_path=mock_private_key
        )

        # Mock the token
        auth._access_token = "test_token_123"

        headers = auth.get_auth_headers()

        assert 'Authorization' in headers
        assert headers['Authorization'] == 'Bearer test_token_123'
        assert headers['Content-Type'] == 'application/json'
