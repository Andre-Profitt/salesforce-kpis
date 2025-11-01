"""
JWT Bearer authentication for Salesforce with token caching.

Production-grade implementation with proper error handling and metrics.
"""

import time
import logging
from pathlib import Path
from typing import Dict, Optional

import jwt
import requests
from prometheus_client import Counter, Histogram


logger = logging.getLogger(__name__)

# Metrics
auth_requests = Counter('sf_auth_requests_total', 'Total auth requests', ['status'])
auth_latency = Histogram('sf_auth_latency_seconds', 'Auth request latency')


class SalesforceJWT:
    """JWT Bearer authentication handler with token caching."""

    def __init__(
        self,
        instance_url: str,
        client_id: str,
        username: str,
        private_key_path: str,
        aud: Optional[str] = None
    ):
        """
        Initialize JWT auth.

        Args:
            instance_url: Salesforce instance URL
            client_id: Connected App consumer key
            username: Integration user username
            private_key_path: Path to RSA private key
            aud: JWT audience (defaults to login.salesforce.com)
        """
        self.instance_url = instance_url.rstrip('/')
        self.client_id = client_id
        self.username = username
        self.aud = aud or (
            'https://login.salesforce.com'
            if 'salesforce.com' in instance_url
            else instance_url
        )

        # Load private key
        key_path = Path(private_key_path)
        if not key_path.exists():
            raise FileNotFoundError(f"Private key not found: {private_key_path}")
        self.private_key = key_path.read_text()

        # Token cache
        self._cache: Dict[str, any] = {'token': None, 'exp': 0}

        logger.info(
            "JWT auth initialized",
            extra={
                'instance_url': self.instance_url,
                'username': self.username,
                'aud': self.aud
            }
        )

    def token(self) -> str:
        """
        Get valid access token (uses cache if available).

        Returns:
            Valid access token
        """
        # Check cache (with 60s buffer)
        if self._cache['token'] and self._cache['exp'] - 60 > int(time.time()):
            logger.debug("Using cached token")
            return self._cache['token']

        # Request new token
        return self._refresh_token()

    @auth_latency.time()
    def _refresh_token(self) -> str:
        """Request new access token from Salesforce."""
        iat = int(time.time())
        exp = iat + 300  # 5 minutes

        # Build JWT payload
        payload = {
            'iss': self.client_id,
            'sub': self.username,
            'aud': self.aud,
            'exp': exp
        }

        # Sign JWT
        try:
            assertion = jwt.encode(payload, self.private_key, algorithm='RS256')
        except Exception as e:
            logger.error("JWT signing failed", extra={'error': str(e)})
            auth_requests.labels(status='sign_error').inc()
            raise

        # Request token
        token_url = f"{self.instance_url}/services/oauth2/token"
        data = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': assertion
        }

        try:
            response = requests.post(token_url, data=data, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error("Token request failed", extra={'error': str(e)})
            auth_requests.labels(status='request_error').inc()
            raise

        # Extract token
        token_data = response.json()
        token = token_data['access_token']

        # Update cache
        self._cache = {'token': token, 'exp': exp}

        logger.info("Token refreshed", extra={'expires_at': exp})
        auth_requests.labels(status='success').inc()

        return token

    def headers(self) -> Dict[str, str]:
        """
        Get authorization headers for API requests.

        Returns:
            Dictionary with Authorization header
        """
        return {
            'Authorization': f'Bearer {self.token()}',
            'Content-Type': 'application/json'
        }

    def invalidate_cache(self):
        """Force token refresh on next request."""
        self._cache = {'token': None, 'exp': 0}
        logger.info("Token cache invalidated")
