"""
Tests for FastAPI web endpoints.

Verifies:
- /metrics returns Prometheus format
- /healthz returns health status
- /ready returns readiness status
- /version returns version info
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime

from app.web.server import app, set_health_check, mark_ready, mark_not_ready


class TestWebEndpoints:
    """Test suite for web endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert data['service'] == 'Salesforce KPIs'
        assert 'version' in data
        assert 'endpoints' in data
        assert 'metrics' in data['endpoints']
        assert 'timestamp' in data

    def test_metrics_endpoint(self, client):
        """Test /metrics returns Prometheus format."""
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/plain')

        content = response.text

        # Should contain metric definitions
        assert '# HELP' in content
        assert '# TYPE' in content

        # Should contain system_info metric
        assert 'system_info' in content

    def test_metrics_contains_expected_metrics(self, client):
        """Test /metrics includes all expected metric families."""
        response = client.get("/metrics")
        content = response.text

        expected_metrics = [
            'system_info',
            'decisions_total',
            'assignment_latency_seconds',
            'errors_total',
            'active_workers',
            'api_requests_total'
        ]

        for metric in expected_metrics:
            assert metric in content, f"Expected metric {metric} not found"

    def test_healthz_endpoint(self, client):
        """Test /healthz returns health status."""
        response = client.get("/healthz")

        assert response.status_code == 200
        data = response.json()

        assert data['status'] == 'healthy'
        assert 'timestamp' in data
        assert 'uptime_seconds' in data
        assert 'version' in data
        assert isinstance(data['uptime_seconds'], int)

    def test_healthz_uptime_increases(self, client):
        """Test uptime increases over time."""
        import time

        response1 = client.get("/healthz")
        uptime1 = response1.json()['uptime_seconds']

        time.sleep(1)

        response2 = client.get("/healthz")
        uptime2 = response2.json()['uptime_seconds']

        assert uptime2 >= uptime1

    def test_readyz_endpoint_ready(self, client):
        """Test /ready returns 200 when all checks pass."""
        # Set all checks to healthy
        set_health_check('test_component', True)

        response = client.get("/ready")

        assert response.status_code == 200
        data = response.json()

        assert 'ready' in data
        assert 'checks' in data
        assert 'timestamp' in data
        assert 'version' in data

    def test_readyz_endpoint_not_ready(self, client):
        """Test /ready returns 503 when checks fail."""
        # Set a check to unhealthy
        set_health_check('failing_component', False)

        response = client.get("/ready")

        assert response.status_code == 503
        data = response.json()

        assert data['ready'] is False
        assert 'failing_component' in data['checks']
        assert data['checks']['failing_component'] is False

    def test_readyz_individual_checks(self, client):
        """Test /ready reports individual component status."""
        set_health_check('cdc_subscriber', True)
        set_health_check('salesforce', True)

        response = client.get("/ready")
        data = response.json()

        assert 'cdc_subscriber' in data['checks']
        assert 'salesforce' in data['checks']
        assert data['checks']['cdc_subscriber'] is True
        assert data['checks']['salesforce'] is True

    def test_version_endpoint(self, client):
        """Test /version returns version info."""
        response = client.get("/version")

        assert response.status_code == 200
        data = response.json()

        assert 'version' in data
        assert 'environment' in data
        assert 'started_at' in data

        # Verify timestamp format
        started_at = data['started_at']
        assert started_at.endswith('Z')  # ISO format with UTC

    def test_health_check_update(self, client):
        """Test health checks can be updated."""
        component = 'test_component_dynamic'

        # Initially not present
        response1 = client.get("/ready")
        data1 = response1.json()
        assert component not in data1['checks']

        # Add health check
        set_health_check(component, True)

        response2 = client.get("/ready")
        data2 = response2.json()
        assert component in data2['checks']
        assert data2['checks'][component] is True

        # Update to unhealthy
        set_health_check(component, False)

        response3 = client.get("/ready")
        data3 = response3.json()
        assert data3['checks'][component] is False

    def test_metrics_content_type(self, client):
        """Test /metrics returns correct content type."""
        response = client.get("/metrics")

        # Prometheus expects text/plain with version
        content_type = response.headers['content-type']
        assert 'text/plain' in content_type

    def test_healthz_always_returns_200(self, client):
        """Test /healthz always returns 200 (liveness probe)."""
        # Even if readiness checks fail, health should pass
        set_health_check('failing_component', False)

        health_response = client.get("/healthz")
        ready_response = client.get("/ready")

        assert health_response.status_code == 200  # Always healthy
        assert ready_response.status_code == 503   # Not ready

    def test_timestamp_format(self, client):
        """Test all endpoints return ISO timestamps."""
        endpoints = ["/", "/healthz", "/ready", "/version"]

        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()

            # All endpoints should have timestamp
            assert 'timestamp' in data or 'started_at' in data

            # Verify ISO format
            timestamp = data.get('timestamp') or data.get('started_at')
            assert timestamp.endswith('Z')

            # Should be parseable
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

    def test_cors_headers_not_present(self, client):
        """Test CORS headers are not present by default."""
        response = client.get("/")

        # Should not have CORS headers unless explicitly configured
        assert 'access-control-allow-origin' not in response.headers

    def test_metrics_incrementable(self, client):
        """Test metrics can be incremented."""
        from app.web.metrics import decisions_total

        # Get initial count
        response1 = client.get("/metrics")
        content1 = response1.text

        # Increment metric
        decisions_total.labels(workload='test', outcome='success').inc()

        # Get updated count
        response2 = client.get("/metrics")
        content2 = response2.text

        # Content should have changed
        assert content1 != content2
        assert 'decisions_total' in content2
