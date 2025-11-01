"""
Metrics extraction and dashboard generation.

Analyzes flywheel logs and Salesforce data to generate KPI reports.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import structlog
from src.salesforce.api_client import SalesforceAPIClient
from src.flywheel.logger import FlywheelLogger

logger = structlog.get_logger()


class MetricsExtractor:
    """Extracts and analyzes metrics for routing, TTFR, and templates."""

    def __init__(
        self,
        sf_client: SalesforceAPIClient,
        flywheel_logger: FlywheelLogger,
        output_dir: str = "./reports"
    ):
        """
        Initialize metrics extractor.

        Args:
            sf_client: Salesforce API client
            flywheel_logger: Flywheel logger
            output_dir: Output directory for reports
        """
        self.sf_client = sf_client
        self.flywheel_logger = flywheel_logger
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_routing_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Extract lead routing metrics.

        Metrics:
        - Routing accuracy (segment/region match vs. policy)
        - Assignment latency (time from lead creation to assignment)
        - Distribution by segment/region

        Args:
            days: Number of days to analyze

        Returns:
            Routing metrics dictionary
        """
        logger.info("extracting_routing_metrics", days=days)

        # Get flywheel logs for routing
        routing_logs = self.flywheel_logger.get_logs("lead.route", days=days)

        if not routing_logs:
            logger.warning("no_routing_logs_found")
            return {"error": "No routing logs found"}

        # Convert to DataFrame
        df_logs = pd.DataFrame(routing_logs)

        # Extract decision data
        decisions = []
        for _, row in df_logs.iterrows():
            response = row.get('response', {})
            metadata = row.get('metadata', {})

            if response and 'choices' in response:
                content = response['choices'][0]['message']['content']
                decision = json.loads(content)

                decisions.append({
                    'timestamp': row.get('timestamp'),
                    'lead_id': metadata.get('lead_id'),
                    'segment': decision.get('segment'),
                    'region': decision.get('region'),
                    'confidence': decision.get('confidence', 0),
                    'reason': decision.get('reason', '')
                })

        df_decisions = pd.DataFrame(decisions)

        # Calculate metrics
        metrics = {
            "total_routed": len(df_decisions),
            "by_segment": df_decisions['segment'].value_counts().to_dict(),
            "by_region": df_decisions['region'].value_counts().to_dict(),
            "avg_confidence": float(df_decisions['confidence'].mean()),
            "confidence_distribution": {
                "high (>0.8)": int((df_decisions['confidence'] > 0.8).sum()),
                "medium (0.5-0.8)": int(((df_decisions['confidence'] >= 0.5) & (df_decisions['confidence'] <= 0.8)).sum()),
                "low (<0.5)": int((df_decisions['confidence'] < 0.5).sum())
            }
        }

        # Get assignment latency from Salesforce
        latency_data = self._get_assignment_latency(days)
        metrics['assignment_latency'] = latency_data

        # Save to CSV
        csv_path = self.output_dir / f"routing_metrics_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        df_decisions.to_csv(csv_path, index=False)
        logger.info("routing_metrics_saved", path=str(csv_path))

        return metrics

    def _get_assignment_latency(self, days: int) -> Dict[str, float]:
        """Get assignment latency from Salesforce."""
        soql = f"""
            SELECT Id, CreatedDate, SystemModstamp
            FROM Lead
            WHERE CreatedDate = LAST_N_DAYS:{days}
            AND OwnerId != NULL
        """

        leads = self.sf_client.query(soql)

        latencies = []
        for lead in leads:
            created = datetime.fromisoformat(lead['CreatedDate'].replace('Z', '+00:00'))
            modified = datetime.fromisoformat(lead['SystemModstamp'].replace('Z', '+00:00'))
            latency_seconds = (modified - created).total_seconds()
            latencies.append(latency_seconds)

        if not latencies:
            return {"median": 0, "p95": 0, "max": 0}

        latencies_series = pd.Series(latencies)

        return {
            "median_seconds": float(latencies_series.median()),
            "p95_seconds": float(latencies_series.quantile(0.95)),
            "max_seconds": float(latencies_series.max()),
            "avg_seconds": float(latencies_series.mean())
        }

    def extract_ttfr_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Extract time-to-first-response (TTFR) metrics.

        Metrics:
        - TTFR median, P95, max
        - SLA breach rate (e.g., >60 minutes)
        - Distribution by segment/region

        Args:
            days: Number of days to analyze

        Returns:
            TTFR metrics dictionary
        """
        logger.info("extracting_ttfr_metrics", days=days)

        # Query leads with first response data
        soql = f"""
            SELECT Id, CreatedDate, First_Response_At__c,
                   Time_to_First_Response__c, First_Response_User__c,
                   OwnerId, Owner.Name
            FROM Lead
            WHERE CreatedDate = LAST_N_DAYS:{days}
            AND First_Response_At__c != NULL
        """

        leads = self.sf_client.query(soql)

        if not leads:
            logger.warning("no_ttfr_data_found")
            return {"error": "No TTFR data found"}

        # Convert to DataFrame
        df = pd.DataFrame(leads)
        df['ttfr_minutes'] = df['Time_to_First_Response__c'].astype(float)

        # SLA threshold (60 minutes)
        sla_threshold = 60

        metrics = {
            "total_responses": len(df),
            "ttfr_stats": {
                "median_minutes": float(df['ttfr_minutes'].median()),
                "p95_minutes": float(df['ttfr_minutes'].quantile(0.95)),
                "max_minutes": float(df['ttfr_minutes'].max()),
                "avg_minutes": float(df['ttfr_minutes'].mean())
            },
            "sla_performance": {
                "threshold_minutes": sla_threshold,
                "within_sla": int((df['ttfr_minutes'] <= sla_threshold).sum()),
                "breach_sla": int((df['ttfr_minutes'] > sla_threshold).sum()),
                "breach_rate": float((df['ttfr_minutes'] > sla_threshold).sum() / len(df))
            },
            "distribution": {
                "0-15min": int((df['ttfr_minutes'] <= 15).sum()),
                "15-30min": int(((df['ttfr_minutes'] > 15) & (df['ttfr_minutes'] <= 30)).sum()),
                "30-60min": int(((df['ttfr_minutes'] > 30) & (df['ttfr_minutes'] <= 60)).sum()),
                "60min+": int((df['ttfr_minutes'] > 60).sum())
            }
        }

        # Save to CSV
        csv_path = self.output_dir / f"ttfr_metrics_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        df[['Id', 'CreatedDate', 'First_Response_At__c', 'ttfr_minutes', 'Owner']].to_csv(csv_path, index=False)
        logger.info("ttfr_metrics_saved", path=str(csv_path))

        return metrics

    def extract_template_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Extract template suggestion metrics.

        Metrics:
        - Template usage distribution
        - Confidence scores
        - Intent detection accuracy

        Args:
            days: Number of days to analyze

        Returns:
            Template metrics dictionary
        """
        logger.info("extracting_template_metrics", days=days)

        # Get flywheel logs for templates
        template_logs = self.flywheel_logger.get_logs("outreach.template_suggest", days=days)

        if not template_logs:
            logger.warning("no_template_logs_found")
            return {"error": "No template logs found"}

        # Convert to DataFrame
        df_logs = pd.DataFrame(template_logs)

        # Extract suggestions
        suggestions = []
        for _, row in df_logs.iterrows():
            response = row.get('response', {})
            metadata = row.get('metadata', {})

            if response and 'choices' in response:
                content = response['choices'][0]['message']['content']
                suggestion = json.loads(content)

                suggestions.append({
                    'timestamp': row.get('timestamp'),
                    'lead_id': metadata.get('lead_id'),
                    'template_id': suggestion.get('template_id'),
                    'intent': suggestion.get('intent_detected'),
                    'confidence': suggestion.get('confidence', 0),
                    'reason': suggestion.get('reason', '')
                })

        df_suggestions = pd.DataFrame(suggestions)

        # Calculate metrics
        metrics = {
            "total_suggestions": len(df_suggestions),
            "by_template": df_suggestions['template_id'].value_counts().to_dict(),
            "by_intent": df_suggestions['intent'].value_counts().to_dict(),
            "avg_confidence": float(df_suggestions['confidence'].mean()),
            "confidence_distribution": {
                "high (>0.8)": int((df_suggestions['confidence'] > 0.8).sum()),
                "medium (0.5-0.8)": int(((df_suggestions['confidence'] >= 0.5) & (df_suggestions['confidence'] <= 0.8)).sum()),
                "low (<0.5)": int((df_suggestions['confidence'] < 0.5).sum())
            }
        }

        # Save to CSV
        csv_path = self.output_dir / f"template_metrics_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        df_suggestions.to_csv(csv_path, index=False)
        logger.info("template_metrics_saved", path=str(csv_path))

        return metrics

    def generate_dashboard(self, days: int = 30) -> Dict[str, Any]:
        """
        Generate comprehensive metrics dashboard.

        Args:
            days: Number of days to analyze

        Returns:
            Complete dashboard data
        """
        logger.info("generating_dashboard", days=days)

        dashboard = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "period_days": days,
            "routing": self.extract_routing_metrics(days),
            "ttfr": self.extract_ttfr_metrics(days),
            "templates": self.extract_template_metrics(days)
        }

        # Save JSON dashboard
        json_path = self.output_dir / f"dashboard_{datetime.utcnow().strftime('%Y%m%d')}.json"
        with open(json_path, 'w') as f:
            json.dump(dashboard, f, indent=2)

        logger.info("dashboard_generated", path=str(json_path))

        return dashboard


def generate_metrics_from_env(days: int = 30, output_dir: str = "./reports") -> Dict[str, Any]:
    """
    Generate metrics dashboard from environment configuration.

    Args:
        days: Number of days to analyze
        output_dir: Output directory for reports

    Returns:
        Dashboard data
    """
    from src.auth.jwt_auth import create_auth_from_env
    from src.flywheel.logger import create_logger_from_env

    auth = create_auth_from_env()
    sf_client = SalesforceAPIClient(auth)
    flywheel_logger = create_logger_from_env()

    extractor = MetricsExtractor(sf_client, flywheel_logger, output_dir)
    return extractor.generate_dashboard(days)


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./reports"

    dashboard = generate_metrics_from_env(days, output_dir)
    print(json.dumps(dashboard, indent=2))
