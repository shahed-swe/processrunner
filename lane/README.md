# PO Review System

This is a Purchase Order (PO) review and processing system that integrates with AI (OpenAI GPT) to analyze and process purchase orders from a MySQL database.

## What It Does

1. **Fetches Purchase Orders** from a MySQL database
2. **Uses AI (OpenAI GPT)** to analyze and review PO data
3. **Processes vendor communications** and tracks communication timeframes
4. **Sends API calls** based on GPT analysis results
5. **Manages workflow queues** to prevent duplicate processing

## Files

- **`po_review_main.py`** - Main orchestrator that runs the entire process
- **`po_database_operation.py`** - Handles all database operations (MySQL)
- **`po_gpt_operation.py`** - Manages OpenAI GPT interactions for PO analysis
- **`config.ini`** - Configuration for databases, API keys, email settings, etc.

## Installation

1. Install required dependencies:
```bash
pip install -r requirements.txt
```

## Running the System

### Option 1: Direct Command Line
```bash
# Run for all open POs
python3 po_review_main.py --config config.ini

# Run for specific WPQ
python3 po_review_main.py --config config.ini --WPQ WPQ123456

# Run with cleanup first
python3 po_review_main.py --config config.ini --cleanup

# Set text limit for GPT responses
python3 po_review_main.py --config config.ini --text-limit 1500
```

### Option 2: Via API (Recommended)

The PO review system is integrated into the WhatsApp API server. To use the API:

1. **Start the combined API server:**
```bash
cd ../whatsapp
./start_api.sh
```

2. **Use the API endpoints:**
```bash
# Run PO review for all open POs
curl http://localhost:5001/api/run-po-review

# Run for specific WPQ with cleanup
curl "http://localhost:5001/api/run-po-review?wpq=WPQ123456&cleanup=true&text_limit=1500"

# POST request with JSON
curl -X POST http://localhost:5001/api/run-po-review \
  -H "Content-Type: application/json" \
  -d '{"wpq": "WPQ123456", "cleanup": true, "text_limit": 1500}'

# Check PO status
curl "http://localhost:5001/api/po-status?wpq=WPQ123456"

# Cleanup stuck records
curl -X POST http://localhost:5001/api/po-cleanup
```

3. **Test the API:**
```bash
cd ../whatsapp
python3 test_combined_api.py
```

## Configuration

Make sure your `config.ini` file contains all required sections:

- **`[OpenAI]`** - OpenAI API key
- **`[Database]`** - Development database connection
- **`[Production]`** - Production database connection
- **`[Email]`** - Email configuration for notifications
- **`[CommunicationTimeframes]`** - Timing rules for processing
- **`[Guidelines]`** - Processing guidelines

## Logs

- **`po_review.log`** - Main processing logs
- **`../whatsapp/api_server.log`** - API server logs (when using API)

## API Integration

This system is integrated with the WhatsApp API server at `../whatsapp/api_server.py`. The combined server provides both WhatsApp notification and PO review capabilities on port 5001.

Available API endpoints:
- `GET/POST /api/run-po-review` - Run PO review
- `GET /api/po-status` - Check PO status
- `POST /api/po-cleanup` - Clean up stuck records
- `GET /health` - Health check
