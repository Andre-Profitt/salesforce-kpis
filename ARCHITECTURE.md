# Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Salesforce                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐                  │
│  │  Leads   │  │  Tasks   │  │ EmailMessage │                  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘                  │
│       │             │                │                           │
│       └─────────────┴────────────────┘                           │
│                     │                                            │
│            ┌────────▼─────────┐                                 │
│            │ Change Data      │                                 │
│            │ Capture (CDC)    │                                 │
│            └────────┬─────────┘                                 │
└─────────────────────┼──────────────────────────────────────────┘
                      │
                      │ Events (CometD/Pub-Sub API)
                      │
         ┌────────────▼────────────┐
         │                         │
         │   CDC Event Listener    │
         │   (or Polling Service)  │
         │                         │
         └────────────┬────────────┘
                      │
          ┌───────────┴───────────┐
          │                       │
     ┌────▼─────┐          ┌─────▼────┐
     │ Lead     │          │  Task/   │
     │ Events   │          │  Email   │
     │          │          │  Events  │
     └────┬─────┘          └─────┬────┘
          │                      │
          │                      │
┌─────────▼────────┐    ┌────────▼──────────┐
│                  │    │                   │
│  Agent Workloads │    │  Agent Workloads  │
│                  │    │                   │
│  ┌────────────┐  │    │ ┌──────────────┐  │
│  │ lead.route │  │    │ │ first_touch_ │  │
│  │            │  │    │ │ detect       │  │
│  └─────┬──────┘  │    │ └──────┬───────┘  │
│        │         │    │        │          │
│  ┌─────▼──────┐  │    │ ┌──────▼───────┐  │
│  │ outreach.  │  │    │ │ TTFR calc    │  │
│  │ template_  │  │    │ │              │  │
│  │ suggest    │  │    │ └──────────────┘  │
│  └────────────┘  │    │                   │
└────────┬─────────┘    └───────────────────┘
         │
         │
    ┌────▼─────────────┐
    │                  │
    │  Flywheel Logger │
    │                  │
    │  ┌────────────┐  │
    │  │ JSONL Logs │  │
    │  └────────────┘  │
    │                  │
    └──────────────────┘
         │
         │
    ┌────▼──────────────┐
    │                   │
    │ Metrics Extractor │
    │                   │
    │  ┌─────────────┐  │
    │  │ Dashboards  │  │
    │  │ CSV/JSON    │  │
    │  └─────────────┘  │
    │                   │
    └───────────────────┘
```

## Component Details

### 1. CDC Event Listener

**Purpose**: Subscribe to Salesforce change events in real-time

**Implementation Options**:
- **CometD** (long-polling): `src/listeners/cdc_listener.py:CDCListener`
- **Polling** (fallback): `src/listeners/cdc_listener.py:PollingListener`

**Events Subscribed**:
- `/data/LeadChangeEvent` - New lead creation, updates
- `/data/TaskChangeEvent` - Task completion (first response indicator)
- `/data/EmailMessageChangeEvent` - Email sends (Enhanced Email)

### 2. Agent Workloads

#### 2.1 Lead Routing (`lead.route`)

**File**: `src/workloads/lead_route.py`

**Trigger**: New lead creation (CREATE event)

**Process**:
1. Extract lead features (company, country, employee count, product interest)
2. Apply rule-based routing (segment by employee count, region by country)
3. Validate/refine with LLM (Claude Sonnet)
4. Assign lead owner via PATCH to `Lead.OwnerId`
5. Log decision to flywheel

**Output**:
```json
{
  "segment": "MM",
  "region": "EMEA",
  "owner": "005xx0000012345",
  "reason": "Mid-market company in UK",
  "confidence": 0.92
}
```

#### 2.2 First Touch Detection (`lead.first_touch_detect`)

**File**: `src/workloads/first_touch_detect.py`

**Trigger**:
- Task completion event (WhoId = Lead)
- Email send event (RelatedToId = Lead)

**Process**:
1. Query earliest Task or EmailMessage for lead
2. Calculate TTFR (minutes from lead creation)
3. Update Lead custom fields:
   - `First_Response_At__c`
   - `First_Response_User__c`
   - `Time_to_First_Response__c`
4. Log to flywheel

**SOQL Examples**:
```sql
-- Earliest Task
SELECT Id, CreatedDate, OwnerId
FROM Task
WHERE WhoId = '00Qxx...'
  AND Status = 'Completed'
  AND Type IN ('Call','Email','Meeting')
ORDER BY CreatedDate ASC
LIMIT 1

