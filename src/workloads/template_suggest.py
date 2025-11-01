"""
Outreach template suggestion workload.

Recommends personalized email templates based on inbound inquiry context.
"""

import json
import os
from typing import Any, Dict, List, Optional
import structlog
from anthropic import Anthropic
from src.salesforce.api_client import SalesforceAPIClient
from src.flywheel.logger import FlywheelLogger

logger = structlog.get_logger()


class TemplateSuggester:
    """Suggests email templates for lead outreach."""

    def __init__(
        self,
        sf_client: SalesforceAPIClient,
        flywheel_logger: FlywheelLogger,
        templates_path: str = "./config/templates.json"
    ):
        """
        Initialize template suggester.

        Args:
            sf_client: Salesforce API client
            flywheel_logger: Flywheel logger
            templates_path: Path to templates configuration
        """
        self.sf_client = sf_client
        self.flywheel_logger = flywheel_logger
        self.anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

        # Load templates
        self.templates = self._load_templates(templates_path)

    def _load_templates(self, templates_path: str) -> List[Dict[str, Any]]:
        """Load email templates from JSON file."""
        try:
            with open(templates_path, 'r') as f:
                templates = json.load(f)
            logger.info("templates_loaded", path=templates_path, count=len(templates))
            return templates
        except FileNotFoundError:
            logger.warning("templates_not_found", path=templates_path)
            return self._get_default_templates()

    def _get_default_templates(self) -> List[Dict[str, Any]]:
        """Get default email templates."""
        return [
            {
                "id": "pricing_inquiry",
                "name": "Pricing Inquiry Response",
                "intent": "pricing",
                "subject": "Re: Pricing information for {{product}}",
                "body": """Hi {{first_name}},

Thanks for your interest in {{product}}! I'd be happy to discuss pricing options that fit your needs.

Based on your company size ({{employee_count}} employees), I recommend our {{segment}} plan which includes:
- {{feature_1}}
- {{feature_2}}
- {{feature_3}}

Would you be available for a quick 15-minute call this week to discuss your specific requirements?

Best regards,
{{rep_name}}""",
                "variables": ["first_name", "product", "employee_count", "segment", "feature_1", "feature_2", "feature_3", "rep_name"]
            },
            {
                "id": "demo_request",
                "name": "Demo Request Response",
                "intent": "demo",
                "subject": "Let's schedule your {{product}} demo",
                "body": """Hi {{first_name}},

Thanks for requesting a demo of {{product}}! I'm excited to show you how we can help {{company}} {{benefit}}.

I have availability this week on:
- {{time_option_1}}
- {{time_option_2}}
- {{time_option_3}}

Which works best for you? The demo typically takes 30 minutes and I'll customize it to your {{industry}} use case.

Looking forward to connecting!

Best,
{{rep_name}}""",
                "variables": ["first_name", "product", "company", "benefit", "time_option_1", "time_option_2", "time_option_3", "industry", "rep_name"]
            },
            {
                "id": "technical_question",
                "name": "Technical Question Response",
                "intent": "technical",
                "subject": "Re: {{product}} - {{question_topic}}",
                "body": """Hi {{first_name}},

Great question about {{question_topic}}! Here's how {{product}} handles this:

{{technical_answer}}

For {{industry}} companies like {{company}}, this typically means {{benefit}}.

I'd be happy to discuss this in more detail or connect you with our solutions engineer. Would a technical deep-dive call be helpful?

Best regards,
{{rep_name}}""",
                "variables": ["first_name", "question_topic", "product", "technical_answer", "industry", "company", "benefit", "rep_name"]
            },
            {
                "id": "general_inquiry",
                "name": "General Inquiry Response",
                "intent": "general",
                "subject": "Re: Inquiry about {{product}}",
                "body": """Hi {{first_name}},

Thanks for reaching out about {{product}}! We help {{industry}} companies {{primary_benefit}}.

Based on your inquiry, I think you'd be interested in:
- {{feature_1}}
- {{feature_2}}

Would you like to schedule a brief call to discuss how we can help {{company}} specifically?

Best,
{{rep_name}}""",
                "variables": ["first_name", "product", "industry", "primary_benefit", "feature_1", "feature_2", "company", "rep_name"]
            }
        ]

    def suggest_template(
        self,
        lead_id: str,
        inquiry_text: Optional[str] = None,
        send_email: bool = False
    ) -> Dict[str, Any]:
        """
        Suggest email template for a lead.

        Args:
            lead_id: Salesforce Lead ID
            inquiry_text: Optional inbound inquiry text (uses Description if not provided)
            send_email: Whether to send email via Salesforce API

        Returns:
            Template suggestion with personalization
        """
        logger.info("suggesting_template", lead_id=lead_id)

        # Get lead data
        lead = self.sf_client.get_record(
            "Lead",
            lead_id,
            fields=[
                "Id", "FirstName", "LastName", "Company", "Email",
                "Industry", "NumberOfEmployees", "Product_Interest__c",
                "Description", "OwnerId", "Owner.Name"
            ]
        )

        # Use inquiry text or lead description
        if not inquiry_text:
            inquiry_text = lead.get("Description", "General inquiry")

        # Get template suggestion from LLM
        suggestion = self._llm_template_suggestion(lead, inquiry_text)

        # Fill template variables
        filled_template = self._fill_template_variables(suggestion, lead)

        # Optionally send email
        if send_email and filled_template.get("email"):
            try:
                self.sf_client.send_email_simple(
                    to_addresses=[lead["Email"]],
                    subject=filled_template["subject"],
                    body=filled_template["body"]
                )
                filled_template["email_sent"] = True
                logger.info("template_email_sent", lead_id=lead_id)
            except Exception as e:
                filled_template["email_sent"] = False
                filled_template["email_error"] = str(e)
                logger.error("template_email_failed", lead_id=lead_id, error=str(e))

        # Log to flywheel
        self.flywheel_logger.log_template_suggest(
            lead_id=lead_id,
            inquiry_text=inquiry_text,
            template_suggestion=suggestion,
            model_used="claude-3-5-sonnet-20241022"
        )

        return filled_template

    def _llm_template_suggestion(
        self,
        lead: Dict[str, Any],
        inquiry_text: str
    ) -> Dict[str, Any]:
        """
        Use LLM to select and personalize template.

        Args:
            lead: Lead record data
            inquiry_text: Inbound inquiry text

        Returns:
            Template suggestion with reasoning
        """
        # Build template options description
        template_options = "\n".join([
            f"{i+1}. {t['name']} (ID: {t['id']}) - For {t['intent']} inquiries"
            for i, t in enumerate(self.templates)
        ])

        prompt = f"""You are an expert sales outreach specialist. Based on the inbound inquiry and lead information, recommend the best email template and personalization.

Lead Information:
- Name: {lead.get('FirstName', '')} {lead.get('LastName', '')}
- Company: {lead.get('Company', 'Unknown')}
- Industry: {lead.get('Industry', 'Unknown')}
- Employee Count: {lead.get('NumberOfEmployees', 'N/A')}
- Product Interest: {lead.get('Product_Interest__c', 'Unknown')}

Inbound Inquiry:
"{inquiry_text}"

Available Templates:
{template_options}

Return your recommendation in JSON format:
{{
  "template_id": "template_id_here",
  "reason": "Why this template is best for this inquiry",
  "intent_detected": "pricing|demo|technical|general",
  "confidence": 0.0-1.0,
  "personalization": {{
    "key_points": ["point1", "point2"],
    "tone": "professional|friendly|technical",
    "urgency": "high|medium|low"
  }},
  "variable_suggestions": {{
    "product": "suggested value",
    "benefit": "suggested value"
  }}
}}"""

        try:
            response = self.anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text

            # Extract JSON
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            suggestion = json.loads(json_str)

            logger.info("template_suggestion_generated", template_id=suggestion["template_id"])
            return suggestion

        except Exception as e:
            logger.error("template_suggestion_failed", error=str(e))
            # Fallback to general inquiry template
            return {
                "template_id": "general_inquiry",
                "reason": "Fallback to default template",
                "intent_detected": "general",
                "confidence": 0.3,
                "personalization": {"key_points": [], "tone": "professional", "urgency": "medium"},
                "variable_suggestions": {}
            }

    def _fill_template_variables(
        self,
        suggestion: Dict[str, Any],
        lead: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fill template with personalized variables.

        Args:
            suggestion: Template suggestion from LLM
            lead: Lead record data

        Returns:
            Filled template with subject and body
        """
        # Find template
        template = next(
            (t for t in self.templates if t["id"] == suggestion["template_id"]),
            self.templates[0]  # Fallback to first template
        )

        # Build variable map
        variables = {
            "first_name": lead.get("FirstName", "there"),
            "last_name": lead.get("LastName", ""),
            "company": lead.get("Company", "your company"),
            "industry": lead.get("Industry", "your industry"),
            "employee_count": str(lead.get("NumberOfEmployees", "N/A")),
            "product": lead.get("Product_Interest__c", "our products"),
            "rep_name": lead.get("Owner", {}).get("Name", "Sales Team"),
            "segment": "Enterprise" if lead.get("NumberOfEmployees", 0) > 2000 else "Professional"
        }

        # Add LLM suggestions
        variables.update(suggestion.get("variable_suggestions", {}))

        # Fill subject
        subject = template["subject"]
        for key, value in variables.items():
            subject = subject.replace(f"{{{{{key}}}}}", str(value))

        # Fill body
        body = template["body"]
        for key, value in variables.items():
            body = body.replace(f"{{{{{key}}}}}", str(value))

        return {
            "template_id": template["id"],
            "template_name": template["name"],
            "subject": subject,
            "body": body,
            "intent": suggestion["intent_detected"],
            "confidence": suggestion["confidence"],
            "reason": suggestion["reason"],
            "email": lead.get("Email")
        }


def suggest_template_from_event(lead_id: str, inquiry_text: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to suggest template from CDC event.

    Args:
        lead_id: Lead ID from CDC event
        inquiry_text: Optional inquiry text

    Returns:
        Template suggestion
    """
    from src.auth.jwt_auth import create_auth_from_env
    from src.flywheel.logger import create_logger_from_env

    auth = create_auth_from_env()
    sf_client = SalesforceAPIClient(auth)
    flywheel_logger = create_logger_from_env()

    suggester = TemplateSuggester(sf_client, flywheel_logger)
    return suggester.suggest_template(lead_id, inquiry_text)


if __name__ == "__main__":
    # Test template suggestion
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    if len(sys.argv) > 1:
        lead_id = sys.argv[1]
        inquiry = sys.argv[2] if len(sys.argv) > 2 else None
        send = "--send" in sys.argv

        suggester = suggest_template_from_event(lead_id, inquiry)
        print(json.dumps(suggester, indent=2))
    else:
        print("Usage: python template_suggest.py <lead_id> [inquiry_text] [--send]")
