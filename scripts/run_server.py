#!/usr/bin/env python3
"""
Run FastAPI metrics/health server.

Starts the web server that exposes:
- /metrics - Prometheus metrics
- /healthz - Health check
- /ready - Readiness probe
- /version - Version info

Usage:
    # Development (with auto-reload)
    python scripts/run_server.py --dev

    # Production
    python scripts/run_server.py

    # Custom port
    python scripts/run_server.py --port 9090

Environment Variables:
    LOG_LEVEL - Logging level (default: INFO)
    LOG_FORMAT - json or text (default: json)
    APP_VERSION - Application version (default: v2.0.0)
    ENVIRONMENT - Environment name (default: development)
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn


def main():
    """Run web server."""
    parser = argparse.ArgumentParser(description="Run Salesforce KPIs web server")
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='Port to bind to (default: 8080)'
    )
    parser.add_argument(
        '--dev',
        action='store_true',
        help='Run in development mode with auto-reload'
    )
    parser.add_argument(
        '--log-level',
        default='info',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        help='Log level (default: info)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Number of worker processes (default: 1)'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Salesforce KPIs Web Server")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Mode: {'Development' if args.dev else 'Production'}")
    print(f"Workers: {args.workers}")
    print("=" * 60)
    print()
    print("Endpoints:")
    print(f"  - http://{args.host}:{args.port}/")
    print(f"  - http://{args.host}:{args.port}/metrics")
    print(f"  - http://{args.host}:{args.port}/healthz")
    print(f"  - http://{args.host}:{args.port}/ready")
    print(f"  - http://{args.host}:{args.port}/version")
    print(f"  - http://{args.host}:{args.port}/docs")
    print("=" * 60)
    print()

    # Configure uvicorn
    config = {
        "app": "app.web.server:app",
        "host": args.host,
        "port": args.port,
        "log_level": args.log_level,
    }

    if args.dev:
        # Development mode
        config.update({
            "reload": True,
            "reload_dirs": ["app"],
        })
    else:
        # Production mode
        config.update({
            "workers": args.workers,
            "access_log": True,
        })

    # Start server
    uvicorn.run(**config)


if __name__ == '__main__':
    main()
