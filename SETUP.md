# Salesforce Flywheel Integration Setup Guide

Complete guide to configure and deploy the Salesforce Flywheel POC.

## Table of Contents

1. [Salesforce Configuration](#salesforce-configuration)
2. [Generate JWT Keys](#generate-jwt-keys)
3. [Create Connected App](#create-connected-app)
4. [Enable Change Data Capture](#enable-change-data-capture)
5. [Create Custom Fields](#create-custom-fields)
6. [Environment Setup](#environment-setup)
7. [Installation](#installation)
8. [Testing](#testing)
9. [Deployment](#deployment)

---

## 1. Salesforce Configuration

### Prerequisites

- Salesforce org with API access
- System Administrator permissions
- Enhanced Email enabled (Setup → Email → Deliverability → Enhanced Email)

### Enable Enhanced Email

1. Navigate to **Setup → Email → Deliverability**
2. Enable **Enhanced Email**
3. This stores emails as `EmailMessage` objects for easier tracking

---

## 2. Generate JWT Keys

Generate RSA key pair for OAuth JWT Bearer authentication:

```bash
# Generate private key
openssl genrsa -out private.key 2048

# Generate public certificate
openssl req -new -x509 -key private.key -out public.crt -days 365

# Store private key securely
chmod 600 private.key
mv private.key ~/.ssh/salesforce-private.key
```

**Important**: Never commit `private.key` to version control!

---

## 3. Create Connected App

### Steps

1. Navigate to **Setup → App Manager → New Connected App**

2. Configure basic settings:
   - **Connected App Name**: Flywheel Integration
   - **API Name**: Flywheel_Integration
   - **Contact Email**: your-email@company.com

3. Enable OAuth Settings:
   - ✅ **Enable OAuth Settings**
   - **Callback URL**: `https://login.salesforce.com/services/oauth2/callback`

4. Select OAuth Scopes:
   - Access and manage your data (api)
   - Perform requests on your behalf at any time (refresh_token, offline_access)
   - Access your basic information (id, profile, email, address, phone)

5. Configure JWT:
   - ✅ **Use digital signatures**
   - Upload `public.crt` generated in step 2

6. Save the Connected App

7. Note the **Consumer Key** (Client ID) - you'll need this

### Pre-authorize Integration User

1. Go to **Manage → Edit Policies**
2. Under **OAuth Policies**:
   - **Permitted Users**: Admin approved users are pre-authorized
   - **IP Relaxation**: Relax IP restrictions
3. Save

4. Go to **Manage → Manage Profiles** or **Permission Sets**
5. Add the integration user's profile/permission set

---

## 4. Enable Change Data Capture

### Option A: Via Setup UI

1. Navigate to **Setup → Integrations → Change Data Capture**
2. Select entities to track:
   - ✅ Lead
   - ✅ Task
   - ✅ EmailMessage
3. Click **Save**

### Option B: Via Metadata API

Deploy this package:

```xml
<!-- package.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>Lead</members>
        <members>Task</members>
        <members>EmailMessage</members>
        <name>ChangeDataCaptureDefinition</name>
    </types>
    <version>59.0</version>
</Package>
```

---

## 5. Create Custom Fields

Add these custom fields to the **Lead** object:

### Via Setup UI

1. Navigate to **Setup → Object Manager → Lead → Fields & Relationships**

2. Create **First_Response_At__c**:
   - **Data Type**: Date/Time
   - **Field Label**: First Response At
   - **Field Name**: First_Response_At
   - **Description**: Timestamp of first response to lead

3. Create **First_Response_User__c**:
   - **Data Type**: Lookup(User)
   - **Field Label**: First Response User
   - **Field Name**: First_Response_User
   - **Description**: User who made first response

4. Create **Time_to_First_Response__c**:
   - **Data Type**: Number(10, 2)
   - **Field Label**: Time to First Response (Minutes)
   - **Field Name**: Time_to_First_Response
   - **Description**: Minutes from lead creation to first response

5. Update **Page Layouts** to include these fields

### Via Metadata API

```bash
# Deploy custom fields using SF CLI
sf project deploy start --metadata-dir ./salesforce/fields
```

---

## 6. Environment Setup

### Create .env file

```bash
cp .env.example .env
```

### Configure environment variables

Edit `.env`:

```bash
# Salesforce Authentication
SF_INSTANCE_URL=https://your-domain.my.salesforce.com
SF_CLIENT_ID=your_connected_app_consumer_key
SF_USERNAME=integration.user@yourorg.com
SF_PRIVATE_KEY_PATH=/Users/you/.ssh/salesforce-private.key

# Salesforce API Version
SF_API_VERSION=59.0

# CDC Configuration
SF_CDC_REPLAY_ID=-1

# LLM Configuration
ANTHROPIC_API_KEY=your_anthropic_api_key
OPENAI_API_KEY=your_openai_api_key  # Optional

# Flywheel Configuration
FLYWHEEL_CLIENT_ID=salesforce-prod
FLYWHEEL_LOG_PATH=./logs/flywheel

# Application Settings
LOG_LEVEL=INFO
ENVIRONMENT=production
USE_POLLING=false  # Set to true if CDC is not available
POLL_INTERVAL=60   # Seconds between polls (if using polling mode)
```

---

## 7. Installation

### Install Python dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Verify installation

```bash
# Test authentication
python -c "from src.auth.jwt_auth import create_auth_from_env; auth = create_auth_from_env(); print('Token:', auth.get_access_token()[:20] + '...')"
```

---

## 8. Testing

### Test individual workloads

```bash
# Test lead routing
python src/workloads/lead_route.py 00Qxx000000xxxx

# Test first touch detection
python src/workloads/first_touch_detect.py 00Qxx000000xxxx

# Test template suggestion
python src/workloads/template_suggest.py 00Qxx000000xxxx

# Backfill first touch data (last 30 days)
python src/workloads/first_touch_detect.py --backfill 30
```

### Test metrics extraction

```bash
# Generate metrics dashboard
python src/analytics/extract_metrics.py 30 ./reports

# View output
cat reports/dashboard_*.json
```

---

## 9. Deployment

### Run the integration

```bash
# Start CDC listener
python src/main.py

# Or use polling mode (if CDC unavailable)
python src/main.py --polling
```

### Run as background service (systemd)

Create `/etc/systemd/system/salesforce-flywheel.service`:

```ini
[Unit]
Description=Salesforce Flywheel Integration
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/salesforce-kpis
Environment="PATH=/path/to/salesforce-kpis/venv/bin"
ExecStart=/path/to/salesforce-kpis/venv/bin/python src/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable salesforce-flywheel
sudo systemctl start salesforce-flywheel
sudo systemctl status salesforce-flywheel
```

### Monitor logs

```bash
# Structured JSON logs
tail -f logs/app.log

# Flywheel decision logs
tail -f logs/flywheel/lead.route_*.jsonl
tail -f logs/flywheel/lead.first_touch_detect_*.jsonl
tail -f logs/flywheel/outreach.template_suggest_*.jsonl
```

---

## Troubleshooting

### Authentication errors

```bash
# Verify Connected App settings
# Check that JWT certificate matches private key
openssl x509 -in public.crt -text

# Verify user is pre-authorized
# Check Setup → App Manager → Flywheel Integration → Manage → Manage Profiles
```

### CDC not receiving events

```bash
# Verify CDC is enabled
# Setup → Change Data Capture → verify Lead, Task, EmailMessage are selected

# Check API limits
# Setup → System Overview → API Usage

# Try polling mode as fallback
python src/main.py --polling
```

### Missing first touch data

```bash
# Run backfill script
python src/workloads/first_touch_detect.py --backfill 90

# Verify Enhanced Email is enabled
# Setup → Email → Deliverability
```

---

## Next Steps

1. **Customize routing policy**: Edit `config/routing_policy.json` with your segments, regions, and owner IDs
2. **Customize templates**: Edit `config/templates.json` with your email templates
3. **Set up monitoring**: Configure dashboards and alerts for KPIs
4. **Schedule reports**: Set up cron jobs to generate daily/weekly metrics
5. **Optimize models**: Use flywheel logs to train and improve routing/template models

---

## Support

For issues and questions:
- Check logs in `logs/` directory
- Review flywheel decision logs for model outputs
- Verify Salesforce API limits and permissions
- Test with sample leads in sandbox first
