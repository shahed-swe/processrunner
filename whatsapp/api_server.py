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
        script_path = os.path.join(current_dir, 'waprod2.py')
        
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

@app.route('/api/run-poprocess', methods=['GET', 'POST'])
def run_poprocess_pipeline():
    """Run all poprocess scripts in sequence"""
    try:
        logger.info("API request: Running PO process pipeline")
        
        # Get poprocess directory (sibling to whatsapp)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        poprocess_dir = os.path.join(parent_dir, 'poprocess')
        
        # Check if poprocess directory exists
        if not os.path.exists(poprocess_dir):
            return jsonify({
                'success': False,
                'error': f'Poprocess directory not found at: {poprocess_dir}',
                'timestamp': datetime.now().isoformat()
            }), 404
        
        # Define scripts to run in order
        scripts = [
            'saveattacment.py',
            'converttopdf.py', 
            'ai_classification_linux.py',
            'APIProcessingPO_linux.py',
            'send_file-linux.py'
        ]
        
        # Verify all scripts exist
        for script in scripts:
            script_path = os.path.join(poprocess_dir, script)
            if not os.path.exists(script_path):
                return jsonify({
                    'success': False,
                    'error': f'Script not found: {script_path}',
                    'timestamp': datetime.now().isoformat()
                }), 404
        
        # Execute scripts sequentially
        results = []
        overall_success = True
        combined_stdout = ""
        combined_stderr = ""
        
        # Get virtual environment path
        env_activate_path = os.path.join(parent_dir, 'env', 'bin', 'activate')
        
        # Change to poprocess directory for execution
        original_cwd = os.getcwd()
        
        try:
            os.chdir(poprocess_dir)
            
            for i, script in enumerate(scripts, 1):
                script_path = os.path.join(poprocess_dir, script)
                
                logger.info(f"Executing step {i}/5: {script}")
                combined_stdout += f"\n{'='*60}\n"
                combined_stdout += f"STEP {i}/5: Executing {script}\n"
                combined_stdout += f"{'='*60}\n"
                
                try:
                    # Run the script with virtual environment activation
                    cmd = ['bash', '-c', f'source {env_activate_path} && cd {poprocess_dir} && python {script}']
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=1800  # 30 minutes timeout per script
                    )
                    
                    # Store individual result
                    script_success = result.returncode == 0
                    script_result = {
                        'step': i,
                        'script': script,
                        'success': script_success,
                        'return_code': result.returncode,
                        'stdout': result.stdout,
                        'stderr': result.stderr,
                        'timestamp': datetime.now().isoformat()
                    }
                    results.append(script_result)
                    
                    # Add to combined output
                    combined_stdout += f"Return Code: {result.returncode}\n"
                    if result.stdout:
                        combined_stdout += f"STDOUT:\n{result.stdout}\n"
                    if result.stderr:
                        combined_stderr += f"STEP {i} - {script} STDERR:\n{result.stderr}\n"
                    
                    logger.info(f"Step {i} completed: {script} (return code: {result.returncode})")
                    
                    # If script failed, update overall success but continue with remaining scripts
                    if not script_success:
                        overall_success = False
                        logger.warning(f"Step {i} failed: {script}")
                        combined_stdout += f"⚠️  WARNING: {script} failed with return code {result.returncode}\n"
                        # Continue to next script instead of breaking
                    else:
                        combined_stdout += f"✅ SUCCESS: {script} completed successfully\n"
                    
                except subprocess.TimeoutExpired:
                    error_msg = f"Script {script} timed out (30 minutes)"
                    logger.error(error_msg)
                    
                    script_result = {
                        'step': i,
                        'script': script,
                        'success': False,
                        'return_code': -1,
                        'stdout': '',
                        'stderr': error_msg,
                        'timestamp': datetime.now().isoformat()
                    }
                    results.append(script_result)
                    
                    overall_success = False
                    combined_stdout += f"❌ TIMEOUT: {script} timed out after 30 minutes\n"
                    combined_stderr += f"STEP {i} - {script} TIMEOUT: {error_msg}\n"
                    
                    # Continue to next script
                    continue
                    
                except Exception as e:
                    error_msg = f"Error executing {script}: {str(e)}"
                    logger.error(error_msg)
                    
                    script_result = {
                        'step': i,
                        'script': script,
                        'success': False,
                        'return_code': -1,
                        'stdout': '',
                        'stderr': error_msg,
                        'timestamp': datetime.now().isoformat()
                    }
                    results.append(script_result)
                    
                    overall_success = False
                    combined_stdout += f"❌ ERROR: {script} failed with error: {str(e)}\n"
                    combined_stderr += f"STEP {i} - {script} ERROR: {error_msg}\n"
                    
                    # Continue to next script
                    continue
        
        finally:
            os.chdir(original_cwd)
        
        # Add summary to combined output
        combined_stdout += f"\n{'='*60}\n"
        combined_stdout += f"PIPELINE EXECUTION SUMMARY\n"
        combined_stdout += f"{'='*60}\n"
        successful_steps = sum(1 for r in results if r['success'])
        combined_stdout += f"Total Steps: {len(scripts)}\n"
        combined_stdout += f"Successful: {successful_steps}\n"
        combined_stdout += f"Failed: {len(scripts) - successful_steps}\n"
        combined_stdout += f"Overall Status: {'SUCCESS' if overall_success else 'PARTIAL/FAILED'}\n"
        
        for result in results:
            status = "✅ SUCCESS" if result['success'] else "❌ FAILED"
            combined_stdout += f"  Step {result['step']}: {result['script']} - {status}\n"
        
        logger.info(f"PO process pipeline completed. Overall success: {overall_success}")
        logger.info(f"Successful steps: {successful_steps}/{len(scripts)}")
        
        return jsonify({
            'success': overall_success,
            'message': 'PO process pipeline executed',
            'summary': {
                'total_steps': len(scripts),
                'successful_steps': successful_steps,
                'failed_steps': len(scripts) - successful_steps,
                'scripts_executed': scripts
            },
            'results': results,
            'combined_stdout': combined_stdout,
            'combined_stderr': combined_stderr,
            'timestamp': datetime.now().isoformat()
        }), 200 if overall_success else 207  # 207 = Multi-Status (partial success)
        
    except Exception as e:
        logger.error(f"Error running PO process pipeline: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/run-mailsend', methods=['GET', 'POST'])
def run_mailsend_script():
    """Run the main_mail_send_linux.py script from mailsend folder"""
    try:
        # Get parameters from query string or JSON body
        if request.method == 'POST':
            data = request.get_json() or {}
            env = data.get('env', 'prod')
            test = data.get('test', False)
        else:
            env = request.args.get('env', 'prod')
            test_param = request.args.get('test', 'false').lower()
            test = test_param in ['true', '1', 'yes', 'y']
        
        logger.info(f"API request: Running mailsend script with env={env}, test={test}")
        
        # Get mailsend directory (sibling to whatsapp)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        mailsend_dir = os.path.join(parent_dir, 'mailsend')
        script_path = os.path.join(mailsend_dir, 'main_mail_send_linux.py')
        
        # Check if mailsend directory and script exist
        if not os.path.exists(mailsend_dir):
            return jsonify({
                'success': False,
                'error': f'Mailsend directory not found at: {mailsend_dir}',
                'timestamp': datetime.now().isoformat()
            }), 404
            
        if not os.path.exists(script_path):
            return jsonify({
                'success': False,
                'error': f'Mailsend script not found at: {script_path}',
                'timestamp': datetime.now().isoformat()
            }), 404
        
        # Prepare input responses: environment choice (1=prod, 2=dev) and test mode (y/n)
        env_choice = "1" if env == 'prod' else "2"
        test_choice = "y" if test else "n"
        input_responses = f"{env_choice}\n{test_choice}\n"
        
        # Build command with virtual environment activation
        env_activate_path = os.path.join(parent_dir, 'env', 'bin', 'activate')
        cmd = ['bash', '-c', f'source {env_activate_path} && cd {mailsend_dir} && python3 main_mail_send_linux.py']
        logger.info(f"Executing mailsend command: {' '.join(cmd)}")
        
        # Change to mailsend directory for execution
        original_cwd = os.getcwd()
        os.chdir(mailsend_dir)
        
        try:
            result = subprocess.run(
                cmd,
                input=input_responses,
                capture_output=True,
                text=True,
                timeout=1800  # 30 minutes timeout
            )
        finally:
            os.chdir(original_cwd)
        
        success = result.returncode == 0
        logger.info(f"Mailsend script execution completed. Return code: {result.returncode}")
        
        return jsonify({
            'success': success,
            'message': 'Mailsend script executed',
            'parameters': {
                'env': env,
                'test': test
            },
            'return_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'timestamp': datetime.now().isoformat()
        }), 200 if success else 500
        
    except subprocess.TimeoutExpired:
        logger.error("Mailsend script execution timed out")
        return jsonify({
            'success': False,
            'error': 'Mailsend script execution timed out (30 minutes)',
            'timestamp': datetime.now().isoformat()
        }), 408
        
    except Exception as e:
        logger.error(f"Error running mailsend script: {e}")
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
    logger.info("  GET/POST /api/run-poprocess - Run complete PO process pipeline (5 scripts)")
    logger.info("  GET/POST /api/run-mailsend?env=prod&test=true - Run mailsend script")
    logger.info("  POST /api/po-cleanup - Clean up stuck PO records")
    
    app.run(
        host='0.0.0.0',
        port=5001,
        debug=False
    )
