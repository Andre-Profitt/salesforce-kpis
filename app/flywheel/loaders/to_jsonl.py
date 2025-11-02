"""
Load flywheel logs from JSONL files.

Provides utilities for reading, filtering, and analyzing flywheel decision logs.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Iterator


class FlywheelJSONLLoader:
    """Load and query flywheel JSONL logs."""

    def __init__(self, log_dir: str = "data/flywheel"):
        """
        Initialize loader.

        Args:
            log_dir: Directory containing flywheel JSONL files
        """
        self.log_dir = Path(log_dir)

    def list_workloads(self) -> List[str]:
        """
        List all workloads with flywheel logs.

        Returns:
            List of workload IDs
        """
        if not self.log_dir.exists():
            return []

        workloads = []
        for log_file in self.log_dir.glob("*.jsonl"):
            workload_id = log_file.stem.replace('_', '.')
            workloads.append(workload_id)

        return sorted(workloads)

    def iter_records(
        self,
        workload_id: str,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Iterate over flywheel records for a workload.

        Args:
            workload_id: Workload identifier
            start_timestamp: Optional start timestamp (Unix epoch)
            end_timestamp: Optional end timestamp (Unix epoch)

        Yields:
            Flywheel record dictionaries
        """
        log_file = self.log_dir / f"{workload_id.replace('.', '_')}.jsonl"

        if not log_file.exists():
            return

        with open(log_file, 'r') as f:
            for line in f:
                if not line.strip():
                    continue

                record = json.loads(line)
                timestamp = record.get('timestamp')

                # Apply timestamp filters
                if start_timestamp and timestamp < start_timestamp:
                    continue
                if end_timestamp and timestamp > end_timestamp:
                    continue

                yield record

    def load_records(
        self,
        workload_id: str,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Load flywheel records into memory.

        Args:
            workload_id: Workload identifier
            start_timestamp: Optional start timestamp
            end_timestamp: Optional end timestamp
            limit: Optional limit on number of records

        Returns:
            List of flywheel records
        """
        records = list(self.iter_records(
            workload_id,
            start_timestamp,
            end_timestamp
        ))

        if limit:
            records = records[-limit:]

        return records

    def get_outcome_distribution(
        self,
        workload_id: str,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Get distribution of outcomes for a workload.

        Args:
            workload_id: Workload identifier
            start_timestamp: Optional start timestamp
            end_timestamp: Optional end timestamp

        Returns:
            Dictionary of outcome counts
        """
        outcomes = {}

        for record in self.iter_records(workload_id, start_timestamp, end_timestamp):
            outcome = record.get('metadata', {}).get('outcome', 'unknown')
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

        return outcomes

    def get_latency_stats(
        self,
        workload_id: str,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> Dict[str, float]:
        """
        Calculate latency statistics for a workload.

        Args:
            workload_id: Workload identifier
            start_timestamp: Optional start timestamp
            end_timestamp: Optional end timestamp

        Returns:
            Latency statistics (min, max, avg, p50, p95, p99)
        """
        latencies = []

        for record in self.iter_records(workload_id, start_timestamp, end_timestamp):
            latency = record.get('metadata', {}).get('latency_ms')
            if latency is not None:
                latencies.append(latency)

        if not latencies:
            return {}

        latencies.sort()

        def percentile(data, p):
            k = (len(data) - 1) * (p / 100)
            f = int(k)
            c = f + 1 if c < len(data) else f
            return data[f] + (data[c] - data[f]) * (k - f) if f < len(data) else data[f]

        return {
            'min': min(latencies),
            'max': max(latencies),
            'avg': sum(latencies) / len(latencies),
            'p50': percentile(latencies, 50),
            'p95': percentile(latencies, 95),
            'p99': percentile(latencies, 99),
            'count': len(latencies)
        }

    def export_for_training(
        self,
        workload_id: str,
        output_file: str,
        outcome_filter: Optional[List[str]] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> int:
        """
        Export flywheel logs for LLM training.

        Args:
            workload_id: Workload identifier
            output_file: Output JSONL file path
            outcome_filter: Optional list of outcomes to include (e.g., ['success'])
            start_timestamp: Optional start timestamp
            end_timestamp: Optional end timestamp

        Returns:
            Number of records exported
        """
        count = 0

        with open(output_file, 'w') as f:
            for record in self.iter_records(workload_id, start_timestamp, end_timestamp):
                # Apply outcome filter
                if outcome_filter:
                    outcome = record.get('metadata', {}).get('outcome')
                    if outcome not in outcome_filter:
                        continue

                # Write OpenAI-compatible format
                training_record = {
                    'messages': record['request']['messages'] + [
                        record['response']['choices'][0]['message']
                    ]
                }

                f.write(json.dumps(training_record) + '\n')
                count += 1

        return count
