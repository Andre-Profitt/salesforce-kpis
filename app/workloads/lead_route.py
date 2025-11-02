"""
Lead routing workload with assignment latency tracking.

Routes leads based on policy and tracks when leads are assigned to users.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from prometheus_client import Counter, Histogram

from app.policies.load import load_routing_policy, RoutingPolicy
from app.web.metrics import decisions_total, assignment_latency_seconds

logger = logging.getLogger(__name__)

# Routing-specific metrics
routing_decisions = Counter(
    'routing_decisions_total',
    'Total routing decisions made',
    ['segment', 'region', 'outcome']
)


class LeadRouter:
    """
    Routes leads to owners based on policy.

    Tracks assignment latency when leads are assigned from queue to user.
    """

    def __init__(self, sf_client, policy_path: Optional[str] = None):
        """
        Initialize lead router.

        Args:
            sf_client: Salesforce API client
            policy_path: Path to routing policy JSON (defaults to config/routing_policy.json)
        """
        self.sf = sf_client

        # Load routing policy
        if policy_path is None:
            import os
            from pathlib import Path
            repo_root = Path(__file__).parent.parent.parent
            policy_path = os.path.join(repo_root, 'app', 'policies', 'routing_policy.json')

        self.policy = load_routing_policy(policy_path)

        logger.info(
            "LeadRouter initialized",
            extra={'policy_version': self.policy.version}
        )

    def route_lead(self, lead_id: str) -> Dict[str, Any]:
        """
        Route a lead to an owner based on policy.

        Args:
            lead_id: Lead ID to route

        Returns:
            Routing decision with outcome
        """
        logger.info("Routing lead", extra={'lead_id': lead_id})

        # Get lead details
        lead = self.sf.get_record('Lead', lead_id, fields=[
            'Id', 'Company', 'NumberOfEmployees', 'Country',
            'OwnerId', 'CreatedDate', 'Owner_Assigned_At__c'
        ])

        # Determine segment and region
        employee_count = lead.get('NumberOfEmployees', 0) or 0
        country = lead.get('Country', 'US')

        segment = self.policy.pick_segment(employee_count)
        region = self.policy.pick_region(country)

        # Determine owner
        new_owner_id = self.policy.pick_owner(segment, region)

        # Check if owner is changing
        current_owner_id = lead.get('OwnerId')
        is_queue = current_owner_id.startswith('00G') if current_owner_id else False

        decision = {
            'lead_id': lead_id,
            'segment': segment,
            'region': region,
            'owner_id': new_owner_id,
            'current_owner': current_owner_id,
            'is_queue': is_queue,
            'policy_version': self.policy.version,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        # If owner is same, skip
        if current_owner_id == new_owner_id:
            logger.info(
                "Owner unchanged, skipping",
                extra=decision
            )

            decisions_total.labels(
                workload='lead.route',
                outcome='skipped_same_owner'
            ).inc()

            routing_decisions.labels(
                segment=segment,
                region=region,
                outcome='skipped_same_owner'
            ).inc()

            decision['outcome'] = 'skipped_same_owner'
            return decision

        # Update owner
        update_fields = {
            'OwnerId': new_owner_id
        }

        # If transitioning from queue to user, track assignment time
        new_is_queue = new_owner_id.startswith('00G')

        if is_queue and not new_is_queue:
            # Assigning from queue to user
            now = datetime.utcnow()
            owner_assigned_at = now.isoformat() + 'Z'

            # Calculate assignment latency
            created_date = datetime.fromisoformat(
                lead['CreatedDate'].replace('Z', '+00:00')
            )
            latency_seconds = (now - created_date).total_seconds()
            latency_minutes = int(latency_seconds / 60)

            # Add assignment fields
            update_fields['Owner_Assigned_At__c'] = owner_assigned_at
            update_fields['Assignment_Latency_Minutes__c'] = latency_minutes

            # Record metric
            assignment_latency_seconds.observe(latency_seconds)

            decision['owner_assigned_at'] = owner_assigned_at
            decision['assignment_latency_minutes'] = latency_minutes

            logger.info(
                "Lead assigned from queue to user",
                extra={
                    'lead_id': lead_id,
                    'owner_id': new_owner_id,
                    'latency_minutes': latency_minutes
                }
            )

        # Perform update
        try:
            self.sf.update_record('Lead', lead_id, update_fields)

            decisions_total.labels(
                workload='lead.route',
                outcome='success'
            ).inc()

            routing_decisions.labels(
                segment=segment,
                region=region,
                outcome='success'
            ).inc()

            decision['outcome'] = 'success'
            decision['updated_fields'] = list(update_fields.keys())

            logger.info(
                "Lead routed successfully",
                extra=decision
            )

            return decision

        except Exception as e:
            logger.error(
                "Failed to route lead",
                extra={
                    'lead_id': lead_id,
                    'error': str(e)
                }
            )

            decisions_total.labels(
                workload='lead.route',
                outcome='error'
            ).inc()

            routing_decisions.labels(
                segment=segment,
                region=region,
                outcome='error'
            ).inc()

            decision['outcome'] = 'error'
            decision['error'] = str(e)

            return decision

    def route_batch(self, lead_ids: list) -> Dict[str, Any]:
        """
        Route multiple leads in batch.

        Args:
            lead_ids: List of lead IDs

        Returns:
            Batch results summary
        """
        results = {
            'total': len(lead_ids),
            'success': 0,
            'skipped': 0,
            'errors': 0,
            'decisions': []
        }

        for lead_id in lead_ids:
            try:
                decision = self.route_lead(lead_id)
                results['decisions'].append(decision)

                if decision['outcome'] == 'success':
                    results['success'] += 1
                elif decision['outcome'].startswith('skipped'):
                    results['skipped'] += 1
                else:
                    results['errors'] += 1

            except Exception as e:
                logger.error(
                    "Batch routing error",
                    extra={'lead_id': lead_id, 'error': str(e)}
                )
                results['errors'] += 1

        logger.info(
            "Batch routing complete",
            extra=results
        )

        return results
