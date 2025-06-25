from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import sys
import subprocess
import os
from datetime import datetime
import json

# Configure logging for API
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('api_server.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'WhatsApp Notification API'
    }), 200

@app.route('/api/run-whatsapp', methods=['GET'])
def run_whatsapp_script():
    """Run the waprod.py script"""
    try:
        env = request.args.get('env', 'test')  # 'test' or 'prod'
        
        if env not in ['test', 'prod']:
            return jsonify({
                'success': False,
                'error': 'env must be either "test" or "prod"',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        logger.info(f"API request: Running WhatsApp script in {env} mode")
        
        # Get current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, 'waprod.py')
        
        # Run the script
        cmd = [sys.executable, script_path, '--env', env]
        logger.info(f"Executing command: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout
        )
        
        success = result.returncode == 0
        
        logger.info(f"Script execution completed. Return code: {result.returncode}")
        
        return jsonify({
            'success': success,
            'message': f'WhatsApp script executed in {env} mode',
            'env': env,
            'return_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'timestamp': datetime.now().isoformat()
        }), 200 if success else 500
        
    except subprocess.TimeoutExpired:
        logger.error("Script execution timed out")
        return jsonify({
            'success': False,
            'error': 'Script execution timed out (5 minutes)',
            'timestamp': datetime.now().isoformat()
        }), 408
        
    except Exception as e:
        logger.error(f"Error running WhatsApp script: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found',
        'timestamp': datetime.now().isoformat()
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error',
        'timestamp': datetime.now().isoformat()
    }), 500

if __name__ == '__main__':
    logger.info("Starting WhatsApp Notification API Server")
    logger.info("Available endpoints:")
    logger.info("  GET  /health - Health check")
    logger.info("  GET  /api/run-whatsapp?env=test - Run WhatsApp script in test mode")
    logger.info("  GET  /api/run-whatsapp?env=prod - Run WhatsApp script in production mode")
    
    app.run(
        host='0.0.0.0',
        port=5001,
        debug=False
    )
