#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  Local Mode Deployment"
echo "=========================================="
echo ""

# Check config.yaml
if [ ! -f "config.yaml" ]; then
    echo "config.yaml does not exist. Generating it..."
    make config
    echo ""
    echo "⚠  Please edit config.yaml to configure your models and API keys"
    echo "  Then run this script again"
    exit 1
else
    echo "✓ config.yaml exists"
fi
echo ""

# Check the .env file
if [ ! -f ".env" ]; then
    echo ".env does not exist. Copying it from the example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✓ Created the .env file"
    else
        echo "⚠  .env.example does not exist. Please create the .env file manually"
    fi
else
    echo "✓ .env file exists"
fi
echo ""

# Check dependencies
echo "Checking dependencies..."
make check
echo ""

# Install dependencies
echo "Installing dependencies..."
make install
echo ""

# Start services
echo "Starting services (background mode)..."
make dev-daemon
echo ""

echo "=========================================="
echo "  Deployment Complete"
echo "=========================================="
echo ""
echo "🌐 Access URL: http://localhost:2026"
echo "📋 View logs:"
echo "   - logs/langgraph.log"
echo "   - logs/gateway.log"
echo "   - logs/frontend.log"
echo "   - logs/nginx.log"
echo "🛑 Stop services: make stop"
echo ""
echo "Please wait 90-120 seconds for all services to start completely, then run the health check"
