#!/bin/bash

# Salesforce Flywheel Integration Setup Script

set -e

echo "====================================="
echo "Salesforce Flywheel Integration Setup"
echo "====================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Error: Python 3 is required"; exit 1; }

# Create virtual environment
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Dependencies installed"

# Create directories
echo "Creating directories..."
mkdir -p logs/flywheel
mkdir -p reports
mkdir -p config
echo "✓ Directories created"

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Creating .env from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your Salesforce credentials"
else
    echo "✓ .env file exists"
fi

# Check for JWT keys
echo ""
echo "Checking for JWT keys..."
if [ -z "$SF_PRIVATE_KEY_PATH" ]; then
    echo "⚠️  JWT keys not configured"
    echo ""
    echo "To generate JWT keys:"
    echo "  1. openssl genrsa -out private.key 2048"
    echo "  2. openssl req -new -x509 -key private.key -out public.crt -days 365"
    echo "  3. Store private.key securely (e.g., ~/.ssh/salesforce-private.key)"
    echo "  4. Upload public.crt to your Salesforce Connected App"
    echo ""
else
    if [ -f "$SF_PRIVATE_KEY_PATH" ]; then
        echo "✓ Private key found at $SF_PRIVATE_KEY_PATH"
    else
        echo "⚠️  Private key not found at $SF_PRIVATE_KEY_PATH"
    fi
fi

# Test import
echo ""
echo "Testing module imports..."
python -c "from src.auth.jwt_auth import SalesforceJWTAuth; print('✓ Auth module loaded')" || echo "⚠️  Import failed"
python -c "from src.salesforce.api_client import SalesforceAPIClient; print('✓ API client module loaded')" || echo "⚠️  Import failed"
python -c "from src.flywheel.logger import FlywheelLogger; print('✓ Flywheel logger module loaded')" || echo "⚠️  Import failed"

echo ""
echo "====================================="
echo "Setup Complete!"
echo "====================================="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your Salesforce credentials"
echo "  2. Generate and configure JWT keys (see SETUP.md)"
echo "  3. Configure Salesforce (Connected App, CDC, Custom Fields)"
echo "  4. Test with: python src/workloads/lead_route.py <lead_id>"
echo "  5. Start listener: python src/main.py"
echo ""
echo "For detailed setup instructions, see SETUP.md"
echo ""
