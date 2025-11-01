"""
Lead routing workload.

Automatically assigns new leads to the right owner/queue based on segment,
region, and product interest using LLM-based decision making.
"""

import json
import os
from typing import Any, Dict
import structlog
from anthropic import Anthropic
from src.salesforce.api_client import SalesforceAPIClient
from src.flywheel.logger import FlywheelLogger

logger = structlog.get_logger()


class LeadRouter:
    """Routes leads to appropriate owners based on lead attributes."""

    def __init__(
        self,
        sf_client: SalesforceAPIClient,
        flywheel_logger: FlywheelLogger,
        routing_policy_path: str = "./config/routing_policy.json"
    ):
        """
        Initialize lead router.

        Args:
            sf_client: Salesforce API client
            flywheel_logger: Flywheel logger
            routing_policy_path: Path to routing policy configuration
        """
        self.sf_client = sf_client
        self.flywheel_logger = flywheel_logger
        self.anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

        # Load routing policy
        self.routing_policy = self._load_routing_policy(routing_policy_path)

    def _load_routing_policy(self, policy_path: str) -> Dict[str, Any]:
        """Load routing policy from JSON file."""
        try:
            with open(policy_path, 'r') as f:
                policy = json.load(f)
            logger.info("routing_policy_loaded", path=policy_path)
            return policy
        except FileNotFoundError:
            logger.warning("routing_policy_not_found", path=policy_path)
            return self._get_default_policy()

    def _get_default_policy(self) -> Dict[str, Any]:
        """Get default routing policy."""
        return {
            "segments": {
                "SMB": {"employee_range": [1, 200], "priority": "low"},
                "MM": {"employee_range": [201, 2000], "priority": "medium"},
                "Enterprise": {"employee_range": [2001, None], "priority": "high"}
            },
            "regions": {
                "NA": ["US", "CA", "MX"],
                "EMEA": ["GB", "DE", "FR", "IT", "ES", "NL"],
                "APAC": ["AU", "JP", "SG", "IN", "CN"]
            },
            "owners": {
                "SMB_NA": "005xx0000012001",
                "SMB_EMEA": "005xx0000012002",
                "SMB_APAC": "005xx0000012003",
                "MM_NA": "005xx0000012011",
                "MM_EMEA": "005xx0000012012",
                "MM_APAC": "005xx0000012013",
                "Enterprise_NA": "005xx0000012021",
                "Enterprise_EMEA": "005xx0000012022",
                "Enterprise_APAC": "005xx0000012023"
            },
            "queues": {
                "default": "00Gxx0000000001"
            }
        }

    def _extract_lead_features(self, lead: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract features from lead for routing decision.

        Args:
            lead: Lead record from Salesforce

        Returns:
            Feature dictionary
        """
        return {
            "company": lead.get("Company", "Unknown"),
            "country": lead.get("Country", "Unknown"),
            "employee_count": lead.get("NumberOfEmployees", 0),
            "product_interest": lead.get("Product_Interest__c", "Unknown"),
            "industry": lead.get("Industry", "Unknown"),
            "annual_revenue": lead.get("AnnualRevenue", 0),
            "lead_source": lead.get("LeadSource", "Unknown"),
            "description": lead.get("Description", "")
        }

    def _determine_segment(self, employee_count: int) -> str:
        """Determine segment based on employee count."""
        for segment, config in self.routing_policy["segments"].items():
            min_emp, max_emp = config["employee_range"]
            if max_emp is None:
                if employee_count >= min_emp:
                    return segment
            elif min_emp <= employee_count <= max_emp:
                return segment
        return "SMB"  # Default

    def _determine_region(self, country: str) -> str:
        """Determine region based on country."""
        for region, countries in self.routing_policy["regions"].items():
            if country in countries:
                return region
        return "NA"  # Default

    def route_lead(self, lead_id: str) -> Dict[str, Any]:
        """
        Route a lead to the appropriate owner.

        Args:
            lead_id: Salesforce Lead ID

        Returns:
            Routing decision dictionary
        """
        logger.info("routing_lead", lead_id=lead_id)

        # Get lead data
        lead = self.sf_client.get_record("Lead", lead_id)
        features = self._extract_lead_features(lead)

        # Basic rule-based routing
        segment = self._determine_segment(features["employee_count"])
        region = self._determine_region(features["country"])

        # Use LLM for complex cases or validation
        routing_decision = self._llm_route_decision(features, segment, region)

        # Get owner ID from policy
        owner_key = f"{routing_decision['segment']}_{routing_decision['region']}"
        owner_id = self.routing_policy["owners"].get(
            owner_key,
            self.routing_policy["queues"]["default"]
        )

        routing_decision["owner"] = owner_id

        # Update lead in Salesforce
        try:
            self.sf_client.update_record("Lead", lead_id, {"OwnerId": owner_id})
            routing_decision["status"] = "assigned"
            logger.info("lead_assigned", lead_id=lead_id, owner=owner_id)
        except Exception as e:
            routing_decision["status"] = "failed"
            routing_decision["error"] = str(e)
            logger.error("lead_assignment_failed", lead_id=lead_id, error=str(e))

        # Log to flywheel
        self.flywheel_logger.log_lead_route(
            lead_id=lead_id,
            lead_data=features,
            routing_decision=routing_decision,
            model_used="claude-3-sonnet"
        )

        return routing_decision

    def _llm_route_decision(
        self,
        features: Dict[str, Any],
        suggested_segment: str,
        suggested_region: str
    ) -> Dict[str, Any]:
        """
        Use LLM to validate or refine routing decision.

        Args:
            features: Lead features
            suggested_segment: Rule-based segment suggestion
            suggested_region: Rule-based region suggestion

        Returns:
            Routing decision with reasoning
        """
        prompt = f"""You are a lead routing expert. Based on the lead information below, determine the best segment and region assignment.

Lead Information:
- Company: {features['company']}
- Country: {features['country']}
- Employee Count: {features['employee_count']}
- Product Interest: {features['product_interest']}
- Industry: {features['industry']}
- Annual Revenue: {features['annual_revenue']}
- Lead Source: {features['lead_source']}

Suggested Assignment:
- Segment: {suggested_segment} (SMB: 1-200 employees, MM: 201-2000, Enterprise: 2001+)
- Region: {suggested_region} (NA, EMEA, APAC)

Return your decision in JSON format:
{{
  "segment": "SMB|MM|Enterprise",
  "region": "NA|EMEA|APAC",
  "reason": "Brief explanation of routing decision",
  "confidence": 0.0-1.0
}}"""

        try:
            response = self.anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text

            # Extract JSON from response
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            decision = json.loads(json_str)

            logger.info("llm_routing_decision", decision=decision)
            return decision

        except Exception as e:
            logger.error("llm_routing_failed", error=str(e))
            # Fallback to rule-based decision
            return {
                "segment": suggested_segment,
                "region": suggested_region,
                "reason": "Fallback to rule-based routing",
                "confidence": 0.5
            }


def route_lead_from_event(lead_id: str) -> Dict[str, Any]:
    """
    Convenience function to route a lead from CDC event.

    Args:
        lead_id: Lead ID from CDC event

    Returns:
        Routing decision
    """
    from src.auth.jwt_auth import create_auth_from_env
    from src.flywheel.logger import create_logger_from_env

    auth = create_auth_from_env()
    sf_client = SalesforceAPIClient(auth)
    flywheel_logger = create_logger_from_env()

    router = LeadRouter(sf_client, flywheel_logger)
    return router.route_lead(lead_id)


if __name__ == "__main__":
    # Test routing
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    if len(sys.argv) > 1:
        lead_id = sys.argv[1]
        result = route_lead_from_event(lead_id)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python lead_route.py <lead_id>")
