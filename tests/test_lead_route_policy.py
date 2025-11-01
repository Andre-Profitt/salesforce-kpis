"""
Tests for routing policy system.

Verifies:
- Policy loads and validates correctly
- Segment/region mapping is deterministic
- Policy version is tracked
"""

import pytest
import json
import tempfile
from pathlib import Path
from app.policies.load import (
    load_routing_policy,
    RoutingPolicy,
    SegmentConfig
)


class TestRoutingPolicy:
    """Test suite for routing policy."""

    @pytest.fixture
    def sample_policy_dict(self):
        """Create sample policy dictionary."""
        return {
            "version": "v1.2.3",
            "segments": {
                "SMB": {
                    "employee_range": [1, 200],
                    "priority": "low",
                    "sla_hours": 48
                },
                "MM": {
                    "employee_range": [201, 2000],
                    "priority": "medium",
                    "sla_hours": 24
                },
                "ENT": {
                    "employee_range": [2001, None],
                    "priority": "high",
                    "sla_hours": 4
                }
            },
            "regions": {
                "NA": ["US", "CA", "MX"],
                "EMEA": ["GB", "DE", "FR"],
                "APAC": ["AU", "JP", "SG"]
            },
            "owners": {
                "SMB_NA": "005xx0000012001AAA",
                "MM_EMEA": "005xx0000012012AAA",
                "ENT_APAC": "005xx0000012023AAA"
            },
            "queues": {
                "default": "00Gxx0000000001AAA"
            }
        }

    @pytest.fixture
    def temp_policy_file(self, sample_policy_dict):
        """Create temporary policy file."""
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as f:
            json.dump(sample_policy_dict, f)
            temp_path = f.name

        yield temp_path

        # Cleanup
        Path(temp_path).unlink()

    def test_policy_validation(self, sample_policy_dict):
        """Test policy Pydantic validation."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.version == "v1.2.3"
        assert len(policy.segments) == 3
        assert len(policy.regions) == 3
        assert "SMB_NA" in policy.owners

    def test_policy_version_validation(self):
        """Test version must follow semver format."""
        with pytest.raises(ValueError):
            RoutingPolicy(
                version="invalid",  # Missing 'v' prefix
                segments={},
                regions={},
                owners={},
                queues={}
            )

    def test_pick_segment_smb(self, sample_policy_dict):
        """Test SMB segment selection."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_segment(50) == "SMB"
        assert policy.pick_segment(200) == "SMB"

    def test_pick_segment_mm(self, sample_policy_dict):
        """Test MM segment selection."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_segment(201) == "MM"
        assert policy.pick_segment(1000) == "MM"
        assert policy.pick_segment(2000) == "MM"

    def test_pick_segment_ent(self, sample_policy_dict):
        """Test ENT segment selection (unbounded upper)."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_segment(2001) == "ENT"
        assert policy.pick_segment(10000) == "ENT"
        assert policy.pick_segment(100000) == "ENT"

    def test_pick_segment_zero_fallback(self, sample_policy_dict):
        """Test zero employees falls back to SMB."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_segment(0) == "SMB"

    def test_pick_region_na(self, sample_policy_dict):
        """Test NA region selection."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_region("US") == "NA"
        assert policy.pick_region("CA") == "NA"
        assert policy.pick_region("MX") == "NA"

    def test_pick_region_emea(self, sample_policy_dict):
        """Test EMEA region selection."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_region("GB") == "EMEA"
        assert policy.pick_region("DE") == "EMEA"
        assert policy.pick_region("FR") == "EMEA"

    def test_pick_region_case_insensitive(self, sample_policy_dict):
        """Test region selection is case-insensitive."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_region("us") == "NA"
        assert policy.pick_region("gb") == "EMEA"

    def test_pick_region_unknown_fallback(self, sample_policy_dict):
        """Test unknown country falls back to NA."""
        policy = RoutingPolicy(**sample_policy_dict)

        assert policy.pick_region("ZZ") == "NA"

    def test_pick_owner_exact_match(self, sample_policy_dict):
        """Test owner selection with exact match."""
        policy = RoutingPolicy(**sample_policy_dict)

        owner = policy.pick_owner("SMB", "NA")
        assert owner == "005xx0000012001AAA"

    def test_pick_owner_missing_fallback(self, sample_policy_dict):
        """Test owner selection falls back to default queue."""
        policy = RoutingPolicy(**sample_policy_dict)

        # SMB_APAC not in owners dict
        owner = policy.pick_owner("SMB", "APAC")
        assert owner == "00Gxx0000000001AAA"  # Default queue

    def test_load_policy_from_file(self, temp_policy_file):
        """Test loading policy from file."""
        policy = load_routing_policy(temp_policy_file)

        assert policy.version == "v1.2.3"
        assert policy.pick_segment(500) == "MM"
        assert policy.pick_region("US") == "NA"

    def test_load_policy_file_not_found(self):
        """Test error when policy file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_routing_policy("/nonexistent/policy.json")

    def test_deterministic_routing(self, sample_policy_dict):
        """Test routing is deterministic for same inputs."""
        policy = RoutingPolicy(**sample_policy_dict)

        # Same inputs should always produce same outputs
        for _ in range(10):
            assert policy.pick_segment(500) == "MM"
            assert policy.pick_region("GB") == "EMEA"
            assert policy.pick_owner("MM", "EMEA") == "005xx0000012012AAA"

    def test_policy_version_stamping(self, sample_policy_dict):
        """Test policy version can be stamped in decisions."""
        policy = RoutingPolicy(**sample_policy_dict)

        decision = {
            "segment": policy.pick_segment(500),
            "region": policy.pick_region("US"),
            "policy_version": policy.version
        }

        assert decision["policy_version"] == "v1.2.3"
