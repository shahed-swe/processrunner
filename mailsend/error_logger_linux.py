#!/usr/bin/env python3
# error_logger_linux.py

import logging
import os
from datetime import datetime
import traceback
import sys

def setup_logging(log_name: str = "application"):
    """Setup logging with Linux-compatible paths and proper permissions"""
    # Create logs directory in user's home directory
    log_dir = os.path.expanduser("~/scripts/logs")
    os.makedirs(log_dir, mode=0o755, exist_ok=True)

    # Set up logging with date-based filename
    log_file = os.path.join(log_dir, f'{log_name}_{datetime.now().strftime("%Y%m%d")}.log')
    
    # Configure logging with both file and console output
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='a', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Log file: {log_file}")
    
    # Set proper permissions for log file
    try:
        os.chmod(log_file, 0o644)
    except Exception as e:
        logger.warning(f"Could not set log file permissions: {e}")
    
    return logger

def log_error(logger, error_message, exception=None):
    """Log error message with optional exception details"""
    if logger is None:
        logger = logging.getLogger(__name__)

    if exception:
        logger.error(f"{error_message}: {str(exception)}")
        logger.error(f"Exception type: {type(exception).__name__}")
        logger.error("Stack trace:")
        logger.error(traceback.format_exc())
    else:
        logger.error(error_message)

def log_warning(logger, warning_message):
    """Log warning message"""
    if logger is None:
        logger = logging.getLogger(__name__)

    logger.warning(warning_message)

def log_info(logger, info_message):
    """Log info message"""
    if logger is None:
        logger = logging.getLogger(__name__)

    logger.info(info_message)

def log_debug(logger, debug_message):
    """Log debug message"""
    if logger is None:
        logger = logging.getLogger(__name__)

    logger.debug(debug_message)

def log_critical(logger, critical_message, exception=None):
    """Log critical message with optional exception details"""
    if logger is None:
        logger = logging.getLogger(__name__)

    if exception:
        logger.critical(f"{critical_message}: {str(exception)}")
        logger.critical(traceback.format_exc())
    else:
        logger.critical(critical_message)

class ErrorHandler:
    """Enhanced error handler class with Linux-specific improvements"""
    
    @staticmethod
    def handle_database_error(logger, error, query=None, params=None):
        """Handle database-related errors"""
        error_message = f"Database error occurred: {str(error)}"
        if query:
            # Truncate very long queries for readability
            query_preview = query[:500] + "..." if len(query) > 500 else query
            error_message += f"\nQuery: {query_preview}"
        if params:
            error_message += f"\nParameters: {str(params)[:200]}"
        log_error(logger, error_message, error)

    @staticmethod
    def handle_network_error(logger, error, url=None):
        """Handle network-related errors"""
        error_message = f"Network error occurred: {str(error)}"
        if url:
            error_message += f"\nURL: {url}"
        log_error(logger, error_message, error)

    @staticmethod
    def handle_file_error(logger, error, file_path):
        """Handle file operation errors"""
        error_message = f"File error occurred with {file_path}: {str(error)}"
        
        # Add file system information if possible
        try:
            if os.path.exists(file_path):
                stat = os.stat(file_path)
                error_message += f"\nFile size: {stat.st_size} bytes"
                error_message += f"\nFile permissions: {oct(stat.st_mode)[-3:]}"
            else:
                error_message += "\nFile does not exist"
        except Exception:
            pass
            
        log_error(logger, error_message, error)

    @staticmethod
    def handle_email_error(logger, error, recipient=None):
        """Handle email-related errors"""
        error_message = f"Email error occurred: {str(error)}"
        if recipient:
            error_message += f"\nRecipient: {recipient}"
        log_error(logger, error_message, error)

    @staticmethod
    def handle_api_error(logger, error, api_endpoint=None, status_code=None):
        """Handle API-related errors"""
        error_message = f"API error occurred: {str(error)}"
        if api_endpoint:
            error_message += f"\nEndpoint: {api_endpoint}"
        if status_code:
            error_message += f"\nStatus Code: {status_code}"
        log_error(logger, error_message, error)

    @staticmethod
    def handle_unexpected_error(logger, error, context=None):
        """Handle unexpected/general errors"""
        error_message = f"Unexpected error occurred: {str(error)}"
        if context:
            error_message += f"\nContext: {context}"
        log_error(logger, error_message, error)

