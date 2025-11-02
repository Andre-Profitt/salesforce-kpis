# Salesforce Metadata - KPIs & Observability

This directory contains Salesforce metadata for production-grade KPI tracking.

## Contents

### Custom Fields (Lead Object)

1. **First_Response_At__c** (DateTime)
   - Timestamp of first response to lead
   - Populated idempotently by FirstTouchDetector
   - Only updates if new response is earlier

2. **First_Response_User__c** (Text, 255)
   - User ID or email of first responder
   - For Tasks: OwnerId
   - For EmailMessages: FromAddress

3. **First_Response_Source__c** (Picklist)
   - Source of first response
   - Values: Task, EmailMessage
   - Tracks which channel is fastest

4. **Time_to_First_Response__c** (Number)
   - TTFR in minutes
   - Formula: (First_Response_At__c - CreatedDate) / 60000
   - Key SLA metric

5. **Owner_Assigned_At__c** (DateTime)
   - When lead assigned to user (not queue)
   - Populated by routing workload

6. **Assignment_Latency_Minutes__c** (Number)
   - Time from creation to assignment
   - Formula: (Owner_Assigned_At__c - CreatedDate) / 60000
   - Measures queue wait time

### Reports

**Lead_TTFR.report-meta.xml**
- Summary report with grouping by date and source
- Aggregates: Average TTFR, Median TTFR
- Filters: Last 30 days, has first response
- Columns: Lead details, TTFR, source, user

### Dashboards

**Sales_Operations_KPIs.dashboard-meta.xml**
- 5 components:
  1. Avg TTFR metric (with thresholds)
  2. Median TTFR metric
  3. Leads responded count
  4. TTFR trend line chart
  5. Response source donut chart

## Deployment

### Prerequisites

- Salesforce CLI (sfdx) installed
- Authenticated to target org
- Enhanced Email enabled (for EmailMessage)

### Deploy to Org

```bash
# Authenticate to org (if not already)
sfdx auth:web:login -a production

# Deploy all metadata
cd sf
sfdx force:source:deploy -p force-app -u production

# Verify deployment
sfdx force:source:deploy:report --jobid <JOB_ID>
```

### Deploy Individual Components

```bash
# Deploy only fields
sfdx force:source:deploy -p force-app/main/default/objects/Lead/fields -u production

# Deploy only reports
sfdx force:source:deploy -p force-app/main/default/reports -u production

# Deploy only dashboard
sfdx force:source:deploy -p force-app/main/default/dashboards -u production
```

### Retrieve Existing Metadata

```bash
# Retrieve Lead fields
sfdx force:source:retrieve -m CustomField:Lead.First_Response_At__c -u production

# Retrieve report
sfdx force:source:retrieve -m Report:SalesOpsKPIs/Lead_TTFR -u production
```

## Post-Deployment

### 1. Set Field-Level Security

Grant read/write access to fields for relevant profiles:
- System Administrator (all fields)
- Sales Operations (all fields)
- Sales Rep (read-only on TTFR fields)

```bash
# Example: Grant access via CLI
sfdx force:user:permset:assign -n SalesOpsKPIAccess -u admin@example.com
```

### 2. Add Fields to Page Layouts

Add custom fields to Lead page layouts:
- Detail page: Add "Response Metrics" section
- List views: Add TTFR and Assignment Latency columns
- Related lists: Show First Response fields on Task/Email

### 3. Configure Dashboard

- Update dashboard running user (line 110)
- Share dashboard with Sales Ops team
- Add to Sales app navigation

### 4. Create Formula Fields (Optional)

**TTFR_SLA_Met__c** (Formula - Checkbox)
```
Time_to_First_Response__c <= 60
```

**Assignment_SLA_Met__c** (Formula - Checkbox)
```
Assignment_Latency_Minutes__c <= 30
```

### 5. Set Up Alerts (Optional)

Create workflow rules or flows for:
- Email alert when TTFR > 4 hours
- Notification when lead unassigned > 30 minutes

## Integration with Python App

The Python application (app/workloads/first_touch.py) automatically:
1. Detects first response from Task or EmailMessage
2. Compares timestamps to find earliest
3. Updates all 4 TTFR fields atomically
4. Only writes if new response is earlier (idempotent)

Example field update:
```python
sf.update_record('Lead', lead_id, {
    'First_Response_At__c': '2025-01-15T10:30:00.000Z',
    'First_Response_User__c': '005xx0000012345',
    'First_Response_Source__c': 'Task',
    'Time_to_First_Response__c': 45
})
```

## Metrics Collection

These fields enable:
- **Prometheus metrics**: first_response_latency_seconds histogram
- **Salesforce reports**: Native TTFR analysis
- **Dashboards**: Real-time KPI visibility
- **Flywheel logs**: Decision history for LLM training

## Troubleshooting

### Deployment Errors

**Error: "Field already exists"**
- Field may exist with different metadata
- Use `sfdx force:source:retrieve` to compare
- Update metadata to match existing field

**Error: "Enhanced Email not enabled"**
- EmailMessage requires Enhanced Email feature
- Enable in Setup > Email > Email Settings
- Or remove EmailMessage references

**Error: "Invalid report type"**
- Report folder may not exist
- Create folder: Setup > Reports > New Folder
- Name: "SalesOpsKPIs"

### Runtime Issues

**Fields not updating**
- Check Python app logs for errors
- Verify Salesforce credentials
- Ensure CDC events are arriving

**Dashboard shows no data**
- Verify leads have First_Response_At__c populated
- Check report filters (last 30 days)
- Run FirstTouchDetector manually to backfill

## Version History

- **v2.0.0** - Initial production release
  - 6 custom fields
  - 1 report
  - 1 dashboard
  - Idempotent TTFR detection
  - Policy-based routing

## Support

For issues or questions:
- Check app/workloads/first_touch.py for field population logic
- Review PR_STATUS.md for implementation details
- See ARCHITECTURE.md for system design
