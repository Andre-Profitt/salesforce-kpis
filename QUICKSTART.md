# Quick Start Guide

Get the Salesforce Flywheel Integration running in 15 minutes.

## Prerequisites

- Python 3.8+
- Salesforce org with API access
- Anthropic API key (for Claude)

## 1. Clone and Setup (5 minutes)

```bash
cd salesforce-kpis

# Run setup script
./setup.sh

# Activate virtual environment
source venv/bin/activate
```

## 2. Generate JWT Keys (2 minutes)

```bash
# Generate private key
openssl genrsa -out private.key 2048

# Generate certificate
openssl req -new -x509 -key private.key -out public.crt -days 365

# Secure the private key
chmod 600 private.key
```

## 3. Configure Salesforce (5 minutes)

### Create Connected App

1. Go to **Setup → App Manager → New Connected App**
2. Fill in:
   - Name: `Flywheel Integration`
   - Email: your-email@company.com
3. Enable OAuth:
   - ✅ Enable OAuth Settings
   - Callback: `https://login.salesforce.com/services/oauth2/callback`
   - Scopes: Select `api`, `refresh_token`, and `id`
   - ✅ Use digital signatures → Upload `public.crt`
4. Save and copy **Consumer Key**

### Enable Change Data Capture

1. Go to **Setup → Change Data Capture**
2. Select: Lead, Task, EmailMessage
3. Save

### Create Custom Fields on Lead

Navigate to **Setup → Object Manager → Lead → Fields**:

1. **First_Response_At__c** - Date/Time
2. **First_Response_User__c** - Lookup(User)
3. **Time_to_First_Response__c** - Number(10,2)

## 4. Configure Environment (2 minutes)

Edit `.env`:

```bash
# Salesforce
SF_INSTANCE_URL=https://yourorg.my.salesforce.com
SF_CLIENT_ID=3MVG9...your_consumer_key
SF_USERNAME=integration.user@yourorg.com
SF_PRIVATE_KEY_PATH=/path/to/private.key

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...your_key

# Flywheel
FLYWHEEL_CLIENT_ID=salesforce-prod
```

## 5. Test Installation (1 minute)

```bash
# Test authentication
python -c "from src.auth.jwt_auth import create_auth_from_env; auth = create_auth_from_env(); print('✓ Token:', auth.get_access_token()[:20])"

# Test API client
python -c "from src.auth.jwt_auth import create_auth_from_env; from src.salesforce.api_client import SalesforceAPIClient; auth = create_auth_from_env(); client = SalesforceAPIClient(auth); print('✓ API works')"
```

## 6. Run the Integration

### Option A: CDC Mode (Real-time)

```bash
python src/main.py
```

### Option B: Polling Mode (Fallback)

```bash
python src/main.py --polling
```

## Testing Individual Components

### Test Lead Routing

```bash
# Replace with a real Lead ID from your org
python src/workloads/lead_route.py 00Q5e000001AbcD
```

### Test First Touch Detection

```bash
python src/workloads/first_touch_detect.py 00Q5e000001AbcD
```

### Test Template Suggestion

```bash
python src/workloads/template_suggest.py 00Q5e000001AbcD
```

### Backfill Historical Data

```bash
# Backfill TTFR for last 30 days
python src/workloads/first_touch_detect.py --backfill 30
```

### Generate Metrics

```bash
# Generate dashboard for last 30 days
python src/analytics/extract_metrics.py 30

# View results
cat reports/dashboard_*.json
```

## Verify It's Working

### 1. Create a Test Lead in Salesforce

```
Company: Acme Corp
Country: US
Employees: 500
Description: Interested in pricing for your analytics platform
```

### 2. Check Logs

```bash
# Application logs
tail -f logs/app.log

# Flywheel decision logs
tail -f logs/flywheel/lead.route_*.jsonl
```

### 3. Verify in Salesforce

- Lead should be assigned to owner (check `OwnerId`)
- Complete a Task on the lead
- Check custom fields populated:
  - `First_Response_At__c`
  - `First_Response_User__c`
  - `Time_to_First_Response__c`

## Common Issues

### "Authentication failed"

- Verify Connected App Consumer Key is correct
- Check that integration user is pre-authorized in Connected App
- Ensure private key matches uploaded certificate

### "CDC not receiving events"

- Verify CDC is enabled for Lead, Task, EmailMessage
- Check API usage limits (Setup → System Overview)
- Try polling mode: `python src/main.py --polling`

### "Module not found"

```bash
# Ensure venv is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

## Next Steps

1. **Customize routing**: Edit `config/routing_policy.json` with your owner IDs
2. **Customize templates**: Edit `config/templates.json` with your messaging
3. **Set up monitoring**: Configure alerts for TTFR SLA breaches
4. **Schedule reports**: Add cron job for daily metrics

```bash
# Example cron for daily reports at 9 AM
0 9 * * * cd /path/to/salesforce-kpis && venv/bin/python src/analytics/extract_metrics.py 7 >> logs/metrics.log 2>&1
```

## Production Deployment

See [SETUP.md](SETUP.md) for:
- systemd service configuration
- Monitoring and alerting setup
- Scaling considerations
- Security best practices

## Support

- Review logs: `logs/app.log`
- Check flywheel decisions: `logs/flywheel/*.jsonl`
- Test with sandbox first
- Verify Salesforce permissions and API limits

---

**You're ready!** The integration will now automatically route new leads, track first responses, and suggest templates in real-time.
