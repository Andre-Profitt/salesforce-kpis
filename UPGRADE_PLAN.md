# Production Upgrade Plan - v2.0

This document tracks the upgrade from POC (v1.0) to production-ready architecture (v2.0).

## Status: IN PROGRESS

Started: 2025-11-01
Target Completion: TBD

## Overview

Upgrading salesforce-kpis with:
- Pub/Sub CDC with replay persistence
- Idempotent TTFR detection
- Policy-as-data with versioning
- Flywheel log contract (Pydantic schema)
- Prometheus metrics + health endpoints
- Salesforce-native observability (custom fields, reports, dashboards)
- Comprehensive test suite
- GitHub Actions CI/CD

## Architecture Changes

### Old (v1.0)
```
src/
├── auth/jwt_auth.py         # Basic JWT
├── listeners/cdc_listener.py # CometD polling
├── workloads/               # Basic workloads
├── flywheel/logger.py       # Unstructured logs
└── main.py                  # Simple entry point
```

### New (v2.0)
```
app/
├── auth/jwt.py              # JWT with caching + metrics
├── cdc/
│   ├── subscriber.py        # Pub/Sub with replay
│   ├── replay_store.py      # Persistent replay IDs
│   └── fixtures/            # Test fixtures
├── workloads/
│   ├── lead_route.py        # With assignment latency
│   ├── first_touch.py       # Idempotent TTFR
│   └── outreach_templates.py
├── flywheel/
│   ├── schema.py            # Pydantic contract
│   ├── emitter.py           # Structured emitter
│   └── loaders/             # JSONL + Elasticsearch
├── policies/
│   ├── routing_policy.json  # Versioned policy
│   └── policy.schema.json   # JSON Schema
├── web/
│   ├── server.py            # FastAPI app
│   ├── metrics.py           # Prometheus
│   └── logging.py           # Structured logs
└── config.py                # Pydantic config

sf/                          # Salesforce metadata
├── force-app/main/default/
│   ├── objects/Lead/fields/ # Custom fields
│   ├── reports/             # KPI reports
│   └── dashboards/          # Dashboards

scripts/                     # Utility scripts
tests/                       # Comprehensive tests
.github/workflows/ci.yml     # CI/CD
```

## Task List

### ✅ Completed

1. **Project restructuring**
   - Created `app/` directory structure
   - Created `sf/` for Salesforce metadata
   - Created `scripts/` for utilities

2. **Configuration (app/config.py)**
   - Pydantic-based config
   - Environment variable loading
   - Separate configs for SF, CDC, Flywheel, Metrics

3. **JWT Auth (app/auth/jwt.py)**
   - Token caching with 60s buffer
   - Prometheus metrics (auth_requests, auth_latency)
   - Proper error handling
   - Logging

4. **Replay Store (app/cdc/replay_store.py)**
   - Thread-safe JSON storage
   - Per-channel replay ID persistence
   - Clear/reset functionality

5. **CDC Fixtures**
   - `app/cdc/fixtures/lead_create.json`
   - `app/cdc/fixtures/task_complete.json`
   - `app/cdc/fixtures/emailmessage.json`

6. **Flywheel Schema (app/flywheel/schema.py)**
   - Pydantic models (Message, Request, Response, FlywheelRecord)
   - OpenAI-compatible format
   - Validation helpers
   - Example data

### 🚧 In Progress

7. **CDC Subscriber (app/cdc/subscriber.py)**
   - [ ] Pub/Sub gRPC client
   - [ ] Replay resumption
   - [ ] Backfill fallback
   - [ ] Event routing to workloads
   - [ ] Metrics (cdc_events_total, cdc_lag_seconds)

### 📋 Pending

8. **Flywheel Emitter (app/flywheel/emitter.py)**
   - [ ] JSONL writer with schema validation
   - [ ] Batch writing
   - [ ] Rotation by date/size
   - [ ] Metrics

9. **Flywheel Loaders**
   - [ ] `app/flywheel/loaders/to_jsonl.py`
   - [ ] `app/flywheel/loaders/to_elastic.py` (Elasticsearch bulk)

10. **Policy System**
    - [ ] `app/policies/routing_policy.json` (v2 with versioning)
    - [ ] `app/policies/policy.schema.json` (JSON Schema)
    - [ ] `app/policies/load.py` (Pydantic loader with validation)
    - [ ] Version stamping in decisions

11. **Idempotent TTFR (app/workloads/first_touch.py)**
    - [ ] Strict ordering (EmailMessage vs Task)
    - [ ] Only write if earlier than existing
    - [ ] Set all 4 fields (At, User, Source, Minutes)
    - [ ] Metrics (first_response_latency_seconds)

12. **Lead Routing v2 (app/workloads/lead_route.py)**
    - [ ] Assignment latency tracking
    - [ ] Set Owner_Assigned_At__c
    - [ ] Compute Assignment_Latency_Minutes__c
    - [ ] Metrics (assignment_latency_seconds)

13. **Outreach Templates v2 (app/workloads/outreach_templates.py)**
    - [ ] Template metadata (id, intent, variables)
    - [ ] LLM selection
    - [ ] Variable filling
    - [ ] Optional email send
    - [ ] Set Template_Recommended__c, Template_Applied__c

14. **Prometheus Metrics (app/web/metrics.py)**
    - [ ] Define all counters/histograms/gauges
    - [ ] cdc_events_total
    - [ ] cdc_lag_seconds
    - [ ] decisions_total
    - [ ] first_response_latency_seconds
    - [ ] assignment_latency_seconds
    - [ ] errors_total

