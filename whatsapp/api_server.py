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
        'service': 'WhatsApp & PO Review API'
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

@app.route('/api/run-po-review', methods=['GET', 'POST'])
def run_po_review():
    """Run the po_review_main.py script from lane folder"""
    try:
        # Get parameters from query string or JSON body
        if request.method == 'POST':
            data = request.get_json() or {}
            wpq_number = data.get('wpq')
            config_path = data.get('config')
            cleanup = data.get('cleanup', False)
            text_limit = data.get('text_limit')
        else:
            wpq_number = request.args.get('wpq')
            config_path = request.args.get('config')
            cleanup = request.args.get('cleanup', 'false').lower() == 'true'
            text_limit = request.args.get('text_limit')
        
        logger.info(f"API request: Running PO review script")
        logger.info(f"Parameters: WPQ={wpq_number}, config={config_path}, cleanup={cleanup}, text_limit={text_limit}")
        
        # Get lane directory (sibling to whatsapp)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        lane_dir = os.path.join(parent_dir, 'lane')
        script_path = os.path.join(lane_dir, 'po_review_main.py')
        
        # Check if lane directory and script exist
        if not os.path.exists(lane_dir):
            return jsonify({
                'success': False,
                'error': f'Lane directory not found at: {lane_dir}',
                'timestamp': datetime.now().isoformat()
            }), 404
            
        if not os.path.exists(script_path):
            return jsonify({
                'success': False,
                'error': f'PO review script not found at: {script_path}',
                'timestamp': datetime.now().isoformat()
            }), 404
        
        # Default config path if not provided
        if not config_path:
            config_path = os.path.join(lane_dir, 'config.ini')
        
        # Build command
        cmd = [sys.executable, script_path, '--config', config_path]
        
        # Add optional parameters
        if wpq_number:
            cmd.extend(['--WPQ', wpq_number])
        
        if cleanup:
            cmd.append('--cleanup')
            
        if text_limit:
            cmd.extend(['--text-limit', str(text_limit)])
        
        logger.info(f"Executing PO review command: {' '.join(cmd)}")
        
        # Change to lane directory for execution
        original_cwd = os.getcwd()
        os.chdir(lane_dir)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes timeout
            )
        finally:
            os.chdir(original_cwd)
        
        success = result.returncode == 0
        
        logger.info(f"PO review script execution completed. Return code: {result.returncode}")
        
        return jsonify({
            'success': success,
            'message': 'PO review script executed',
            'parameters': {
                'wpq': wpq_number,
                'config': config_path,
                'cleanup': cleanup,
                'text_limit': text_limit
            },
            'return_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'timestamp': datetime.now().isoformat()
        }), 200 if success else 500
        
    except subprocess.TimeoutExpired:
        logger.error("PO review script execution timed out")
        return jsonify({
            'success': False,
            'error': 'PO review script execution timed out (10 minutes)',
            'timestamp': datetime.now().isoformat()
        }), 408
        
    except Exception as e:
        logger.error(f"Error running PO review script: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/po-status', methods=['GET'])
def get_po_status():
    """Get status of PO processing"""
    try:
        wpq_number = request.args.get('wpq')
        
        if not wpq_number:
            return jsonify({
                'success': False,
                'error': 'WPQ number is required',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        # Here you could add logic to check PO status from database
        # For now, just return a basic response
        logger.info(f"Status check for WPQ: {wpq_number}")
        
        return jsonify({
            'success': True,
            'wpq': wpq_number,
            'message': 'Status check endpoint - implement database query here',
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error checking PO status: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/po-cleanup', methods=['POST'])
def cleanup_stuck_records():
    """Clean up stuck processing records"""
    try:
        logger.info("API request: Cleanup stuck PO records")
        
        # Get lane directory (sibling to whatsapp)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        lane_dir = os.path.join(parent_dir, 'lane')
        script_path = os.path.join(lane_dir, 'po_review_main.py')
        config_path = os.path.join(lane_dir, 'config.ini')
        
        cmd = [sys.executable, script_path, '--config', config_path, '--cleanup']
        
        logger.info(f"Executing cleanup command: {' '.join(cmd)}")
        
        # Change to lane directory for execution
        original_cwd = os.getcwd()
        os.chdir(lane_dir)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
        finally:
            os.chdir(original_cwd)
        
        success = result.returncode == 0
        
        return jsonify({
            'success': success,
            'message': 'PO cleanup operation completed',
            'return_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'timestamp': datetime.now().isoformat()
        }), 200 if success else 500
        
    except Exception as e:
        logger.error(f"Error during PO cleanup: {e}")
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
    logger.info("Starting WhatsApp & PO Review API Server")
    logger.info("Available endpoints:")
    logger.info("  GET  /health - Health check")
    logger.info("  GET  /api/run-whatsapp?env=test - Run WhatsApp script in test mode")
    logger.info("  GET  /api/run-whatsapp?env=prod - Run WhatsApp script in production mode")
    logger.info("  GET  /api/run-po-review?wpq=XXX&cleanup=true&text_limit=1500 - Run PO review")
    logger.info("  POST /api/run-po-review - Run PO review with JSON body")
    logger.info("  GET  /api/po-status?wpq=XXX - Check PO status")
    logger.info("  POST /api/po-cleanup - Clean up stuck PO records")
    
    app.run(
        host='0.0.0.0',
        port=5001,
        debug=False
    )
