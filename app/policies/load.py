"""
Policy loader with validation and versioning.

Validates routing policy against JSON schema and provides deterministic
routing decisions.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from pydantic import BaseModel, Field, validator
import jsonschema


logger = logging.getLogger(__name__)


class SegmentConfig(BaseModel):
    """Segment configuration."""
    employee_range: Tuple[int, Optional[int]]
    priority: str
    sla_hours: Optional[int] = None


class RoutingPolicy(BaseModel):
    """Validated routing policy."""
    version: str = Field(..., regex=r'^v\d+\.\d+\.\d+$')
    segments: Dict[str, SegmentConfig]
    regions: Dict[str, List[str]]
    owners: Dict[str, str]
    queues: Dict[str, str]

    @validator('version')
    def validate_version(cls, v):
        """Ensure version follows semantic versioning."""
        if not v.startswith('v'):
            raise ValueError('Version must start with v')
        return v

    def pick_segment(self, employee_count: int) -> str:
        """
        Determine segment based on employee count.

        Args:
            employee_count: Number of employees

        Returns:
            Segment identifier (SMB, MM, ENT, etc.)
        """
        for segment, config in self.segments.items():
            min_emp, max_emp = config.employee_range

            if max_emp is None:
                # Unbounded upper limit
                if employee_count >= min_emp:
                    return segment
            elif min_emp <= employee_count <= max_emp:
                return segment

        # Default fallback
        return 'SMB'

    def pick_region(self, country_code: str) -> str:
        """
        Determine region based on country code.

        Args:
            country_code: 2-letter country code

        Returns:
            Region identifier (NA, EMEA, APAC, etc.)
        """
        country_upper = country_code.upper()

        for region, countries in self.regions.items():
            if country_upper in countries:
                return region

        # Default fallback
        return 'NA'

    def pick_owner(self, segment: str, region: str) -> str:
        """
        Get owner ID for segment and region.

        Args:
            segment: Segment identifier
            region: Region identifier

        Returns:
            Salesforce User or Queue ID
        """
        key = f"{segment}_{region}"
        owner_id = self.owners.get(key)

        if owner_id:
            return owner_id

        # Fallback to default queue
        logger.warning(
            "No owner found for segment_region, using default queue",
            extra={'segment': segment, 'region': region, 'key': key}
        )
        return self.queues.get('default', '00Gxx0000000001AAA')


def load_routing_policy(policy_path: str = 'app/policies/routing_policy.json') -> RoutingPolicy:
    """
    Load and validate routing policy.

    Args:
        policy_path: Path to policy JSON file

    Returns:
        Validated RoutingPolicy instance

    Raises:
        FileNotFoundError: If policy file doesn't exist
        jsonschema.ValidationError: If policy is invalid
        ValueError: If policy data is malformed
    """
    policy_file = Path(policy_path)
    schema_file = Path(policy_path).parent / 'policy.schema.json'

    if not policy_file.exists():
        raise FileNotFoundError(f"Policy file not found: {policy_path}")

    # Load policy data
    with open(policy_file) as f:
        policy_data = json.load(f)

    # Validate against JSON schema if schema exists
    if schema_file.exists():
        with open(schema_file) as f:
            schema = json.load(f)

        try:
            jsonschema.validate(policy_data, schema)
            logger.info("Policy validated against JSON schema")
        except jsonschema.ValidationError as e:
            logger.error("Policy validation failed", extra={'error': str(e)})
            raise

    # Parse with Pydantic
    policy = RoutingPolicy(**policy_data)

    logger.info(
        "Routing policy loaded",
        extra={
            'version': policy.version,
            'segments': len(policy.segments),
            'regions': len(policy.regions),
            'owners': len(policy.owners)
        }
    )

    return policy


# Global policy instance (loaded on import)
_policy: Optional[RoutingPolicy] = None


def get_policy() -> RoutingPolicy:
    """
    Get cached policy instance.

    Returns:
        Cached RoutingPolicy
    """
    global _policy
    if _policy is None:
        _policy = load_routing_policy()
    return _policy


def reload_policy(policy_path: str = 'app/policies/routing_policy.json'):
    """
    Reload policy from disk.

    Args:
        policy_path: Path to policy JSON file
    """
    global _policy
    _policy = load_routing_policy(policy_path)
    logger.info("Policy reloaded", extra={'version': _policy.version})
