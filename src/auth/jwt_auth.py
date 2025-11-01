"""
Salesforce OAuth 2.0 JWT Bearer authentication.

Implements server-to-server authentication using JWT tokens.
Ref: https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_jwt_flow.htm
"""

import os
import time
from datetime import datetime, timedelta
from typing import Optional
import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import structlog

logger = structlog.get_logger()


class SalesforceJWTAuth:
    """Handles JWT-based authentication for Salesforce."""

    def __init__(
        self,
        instance_url: str,
        client_id: str,
        username: str,
        private_key_path: str,
        token_expiry_seconds: int = 3600
    ):
        """
        Initialize JWT authentication.

        Args:
            instance_url: Salesforce instance URL (e.g., https://your-instance.salesforce.com)
            client_id: Connected App Consumer Key
            username: Salesforce username for the integration user
            private_key_path: Path to RSA private key file
            token_expiry_seconds: JWT token validity duration (default: 1 hour)
        """
        self.instance_url = instance_url.rstrip('/')
        self.client_id = client_id
        self.username = username
        self.private_key_path = private_key_path
        self.token_expiry_seconds = token_expiry_seconds

        # Token cache
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

        # Load private key
        self._private_key = self._load_private_key()

    def _load_private_key(self) -> bytes:
        """Load RSA private key from file."""
        try:
            with open(self.private_key_path, 'rb') as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            logger.info("private_key_loaded", path=self.private_key_path)
            return private_key
        except Exception as e:
            logger.error("failed_to_load_private_key", error=str(e), path=self.private_key_path)
            raise

    def _create_jwt_assertion(self) -> str:
        """
        Create JWT assertion for Salesforce OAuth.

        Returns:
            Signed JWT token string
        """
        current_time = int(time.time())

        payload = {
            'iss': self.client_id,
            'sub': self.username,
            'aud': self.instance_url,
            'exp': current_time + self.token_expiry_seconds
        }

        # Sign JWT with RS256
        token = jwt.encode(
            payload,
            self._private_key,
            algorithm='RS256'
        )

        return token

    def _request_access_token(self) -> dict:
        """
        Request access token from Salesforce using JWT Bearer flow.

        Returns:
            Token response dictionary
        """
        jwt_assertion = self._create_jwt_assertion()

        token_url = f"{self.instance_url}/services/oauth2/token"

        payload = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': jwt_assertion
        }

        logger.info("requesting_access_token", url=token_url, username=self.username)

        try:
            response = requests.post(
                token_url,
                data=payload,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30
            )
            response.raise_for_status()

            token_data = response.json()
            logger.info("access_token_obtained", expires_in=self.token_expiry_seconds)

            return token_data

        except requests.exceptions.RequestException as e:
            logger.error("token_request_failed", error=str(e))
            raise

    def get_access_token(self, force_refresh: bool = False) -> str:
        """
        Get valid access token, refreshing if necessary.

        Args:
            force_refresh: Force token refresh even if cached token is valid

        Returns:
            Valid access token
        """
        now = datetime.utcnow()

        # Check if we have a valid cached token
        if (
            not force_refresh
            and self._access_token
            and self._token_expires_at
            and now < self._token_expires_at
        ):
            logger.debug("using_cached_token", expires_at=self._token_expires_at.isoformat())
            return self._access_token

        # Request new token
        token_data = self._request_access_token()
        self._access_token = token_data['access_token']

        # Set expiry with 5-minute buffer
        self._token_expires_at = now + timedelta(seconds=self.token_expiry_seconds - 300)

        logger.info("token_refreshed", expires_at=self._token_expires_at.isoformat())

        return self._access_token

    def get_auth_headers(self) -> dict:
        """
        Get authorization headers for Salesforce API requests.

        Returns:
            Dictionary of headers including Bearer token
        """
        token = self.get_access_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }


def create_auth_from_env() -> SalesforceJWTAuth:
    """
    Create SalesforceJWTAuth instance from environment variables.

    Required environment variables:
        - SF_INSTANCE_URL
        - SF_CLIENT_ID
        - SF_USERNAME
        - SF_PRIVATE_KEY_PATH

    Returns:
        Configured SalesforceJWTAuth instance
    """
    instance_url = os.getenv('SF_INSTANCE_URL')
    client_id = os.getenv('SF_CLIENT_ID')
    username = os.getenv('SF_USERNAME')
    private_key_path = os.getenv('SF_PRIVATE_KEY_PATH')

    if not all([instance_url, client_id, username, private_key_path]):
        raise ValueError(
            "Missing required environment variables: "
            "SF_INSTANCE_URL, SF_CLIENT_ID, SF_USERNAME, SF_PRIVATE_KEY_PATH"
        )

    return SalesforceJWTAuth(
        instance_url=instance_url,
        client_id=client_id,
        username=username,
        private_key_path=private_key_path
    )
