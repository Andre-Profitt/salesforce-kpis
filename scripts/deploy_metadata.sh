#!/bin/bash
# Deploy Salesforce metadata for KPI fields and reports
#
# Usage:
#   ./scripts/deploy_metadata.sh [org-alias]
#
# Examples:
#   ./scripts/deploy_metadata.sh production
#   ./scripts/deploy_metadata.sh sandbox
#
# Prerequisites:
#   - Salesforce CLI (sfdx) installed
#   - Authenticated to target org

set -e

ORG_ALIAS=${1:-production}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SF_DIR="$SCRIPT_DIR/../sf"

echo "========================================"
echo "Salesforce Metadata Deployment"
echo "========================================"
echo "Target Org: $ORG_ALIAS"
echo "Source Dir: $SF_DIR"
echo "========================================"
echo ""

# Check if sfdx is installed
if ! command -v sfdx &> /dev/null; then
    echo "❌ Error: Salesforce CLI (sfdx) not found"
    echo "Install from: https://developer.salesforce.com/tools/sfdxcli"
    exit 1
fi

# Check if org is authenticated
echo "📋 Checking authentication..."
if ! sfdx force:org:display -u "$ORG_ALIAS" &> /dev/null; then
    echo "❌ Error: Not authenticated to org '$ORG_ALIAS'"
    echo ""
    echo "Authenticate with:"
    echo "  sfdx auth:web:login -a $ORG_ALIAS"
    exit 1
fi

echo "✅ Authenticated to $ORG_ALIAS"
echo ""

# Display org info
echo "📊 Org Information:"
sfdx force:org:display -u "$ORG_ALIAS" --json | jq -r '.result | "  Username: \(.username)\n  Org ID: \(.id)\n  Instance: \(.instanceUrl)"'
echo ""

# Confirm deployment
read -p "Deploy metadata to this org? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Deployment cancelled"
    exit 0
fi

echo ""
echo "========================================"
echo "Starting Deployment"
echo "========================================"
echo ""

# Deploy metadata
echo "🚀 Deploying custom fields..."
sfdx force:source:deploy \
    -p "$SF_DIR/force-app/main/default/objects/Lead/fields" \
    -u "$ORG_ALIAS" \
    --loglevel warn

echo ""
echo "🚀 Deploying reports..."
sfdx force:source:deploy \
    -p "$SF_DIR/force-app/main/default/reports" \
    -u "$ORG_ALIAS" \
    --loglevel warn

echo ""
echo "🚀 Deploying dashboards..."
sfdx force:source:deploy \
    -p "$SF_DIR/force-app/main/default/dashboards" \
    -u "$ORG_ALIAS" \
    --loglevel warn

echo ""
echo "========================================"
echo "✅ Deployment Complete!"
echo "========================================"
echo ""

# Next steps
echo "📝 Next Steps:"
echo ""
echo "1. Set Field-Level Security:"
echo "   Setup > Object Manager > Lead > Fields > [field] > Set Field-Level Security"
echo ""
echo "2. Add Fields to Page Layout:"
echo "   Setup > Object Manager > Lead > Page Layouts > Lead Layout"
echo "   Add 'Response Metrics' section with custom fields"
echo ""
echo "3. Configure Dashboard:"
echo "   Setup > Dashboards > Sales Operations KPIs"
echo "   Update running user and share with team"
echo ""
echo "4. Test TTFR Detection:"
echo "   python scripts/run_cdc_local.py"
echo ""
echo "5. Verify in Salesforce:"
echo "   - Create a test lead"
echo "   - Complete a task or send email"
echo "   - Check First_Response_At__c is populated"
echo ""

# Show deployed components
echo "📦 Deployed Components:"
echo "  - 6 custom fields on Lead"
echo "  - 1 report (Lead TTFR Analysis)"
echo "  - 1 dashboard (Sales Operations KPIs)"
echo ""
