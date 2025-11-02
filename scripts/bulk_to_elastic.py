#!/usr/bin/env python3
"""
Bulk load flywheel logs to Elasticsearch.

Reads JSONL flywheel logs and indexes them to Elasticsearch for
analysis with Kibana.

Usage:
    # Load all logs
    python scripts/bulk_to_elastic.py

    # Load specific workload
    python scripts/bulk_to_elastic.py --workload lead.route

    # Load with custom Elasticsearch host
    python scripts/bulk_to_elastic.py --host https://elasticsearch:9200

Environment:
    ES_HOST - Elasticsearch host (default: http://localhost:9200)
    ES_API_KEY - Optional Elasticsearch API key
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.flywheel.loaders.to_jsonl import FlywheelJSONLLoader
from app.flywheel.loaders.to_elastic import ElasticsearchLoader


def main():
    """Bulk load flywheel logs to Elasticsearch."""
    parser = argparse.ArgumentParser(
        description="Bulk load flywheel logs to Elasticsearch"
    )
    parser.add_argument(
        '--host',
        default=os.getenv('ES_HOST', 'http://localhost:9200'),
        help='Elasticsearch host (default: http://localhost:9200)'
    )
    parser.add_argument(
        '--api-key',
        default=os.getenv('ES_API_KEY'),
        help='Elasticsearch API key'
    )
    parser.add_argument(
        '--workload',
        help='Specific workload to load (default: all)'
    )
    parser.add_argument(
        '--log-dir',
        default='data/flywheel',
        help='Flywheel log directory (default: data/flywheel)'
    )
    parser.add_argument(
        '--create-template',
        action='store_true',
        help='Create index template before loading'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Batch size for bulk indexing (default: 500)'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Flywheel → Elasticsearch Bulk Loader")
    print("=" * 60)
    print(f"ES Host: {args.host}")
    print(f"Log Dir: {args.log_dir}")
    print(f"Workload: {args.workload or 'all'}")
    print("=" * 60)
    print()

    # Initialize loaders
    jsonl_loader = FlywheelJSONLLoader(log_dir=args.log_dir)

    es_loader = ElasticsearchLoader(
        hosts=[args.host],
        api_key=args.api_key
    )

    # Create template if requested
    if args.create_template:
        print("Creating index template...")
        es_loader.create_index_template()
        print("✅ Template created")
        print()

    # Get workloads to load
    if args.workload:
        workloads = [args.workload]
    else:
        workloads = jsonl_loader.list_workloads()

    if not workloads:
        print("❌ No flywheel logs found in", args.log_dir)
        return 1

    print(f"Found {len(workloads)} workload(s):")
    for wl in workloads:
        print(f"  - {wl}")
    print()

    # Load each workload
    total_indexed = 0
    total_errors = 0

    for workload_id in workloads:
        print(f"Loading {workload_id}...")

        # Load records
        records = jsonl_loader.load_records(workload_id)

        if not records:
            print(f"  ⚠️  No records found")
            continue

        print(f"  Found {len(records)} records")

        # Bulk index in batches
        for i in range(0, len(records), args.batch_size):
            batch = records[i:i + args.batch_size]

            result = es_loader.bulk_index(batch)

            total_indexed += result['indexed']
            total_errors += result['errors']

            print(f"  Batch {i // args.batch_size + 1}: "
                  f"+{result['indexed']} indexed, {result['errors']} errors")

        print(f"  ✅ {workload_id} complete")
        print()

    print("=" * 60)
    print("Load Complete")
    print("=" * 60)
    print(f"Total Indexed: {total_indexed}")
    print(f"Total Errors: {total_errors}")
    print()

    if total_errors > 0:
        print("⚠️  Some records failed to index")
        return 1

    print("✅ All records indexed successfully")
    print()
    print("Next steps:")
    print(f"  1. Open Kibana: {args.host.replace('9200', '5601')}")
    print("  2. Create index pattern: flywheel-*")
    print("  3. Explore in Discover tab")
    print("  4. Build dashboards for decision analysis")

    return 0


if __name__ == '__main__':
    sys.exit(main())
