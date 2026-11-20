#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  Docker Deployment"
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

# Check the frontend .env file
if [ ! -f "frontend/.env" ]; then
    echo "frontend/.env does not exist. Copying it from the example..."
    if [ -f "frontend/.env.example" ]; then
        cp frontend/.env.example frontend/.env
        echo "✓ Created the frontend/.env file"
    else
        echo "⚠  frontend/.env.example does not exist. Please create frontend/.env manually"
    fi
else
    echo "✓ frontend/.env file exists"
fi
echo ""
# Initialize the Docker environment
echo "Initializing the Docker environment..."
make docker-init
echo ""

# Start Docker services
echo "Starting Docker services..."
make docker-start
echo ""

echo "=========================================="
echo "  Deployment Complete"
echo "=========================================="
echo ""
echo "🌐 Access URL: http://localhost:2026"
echo "📋 View logs: make docker-logs"
echo "🛑 Stop services: make docker-stop"