def get_error_summary(log_file_path=None, error_level="ERROR", max_lines=100):
    """Get summary of errors from log file"""
    if log_file_path is None:
        # Default to today's application log
        log_dir = os.path.expanduser("~/scripts/logs")
        log_file_path = os.path.join(log_dir, f'application_{datetime.now().strftime("%Y%m%d")}.log')
    
    error_summary = []
    try:
        if not os.path.exists(log_file_path):
            return [f"Log file not found: {log_file_path}"]
            
        with open(log_file_path, 'r', encoding='utf-8') as log_file:
            lines = log_file.readlines()
            
            # Get the last max_lines lines that contain the error level
            relevant_lines = [line.strip() for line in lines if error_level in line]
            error_summary = relevant_lines[-max_lines:] if len(relevant_lines) > max_lines else relevant_lines
            
    except Exception as e:
        error_summary = [f"Error reading log file {log_file_path}: {str(e)}"]
    
    return error_summary

def get_log_stats(log_file_path=None):
    """Get statistics about log entries"""
    if log_file_path is None:
        log_dir = os.path.expanduser("~/scripts/logs")
        log_file_path = os.path.join(log_dir, f'application_{datetime.now().strftime("%Y%m%d")}.log')
    
    stats = {
        'total_lines': 0,
        'errors': 0,
        'warnings': 0,
        'info': 0,
        'debug': 0,
        'critical': 0,
        'file_size': 0
    }
    
    try:
        if not os.path.exists(log_file_path):
            return stats
            
        # Get file size
        stats['file_size'] = os.path.getsize(log_file_path)
        
        with open(log_file_path, 'r', encoding='utf-8') as log_file:
            for line in log_file:
                stats['total_lines'] += 1
                if 'ERROR' in line:
                    stats['errors'] += 1
                elif 'WARNING' in line:
                    stats['warnings'] += 1
                elif 'INFO' in line:
                    stats['info'] += 1
                elif 'DEBUG' in line:
                    stats['debug'] += 1
                elif 'CRITICAL' in line:
                    stats['critical'] += 1
                    
    except Exception as e:
        print(f"Error reading log stats from {log_file_path}: {str(e)}")
    
    return stats

def cleanup_old_logs(days_to_keep=30, log_prefix="application"):
    """Clean up log files older than specified days"""
    logger = logging.getLogger(__name__)
    log_dir = os.path.expanduser("~/scripts/logs")
    
    if not os.path.exists(log_dir):
        return
    
    try:
        cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)
        cleaned_count = 0
        
        for filename in os.listdir(log_dir):
            if filename.startswith(log_prefix) and filename.endswith('.log'):
                file_path = os.path.join(log_dir, filename)
                
                if os.path.getctime(file_path) < cutoff_time:
                    try:
                        os.remove(file_path)
                        cleaned_count += 1
                        logger.info(f"Removed old log file: {filename}")
                    except Exception as e:
                        logger.warning(f"Could not remove old log file {filename}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} old log files")
            
    except Exception as e:
        logger.error(f"Error during log cleanup: {e}")

# Context manager for temporary log level changes
class TemporaryLogLevel:
    """Context manager to temporarily change logging level"""
    
    def __init__(self, logger, level):
        self.logger = logger
        self.new_level = level
        self.old_level = None
    
    def __enter__(self):
        self.old_level = self.logger.level
        self.logger.setLevel(self.new_level)
        return self.logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.setLevel(self.old_level)

# Initialize logging when module is imported
if __name__ != "__main__":
    # Only setup default logging if not running as main module
    try:
        setup_logging()
    except Exception:
        pass  # Fail silently if logging setup fails