15. **Health & Web Server (app/web/server.py)**
    - [ ] FastAPI app
    - [ ] `/healthz` endpoint
    - [ ] `/metrics` endpoint (Prometheus format)
    - [ ] Structured logging

16. **Salesforce Custom Fields**
    - [ ] First_Response_At__c.field-meta.xml
    - [ ] First_Response_User__c.field-meta.xml
    - [ ] First_Response_Source__c.field-meta.xml
    - [ ] Time_to_First_Response__c.field-meta.xml
    - [ ] Owner_Assigned_At__c.field-meta.xml
    - [ ] Assignment_Latency_Minutes__c.field-meta.xml
    - [ ] Template_Recommended__c.field-meta.xml
    - [ ] Template_Applied__c.field-meta.xml
    - [ ] sfdx-project.json

17. **Salesforce Reports**
    - [ ] Lead_TTFR.report-meta.xml (grouped by Owner)
    - [ ] Assignment_Latency.report-meta.xml
    - [ ] Template_Usage.report-meta.xml

18. **Salesforce Dashboard**
    - [ ] TTFR_and_Routing.dashboard-meta.xml
    - [ ] Components: TTFR by Owner, Assignment Latency, SLA Breach %

19. **Test Suite**
    - [ ] tests/test_jwt.py (auth caching, errors)
    - [ ] tests/test_cdc_replay.py (replay persistence)
    - [ ] tests/test_first_touch_idempotent.py (ordering, idempotency)
    - [ ] tests/test_lead_route_policy.py (policy versioning)
    - [ ] tests/test_flywheel_contract.py (schema validation)
    - [ ] Fixtures and mocks

20. **CI/CD**
    - [ ] .github/workflows/ci.yml
    - [ ] Black formatting check
    - [ ] Flake8 linting
    - [ ] Pytest with coverage
    - [ ] Auto-deploy on main (optional)

21. **Scripts**
    - [ ] scripts/seed_fixtures.py (load test data)
    - [ ] scripts/run_cdc_local.py (local testing)
    - [ ] scripts/bulk_to_elastic.py (flywheel export)

22. **Documentation**
    - [ ] Update README.md with v2 architecture
    - [ ] OBSERVABILITY.md (Prometheus, Salesforce reports)
    - [ ] DEPLOYMENT.md (production deployment)
    - [ ] Update QUICKSTART.md

23. **Updated requirements.txt**
    - [ ] Add FastAPI, uvicorn
    - [ ] Add prometheus_client
    - [ ] Add pydantic settings
    - [ ] Add elasticsearch (optional)

## Migration Path

### For Existing Users

1. **Backup current state**
   ```bash
   cp .env .env.backup
   cp -r logs/ logs.backup/
   ```

2. **Install new dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Deploy Salesforce metadata**
   ```bash
   cd sf
   sfdx force:source:deploy -p force-app/main/default/objects/Lead/fields
   ```

4. **Update configuration**
   - Review new .env.example
   - Add new config variables

5. **Test with fixtures**
   ```bash
   python scripts/run_cdc_local.py
   ```

6. **Deploy to production**
   ```bash
   # Start metrics server
   uvicorn app.web.server:app --port 8080 &

   # Start CDC subscriber
   python -m app.cdc.subscriber
   ```

## Breaking Changes

### v1.0 → v2.0

1. **Module paths changed**
   - `src/` → `app/`
   - Import paths need updating

2. **Configuration**
   - Now uses Pydantic models
   - Some env var names changed

3. **Flywheel logs**
   - New Pydantic schema
   - Old logs won't validate

4. **Metrics**
   - New Prometheus format
   - Need to update scrape configs

## Rollback Plan

If issues arise:

1. Revert to v1.0 commit
   ```bash
   git checkout v1.0
   ```

2. Restore config
   ```bash
   cp .env.backup .env
   ```

3. Restart services with old code

## Testing Checklist

Before production deployment:

- [ ] JWT auth works with token caching
- [ ] CDC subscriber receives events and persists replay IDs
- [ ] Replay resumption works after restart
- [ ] TTFR is idempotent (multiple events don't overwrite)
- [ ] Lead routing sets assignment latency correctly
- [ ] All Prometheus metrics are exposed
- [ ] /healthz returns correct status
- [ ] Flywheel logs validate against schema
- [ ] Salesforce fields are populated
- [ ] Reports and dashboards render
- [ ] All tests pass
- [ ] CI pipeline succeeds

## Performance Targets

- CDC event latency: <500ms p95
- Assignment latency: <5s p95
- TTFR detection: <1s p95
- Metrics endpoint: <100ms p95
- Token caching hit rate: >95%

## Monitoring

Post-deployment monitoring:

1. **Prometheus queries**
   ```promql
   rate(cdc_events_total[5m])
   histogram_quantile(0.95, rate(first_response_latency_seconds_bucket[5m]))
   sum(rate(errors_total[5m])) by (area)
   ```

2. **Salesforce reports**
   - Daily TTFR trend
   - Assignment latency by segment
   - Template usage distribution

3. **Logs**
   - Structured JSON logs
   - Error rate <0.1%
   - No auth failures

## Notes

- This is a significant refactoring (50+ files)
- Estimated effort: 3-5 days full-time
- Test thoroughly in sandbox first
- Monitor closely for first 48 hours post-deployment

## Questions / Decisions Needed

1. Use Pub/Sub gRPC or stick with CometD polling?
2. Elasticsearch required or optional for flywheel logs?
3. Custom SLA thresholds (currently 60 min default)?
4. Auto-email send or manual approval for templates?

---

Last Updated: 2025-11-01
Status: In Progress (25% complete)
