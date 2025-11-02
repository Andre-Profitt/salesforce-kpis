"""
Load flywheel logs to Elasticsearch.

Enables:
- Full-text search of decision history
- Time-series analysis with Kibana
- Aggregations and dashboards
- Alerting on decision patterns
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class ElasticsearchLoader:
    """Load flywheel logs to Elasticsearch."""

    def __init__(
        self,
        hosts: List[str],
        index_prefix: str = "flywheel",
        api_key: Optional[str] = None
    ):
        """
        Initialize Elasticsearch loader.

        Args:
            hosts: List of Elasticsearch hosts
            index_prefix: Index prefix (default: "flywheel")
            api_key: Optional API key for authentication
        """
        try:
            from elasticsearch import Elasticsearch
        except ImportError:
            raise ImportError(
                "elasticsearch package required. Install with: pip install elasticsearch"
            )

        self.es = Elasticsearch(
            hosts=hosts,
            api_key=api_key
        )
        self.index_prefix = index_prefix

        logger.info(
            "ElasticsearchLoader initialized",
            extra={
                'hosts': hosts,
                'index_prefix': index_prefix
            }
        )

    def _get_index_name(self, workload_id: str, timestamp: int) -> str:
        """
        Get index name for a workload and timestamp.

        Uses monthly indices: flywheel-lead.route-2025-01

        Args:
            workload_id: Workload identifier
            timestamp: Unix timestamp

        Returns:
            Index name
        """
        dt = datetime.utcfromtimestamp(timestamp)
        year_month = dt.strftime('%Y-%m')

        # Sanitize workload_id
        safe_workload = workload_id.replace('.', '-')

        return f"{self.index_prefix}-{safe_workload}-{year_month}"

    def create_index_template(self):
        """
        Create index template for flywheel logs.

        Defines mappings and settings for flywheel indices.
        """
        template = {
            "index_patterns": [f"{self.index_prefix}-*"],
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 1,
                    "index": {
                        "lifecycle": {
                            "name": "flywheel_policy",
                            "rollover_alias": f"{self.index_prefix}"
                        }
                    }
                },
                "mappings": {
                    "properties": {
                        "timestamp": {
                            "type": "date",
                            "format": "epoch_second"
                        },
                        "client_id": {
                            "type": "keyword"
                        },
                        "workload_id": {
                            "type": "keyword"
                        },
                        "lead_id": {
                            "type": "keyword"
                        },
                        "policy_version": {
                            "type": "keyword"
                        },
                        "request": {
                            "properties": {
                                "model": {"type": "keyword"},
                                "messages": {
                                    "properties": {
                                        "role": {"type": "keyword"},
                                        "content": {"type": "text"}
                                    }
                                }
                            }
                        },
                        "response": {
                            "properties": {
                                "id": {"type": "keyword"},
                                "model": {"type": "keyword"},
                                "choices": {
                                    "properties": {
                                        "message": {
                                            "properties": {
                                                "role": {"type": "keyword"},
                                                "content": {"type": "text"}
                                            }
                                        },
                                        "finish_reason": {"type": "keyword"}
                                    }
                                }
                            }
                        },
                        "metadata": {
                            "properties": {
                                "latency_ms": {"type": "float"},
                                "outcome": {"type": "keyword"}
                            }
                        }
                    }
                }
            }
        }

        self.es.indices.put_index_template(
            name=f"{self.index_prefix}_template",
            body=template
        )

        logger.info("Index template created")

    def index_record(self, record: Dict[str, Any]):
        """
        Index a single flywheel record.

        Args:
            record: Flywheel record dictionary
        """
        index_name = self._get_index_name(
            record['workload_id'],
            record['timestamp']
        )

        doc_id = f"{record['client_id']}-{record['timestamp']}"

        self.es.index(
            index=index_name,
            id=doc_id,
            document=record
        )

    def bulk_index(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Bulk index flywheel records.

        Args:
            records: List of flywheel records

        Returns:
            Statistics (indexed, errors)
        """
        from elasticsearch.helpers import bulk

        actions = []

        for record in records:
            index_name = self._get_index_name(
                record['workload_id'],
                record['timestamp']
            )

            doc_id = f"{record['client_id']}-{record['timestamp']}"

            action = {
                '_index': index_name,
                '_id': doc_id,
                '_source': record
            }

            actions.append(action)

        success, errors = bulk(self.es, actions, stats_only=True)

        logger.info(
            "Bulk index complete",
            extra={'indexed': success, 'errors': errors}
        )

        return {
            'indexed': success,
            'errors': errors
        }

    def search(
        self,
        workload_id: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        outcome: Optional[str] = None,
        size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search flywheel logs.

        Args:
            workload_id: Optional workload filter
            start_timestamp: Optional start timestamp
            end_timestamp: Optional end timestamp
            outcome: Optional outcome filter
            size: Number of results (default: 100)

        Returns:
            List of matching records
        """
        query = {
            "bool": {
                "must": []
            }
        }

        if workload_id:
            query["bool"]["must"].append({
                "term": {"workload_id": workload_id}
            })

        if start_timestamp or end_timestamp:
            range_query = {"range": {"timestamp": {}}}

            if start_timestamp:
                range_query["range"]["timestamp"]["gte"] = start_timestamp

            if end_timestamp:
                range_query["range"]["timestamp"]["lte"] = end_timestamp

            query["bool"]["must"].append(range_query)

        if outcome:
            query["bool"]["must"].append({
                "term": {"metadata.outcome": outcome}
            })

        results = self.es.search(
            index=f"{self.index_prefix}-*",
            query=query,
            size=size,
            sort=[{"timestamp": "desc"}]
        )

        return [hit['_source'] for hit in results['hits']['hits']]