-- Earliest Email (Enhanced Email)
SELECT Id, MessageDate, CreatedById
FROM EmailMessage
WHERE RelatedToId = '00Qxx...'
ORDER BY MessageDate ASC
LIMIT 1
```

#### 2.3 Outreach Template Suggestion (`outreach.template_suggest`)

**File**: `src/workloads/template_suggest.py`

**Trigger**: New lead creation (or manual invocation)

**Process**:
1. Extract lead context (description, product interest, industry)
2. Use LLM to select best template and detect intent
3. Fill template variables with lead data
4. Optionally send email via Salesforce Simple Email Action
5. Log to flywheel

**Template Selection**:
```python
# Input: Lead description + context
# LLM Output:
{
  "template_id": "pricing_inquiry",
  "intent_detected": "pricing",
  "confidence": 0.88,
  "variable_suggestions": {
    "product": "Enterprise Analytics",
    "benefit": "faster decision-making"
  }
}
```

### 3. Flywheel Logger

**File**: `src/flywheel/logger.py`

**Purpose**: Capture all agent decisions for continuous optimization

**Format**: JSONL (one decision per line)

**Log Entry Structure**:
```json
{
  "timestamp": "2025-11-01T12:34:56.789Z",
  "client_id": "salesforce-prod",
  "workload_id": "lead.route",
  "request": {
    "messages": [{
      "role": "user",
      "content": "Lead: acme.com; 420 employees; UK; product=DataHub"
    }],
    "model": "claude-3-5-sonnet-20241022"
  },
  "response": {
    "choices": [{
      "message": {
        "content": "{\"segment\":\"MM\",\"region\":\"EMEA\",\"owner\":\"005xx...\"}"
      }
    }]
  },
  "metadata": {
    "lead_id": "00Qxx...",
    "assigned_to": "005xx..."
  }
}
```

**Log Files**:
- `logs/flywheel/lead.route_2025-11-01.jsonl`
- `logs/flywheel/lead.first_touch_detect_2025-11-01.jsonl`
- `logs/flywheel/outreach.template_suggest_2025-11-01.jsonl`

### 4. Metrics Extractor

**File**: `src/analytics/extract_metrics.py`

**Purpose**: Analyze flywheel logs and Salesforce data for KPIs

**Metrics Tracked**:

#### Routing Quality
- Total leads routed
- Distribution by segment/region
- Model confidence scores
- Assignment latency (median, P95)

#### TTFR (Time to First Response)
- TTFR median, P95, max
- SLA breach rate (>60 min)
- Distribution (0-15, 15-30, 30-60, 60+ minutes)
- By owner/region breakdown

#### Template Recommendations
- Template usage frequency
- Intent detection accuracy
- Confidence scores
- Email send success rate

**Output Files**:
- `reports/dashboard_20251101.json` - Complete metrics
- `reports/routing_metrics_20251101.csv` - Routing decisions
- `reports/ttfr_metrics_20251101.csv` - Response times
- `reports/template_metrics_20251101.csv` - Template usage

## Data Flow

### New Lead Flow

```
1. Sales rep creates Lead in Salesforce
   ↓
2. CDC emits LeadChangeEvent (CREATE)
   ↓
3. CDC Listener receives event
   ↓
4. Event handler calls lead.route workload
   ↓
5. LeadRouter extracts features, calls LLM
   ↓
6. Decision logged to flywheel
   ↓
7. Lead.OwnerId updated via REST API
   ↓
8. Template suggester suggests outreach email
   ↓
9. Suggestion logged to flywheel
```

### First Response Flow

```
1. SDR sends email or completes call task
   ↓
2. CDC emits TaskChangeEvent or EmailMessageChangeEvent
   ↓
3. CDC Listener receives event
   ↓
4. Event handler calls first_touch_detect workload
   ↓
5. FirstTouchDetector queries for first response
   ↓
6. Calculates TTFR (minutes)
   ↓
7. Detection logged to flywheel
   ↓
8. Lead custom fields updated via REST API
   - First_Response_At__c
   - First_Response_User__c
   - Time_to_First_Response__c
```

## Authentication Flow

```
1. Load private key from file
   ↓
2. Create JWT assertion
   - iss: Client ID
   - sub: Username
   - aud: Instance URL
   - exp: Current time + 1 hour
   ↓
3. Sign JWT with RS256
   ↓
4. POST to /services/oauth2/token
   - grant_type: urn:ietf:params:oauth:grant-type:jwt-bearer
   - assertion: <signed JWT>
   ↓
5. Receive access_token
   ↓
6. Cache token (expires in 1 hour)
   ↓
7. Use in Authorization: Bearer <token> header
```

## Configuration

### Routing Policy (`config/routing_policy.json`)

Defines:
- Segment thresholds (employee count ranges)
- Region mappings (country → region)
- Owner assignments (segment_region → User/Queue ID)
- Business rules (priority industries, validation requirements)

### Templates (`config/templates.json`)

Defines:
- Template metadata (ID, name, intent)
- Subject line with variables
- Email body with variables
- Variable list for substitution

## Scalability Considerations

### Current Implementation
- Synchronous event processing
- Single-threaded workload execution
- File-based flywheel logs

### Production Optimizations
1. **Async processing**: Use asyncio for concurrent workload execution
2. **Queue-based architecture**: RabbitMQ/SQS between listener and workloads
3. **Distributed logging**: Send flywheel logs to S3/GCS
4. **Horizontal scaling**: Multiple listener instances with load balancing
5. **Caching**: Redis for lead data and routing decisions
6. **Batch processing**: Aggregate updates to reduce API calls

## Monitoring

### Health Checks
- CDC connection status
- Authentication token validity
- Workload execution success rates
- API rate limit usage

### Alerts
- CDC disconnection
- Authentication failures
- High TTFR (>60 min for Enterprise)
- Low routing confidence (<0.5)
- Template suggestion failures

### Dashboards
- Leads routed per hour/day
- TTFR trend (median, P95)
- Template usage distribution
- Model confidence over time
