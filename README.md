# Salesforce Flywheel Integration POC

An intelligent agent system that integrates with Salesforce to optimize lead routing, track first-response times, and recommend personalized outreach templates.

## Features

- **Lead Routing**: Automatically route new Leads to the right owner/queue based on segment, region, and product interest
- **First Response Tracking**: Detect and measure time-to-first-response (TTFR) via Tasks and EmailMessages
- **Outreach Templates**: Suggest personalized email templates based on inbound inquiry context
- **Flywheel Optimization**: Log all decisions for continuous model improvement

## Architecture

```
Salesforce CDC Events → Event Listener → Agent Workloads → Salesforce REST API
                             ↓
                       Flywheel Logs
```

### Components

1. **Auth Service**: OAuth 2.0 JWT Bearer flow for server-to-server authentication
2. **CDC Listener**: Subscribes to LeadChangeEvent, TaskChangeEvent, EmailMessageChangeEvent
3. **Agent Workloads**:
   - `lead.route`: Assign leads to optimal owner/queue
   - `lead.first_touch_detect`: Track first response and calculate TTFR
   - `outreach.template_suggest`: Recommend email templates
4. **Salesforce API Client**: REST operations (PATCH, email send, queries)
5. **Flywheel Logger**: Capture all agent decisions for optimization

## Prerequisites

### Salesforce Setup

1. **Connected App** with OAuth 2.0 JWT Bearer flow
2. **Change Data Capture (CDC)** enabled for:
   - Lead
   - Task
   - EmailMessage
3. **Enhanced Email** enabled (stores emails as EmailMessage records)
4. **Custom Fields** on Lead:
   - `First_Response_At__c` (DateTime)
   - `First_Response_User__c` (Lookup to User)
   - `Time_to_First_Response__c` (Number - minutes)

### Environment Variables

```bash
SF_INSTANCE_URL=https://your-instance.salesforce.com
SF_CLIENT_ID=your_connected_app_client_id
SF_USERNAME=integration.user@yourorg.com
SF_PRIVATE_KEY_PATH=/path/to/private.key
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Salesforce credentials

# Run the listener
python src/main.py
```

## Usage

### Start the CDC Listener

```bash
python src/main.py
```

### Test Individual Workloads

```bash
# Test lead routing
python src/workloads/lead_route.py --lead-id 00Qxx000000xxxx

# Test TTFR detection
python src/workloads/first_touch_detect.py --lead-id 00Qxx000000xxxx

# Test template suggestion
python src/workloads/template_suggest.py --lead-id 00Qxx000000xxxx
```

### Extract Metrics

```bash
# Generate metrics dashboard
python src/analytics/extract_metrics.py --output-dir ./reports
```

## Metrics

- **Routing Quality**: Segment/region accuracy vs. policy; assignment latency
- **TTFR**: Median, P95, SLA breach rate (e.g., >60 minutes)
- **Template Recommendations**: LLM-judge scores, reply rates

## Project Structure

```
salesforce-kpis/
├── src/
│   ├── auth/              # JWT authentication
│   ├── listeners/         # CDC event subscribers
│   ├── workloads/         # Agent workloads
│   ├── salesforce/        # API clients
│   ├── flywheel/          # Logging system
│   ├── analytics/         # Metrics extraction
│   └── main.py           # Entry point
├── config/
│   ├── routing_policy.json
│   └── templates.json
├── tests/
├── requirements.txt
└── README.md
```

## Development

```bash
# Run tests
pytest

# Lint
flake8 src/

# Format
black src/
```

## License

MIT
