#!/bin/bash

# WhatsApp Notification API Startup Script

echo "🚀 Starting WhatsApp Notification API Server"
echo "================================================"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "📦 Installing dependencies..."
    pip3 install -r requirements.txt
fi

# Start the API server
echo "🌐 Starting API server on http://localhost:5000"
echo "📊 Logs will be written to api_server.log"
echo "🛑 Press Ctrl+C to stop the server"
echo ""

python3 api_server.py
