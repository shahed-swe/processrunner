import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import mysql.connector
from mysql.connector import Error as MySQLError
from contextlib import contextmanager
from datetime import datetime
import os
import sys
import json
import time
import re
import tempfile
import signal
import atexit
from typing import Optional, Dict, List
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Cross-platform file locking
if os.name == 'posix':  # Linux/Unix
    import fcntl
    USE_FCNTL = True
else:  # Windows
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    USE_FCNTL = False

# Process lock file path
LOCK_FILE_PATH = os.path.join(tempfile.gettempdir(), 'whatsapp_notifications.lock')
LOCK_FILE_HANDLE = None

def acquire_lock():
    """Acquire exclusive process lock - cross-platform"""
    global LOCK_FILE_HANDLE
    try:
        LOCK_FILE_HANDLE = open(LOCK_FILE_PATH, 'w')
        
        if USE_FCNTL:  # Linux/Unix
            fcntl.flock(LOCK_FILE_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # Windows
            # Simple file-based locking for Windows
            if os.path.exists(LOCK_FILE_PATH + '.lock'):
                LOCK_FILE_HANDLE.close()
                LOCK_FILE_HANDLE = None
                return False
            # Create lock indicator file
            with open(LOCK_FILE_PATH + '.lock', 'w') as lock_indicator:
                lock_indicator.write(str(os.getpid()))
        
        LOCK_FILE_HANDLE.write(str(os.getpid()))
        LOCK_FILE_HANDLE.flush()
        return True
    except (IOError, BlockingIOError):
        if LOCK_FILE_HANDLE:
            LOCK_FILE_HANDLE.close()
            LOCK_FILE_HANDLE = None
        return False

def release_lock():
    """Release process lock - cross-platform"""
    global LOCK_FILE_HANDLE
    if LOCK_FILE_HANDLE:
        try:
            if USE_FCNTL:  # Linux/Unix
                fcntl.flock(LOCK_FILE_HANDLE.fileno(), fcntl.LOCK_UN)
            else:  # Windows
                # Remove lock indicator file
                try:
                    os.unlink(LOCK_FILE_PATH + '.lock')
                except:
                    pass
            
            LOCK_FILE_HANDLE.close()
            try:
                os.unlink(LOCK_FILE_PATH)
            except:
                pass
        except:
            pass
        LOCK_FILE_HANDLE = None

def signal_handler(signum, frame):
    """Handle termination signals"""
    logger.info(f"Received signal {signum}, cleaning up...")
    release_lock()
    sys.exit(0)

# Register cleanup functions
atexit.register(release_lock)

# Only register signal handlers that exist on this platform
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, signal_handler)
if hasattr(signal, 'SIGINT'):
    signal.signal(signal.SIGINT, signal_handler)

# Create unique log file for each process to avoid conflicts
LOG_FILE = f'whatsapp_notifications_{datetime.now().strftime("%Y%m%d")}.log'

# Configure logging with file rotation
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(process)d - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Twilio configuration from environment variables
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')
TEST_NUMBER = os.getenv('TEST_NUMBER')
TEMPLATE_SID_HEBREW = os.getenv('TEMPLATE_SID_HEBREW')
TEMPLATE_SID_OTHER = os.getenv('TEMPLATE_SID_OTHER')

# Validate required environment variables
required_env_vars = [
    'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_NUMBER',
    'TEST_NUMBER', 'TEMPLATE_SID_HEBREW', 'TEMPLATE_SID_OTHER'
]

missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    logger.error("Please check your .env file")
    sys.exit(1)

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '113.30.189.140'),
    'database': os.getenv('DB_DATABASE', 'supsol_db'),
    'user': os.getenv('DB_USER', 'WA'),
    'password': os.getenv('DB_PASSWORD', 'g&3cX@$tNt*S7@Qs'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4'),
    'connect_timeout': int(os.getenv('DB_CONNECT_TIMEOUT', '10')),
    'autocommit': True
}




class DatabaseError(Exception):
    """Custom exception for database operations"""
    pass

def format_phone_number(phone: str) -> str:
    """Format phone number for WhatsApp - preserves original number"""
    phone = re.sub(r'\D', '', phone)
    return f'whatsapp:+{phone}'

@contextmanager
def get_db_connection():
    """Create a database connection with enhanced error handling and timeouts"""
    connection = None
    try:
        logger.info("Establishing database connection...")
        connection = mysql.connector.connect(**DB_CONFIG)
        if not connection.is_connected():
            raise DatabaseError("Failed to establish database connection")
        
        # Set connection timeout
        connection.cmd_query("SET SESSION wait_timeout=30")
        connection.cmd_query("SET SESSION interactive_timeout=30")
        
        logger.info("Database connection established successfully")
        yield connection
    except MySQLError as err:
        logger.error(f"MySQL Error: {err}")
        raise DatabaseError(f"Database connection error: {err}")
    except Exception as e:
        logger.error(f"Unexpected error in database connection: {e}")
        raise DatabaseError(f"Unexpected database error: {e}")
    finally:
        if connection and connection.is_connected():
            connection.close()
            logger.info("Database connection closed")

def execute_query(connection, query: str, params: tuple = None, fetch: bool = True, timeout: int = 30) -> Optional[List[Dict]]:
    """Execute a database query with error handling and timeout"""
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        logger.info(f"Executing query: {query[:100]}...")  # Limit log length
        if params:
            logger.info(f"Query parameters: {params}")
        
        # Set query timeout
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute(query, params or ())
        
        if fetch:
            result = cursor.fetchall()
            logger.info(f"Query returned {len(result)} results")
            return result
        else:
            connection.commit()
            logger.info(f"Query executed successfully. Rows affected: {cursor.rowcount}")
            return None
    except MySQLError as err:
        logger.error(f"Database query error: {err}")
        if connection.is_connected():
            connection.rollback()
        raise DatabaseError(f"Query execution failed: {err}")
    finally:
        if cursor:
            cursor.close()

def get_pending_wpq() -> List[Dict]:
    """Get WPQ details from database that need notification with row locking"""
    # Use SELECT FOR UPDATE to prevent concurrent processing of same records
    query = """
        SELECT DISTINCT
            sc.WPQNumber,
            sc.PQNumber,
            ev.CompanyName as VendorCompanyName,
            ev.MobilePhone as VendorPhone,
            ev.Email as VendorEmail,
            COALESCE(ev.FirstLanguage, 'Hebrew') as VendorLanguage,
            CONCAT(cust.FullName, ' (', comp.Name, ')') as CustomerName,
            ev.CompanyCountry as VendorCompanyCountry,
            sci.InitialExecutionDate as ExpectedDate,
            eu.EU_Phone as SupporterPhone,
            eu.EU_FullName as SupporterName,
            GROUP_CONCAT(sal.ID) as AuditLogIDs
        FROM sol_servicecalls sc
        LEFT JOIN sol_enterprise_vendors ev ON sc.VendorID = ev.ID
        LEFT JOIN sol_enterprise_customers cust ON sc.CustomerID = cust.ID
        LEFT JOIN sol_enterprise_companies comp ON cust.CompanyID = comp.ID
        LEFT JOIN sol_servicecalls_items sci ON sc.WPQNumber = sci.WPQNumber
        LEFT JOIN sol_enterprise_users eu ON sc.SupporterID = eu.EU_UserID
        INNER JOIN sol_servicecalls_audit_logs sal ON sal.WPQNumber = sc.WPQNumber 
            AND sal.AuditTypeID IN (300, 900, 1500, 2100)
            AND sal.ExecutionStatus != 999
        WHERE sc.CallStatus IN (0, 20, 40, 100)
        AND sc.ProcessingStatus = 0
        GROUP BY sc.WPQNumber, sc.PQNumber, ev.CompanyName, ev.MobilePhone, ev.Email, 
                 ev.FirstLanguage, cust.FullName, comp.Name, ev.CompanyCountry, 
                 sci.InitialExecutionDate, eu.EU_Phone, eu.EU_FullName
        ORDER BY sc.WPQNumber
        LIMIT 50
        FOR UPDATE SKIP LOCKED
    """
    
    try:
        with get_db_connection() as connection:
            results = execute_query(connection, query)
            logger.info(f"Retrieved {len(results)} pending WPQs")
            return results
    except DatabaseError as e:
        logger.error(f"Failed to retrieve pending WPQs: {e}")
        return []

def update_processing_status(wpq_number: str, status: int) -> bool:
    """Update ProcessingStatus for a specific WPQ"""
    query = """
        UPDATE sol_servicecalls 
        SET ProcessingStatus = %s
        WHERE WPQNumber = %s
    """
    
    # Log the status change attempt
    status_text = "PROCESSING" if status == 1 else "COMPLETED"
    logger.info(f"[STATUS] Updating ProcessingStatus to {status} ({status_text}) for WPQ {wpq_number}")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_db_connection() as connection:
                execute_query(connection, query, (status, wpq_number), fetch=False)
                logger.info(f"[SUCCESS] Updated ProcessingStatus to {status} ({status_text}) for WPQ {wpq_number}")
                return True
        except DatabaseError as e:
            logger.warning(f"ProcessingStatus update attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"[FAILED] Failed to update ProcessingStatus to {status} ({status_text}) for WPQ {wpq_number} after {max_retries} attempts")
                return False
    return False

def update_message_status(audit_log_ids: str, message_sid: str, status: str) -> bool:
    """Update message status in audit logs using specific audit log IDs"""
    if status.lower() in ['delivered', 'sent'] and audit_log_ids:
        # Convert comma-separated IDs to list for IN clause
        id_list = audit_log_ids.split(',')
        placeholders = ','.join(['%s'] * len(id_list))
        
        query = f"""
            UPDATE sol_servicecalls_audit_logs 
            SET ExecutionStatus = 999,
                TwilioMessageSID = %s
            WHERE ID IN ({placeholders})
            AND ExecutionStatus != 999
        """
        
        # Parameters: message_sid first, then all the audit log IDs
        params = [message_sid] + id_list
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with get_db_connection() as connection:
                    execute_query(connection, query, tuple(params), fetch=False)
                    logger.info(f"Successfully updated audit log status for IDs {audit_log_ids}, message {message_sid}")
                    return True
            except DatabaseError as e:
                logger.warning(f"Audit log update attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"Failed to update audit log status after {max_retries} attempts")
                    return False
    return False

def send_whatsapp_template(wpq_data: Dict, recipient_number: str, recipient_type: str) -> Dict:
    """Send WhatsApp template message to a specific number with enhanced error handling"""
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        vendor_language = wpq_data.get('VendorLanguage', 'Hebrew')
        country = wpq_data.get('VendorCompanyCountry')
        
        # Select sender number based on country
        if country == 'Israel':
            sender_number = 'whatsapp:+972559878005'
        else:
            sender_number = 'whatsapp:+19723729572'

        template_sid = TEMPLATE_SID_HEBREW if vendor_language.lower() == 'hebrew' else TEMPLATE_SID_OTHER
        
        template_data = {
            "1": wpq_data['VendorCompanyName'] if wpq_data['VendorCompanyName'] else "Dear Sir/Madam",
            "2": wpq_data['PQNumber'],
            "3": wpq_data['VendorEmail'] if wpq_data['VendorEmail'] else ""
        }
        
        logger.info(f"Sending template message for WPQ {wpq_data['WPQNumber']} to {recipient_type} ({recipient_number})")
        logger.info(f"Using sender number: {sender_number}")
        
        message = client.messages.create(
            from_=sender_number,
            to=recipient_number,
            content_sid=template_sid,
            content_variables=json.dumps(template_data)
        )
        
        logger.info(f"Message SID: {message.sid}")
        logger.info(f"Initial Status: {message.status}")
        
        # Wait and check final status
        time.sleep(3)
        try:
            message_status = client.messages(message.sid).fetch()
            final_status = message_status.status
        except:
            final_status = message.status  # Use initial status if fetch fails
        
        return {
            'success': True,
            'message_sid': message.sid,
            'status': final_status,
            'error_code': message_status.error_code if 'message_status' in locals() else None,
            'error_message': message_status.error_message if 'message_status' in locals() else None
        }

    except TwilioRestException as twilio_error:
        logger.error(f"Twilio Error for {recipient_type} ({recipient_number}):")
        logger.error(f"Error Code: {twilio_error.code}")
        logger.error(f"Error Message: {twilio_error.msg}")
        return {
            'success': False,
            'error_code': twilio_error.code,
            'error_message': twilio_error.msg,
            'details': getattr(twilio_error, 'details', None)
        }

    except Exception as e:
        logger.error(f"General Error for {recipient_type} ({recipient_number}):")
        logger.error(f"Error Type: {type(e).__name__}")
        logger.error(f"Error Message: {str(e)}")
        return {
            'success': False,
            'error_type': type(e).__name__,
            'error_message': str(e)
        }

def process_wpq_notifications(is_test_env: bool = True) -> bool:
    """Process all pending WPQ notifications with enhanced error handling"""
    success_count = 0
    error_count = 0
    
    try:
        wpq_list = get_pending_wpq()
        if not wpq_list:
            logger.info("No pending WPQs found for processing")
            return True

        logger.info(f"Found {len(wpq_list)} WPQs to process")

        for wpq_data in wpq_list:
            wpq_number = wpq_data['WPQNumber']
            processing_started = False
            
            try:
                logger.info(f"Processing WPQ {wpq_number}:")
                
                # Step 1: Mark WPQ as being processed (ProcessingStatus = 1)
                if not update_processing_status(wpq_number, 1):
                    logger.error(f"Failed to mark WPQ {wpq_number} as processing. Skipping.")
                    error_count += 1
                    continue
                
                processing_started = True
                logger.info(f"WPQ {wpq_number} marked as processing")
                
                # Format supporter phone number if available
                supporter_phone = None
                if wpq_data.get('SupporterPhone'):
                    supporter_phone = format_phone_number(wpq_data['SupporterPhone'])
                    logger.info(f"Supporter {wpq_data.get('SupporterName', 'Unknown')}'s phone: {supporter_phone}")
                
                # Define recipients based on environment - WITH DUPLICATE PREVENTION
                recipients = []
                if is_test_env:
                    recipients.append(('Test Number', TEST_NUMBER))
                    if supporter_phone and supporter_phone != TEST_NUMBER:
                        recipients.append(('Supporter', supporter_phone))
                        logger.info(f"Added supporter as separate recipient")
                    elif supporter_phone == TEST_NUMBER:
                        logger.info(f"Supporter phone matches test number - avoiding duplicate")
                else:
                    # Production environment
                    vendor_phone = None
                    if wpq_data.get('VendorPhone'):
                        vendor_phone = format_phone_number(wpq_data['VendorPhone'])
                        recipients.append(('Vendor', vendor_phone))
                    
                    if supporter_phone and supporter_phone != vendor_phone:
                        recipients.append(('Supporter', supporter_phone))
                    elif supporter_phone == vendor_phone:
                        logger.info(f"Supporter phone matches vendor phone - avoiding duplicate")
                
                logger.info(f"Will send to {len(recipients)} unique recipients")
                
                # Step 2: Send to all recipients and update audit logs
                wpq_success = True
                for recipient_type, recipient_number in recipients:
                    result = send_whatsapp_template(wpq_data, recipient_number, recipient_type)
                    
                    if result['success']:
                        logger.info(f"Message sent successfully to {recipient_type}")
                        
                        # Step 3: Mark audit logs as processed (ExecutionStatus = 999)
                        if update_message_status(wpq_data['AuditLogIDs'], result['message_sid'], result['status']):
                            success_count += 1
                        else:
                            wpq_success = False
                            error_count += 1
                    else:
                        wpq_success = False
                        error_count += 1
                        logger.error(f"Failed to send message to {recipient_type}")

                # Step 4: Mark WPQ as completed (ProcessingStatus = 0)
                if not update_processing_status(wpq_number, 0):
                    logger.error(f"Failed to mark WPQ {wpq_number} as completed")
                    wpq_success = False
                else:
                    logger.info(f"WPQ {wpq_number} marked as completed")
                
                processing_started = False  # Successfully completed
                
                # Add small delay between WPQs to avoid overwhelming the system
                time.sleep(1)

            except Exception as e:
                error_count += 1
                logger.error(f"Error processing WPQ {wpq_number}: {e}")
                
                # Step 5: CRITICAL ERROR HANDLING - Reset ProcessingStatus to 0
                if processing_started:
                    try:
                        if update_processing_status(wpq_number, 0):
                            logger.info(f"Reset ProcessingStatus to 0 for failed WPQ {wpq_number}")
                        else:
                            logger.error(f"CRITICAL: Failed to reset ProcessingStatus for WPQ {wpq_number}")
                    except Exception as reset_error:
                        logger.error(f"CRITICAL: Exception during ProcessingStatus reset for WPQ {wpq_number}: {reset_error}")
                continue

        logger.info(f"Batch processing completed:")
        logger.info(f"  - Total WPQs processed: {len(wpq_list)}")
        logger.info(f"  - Successful: {success_count}")
        logger.info(f"  - Failed: {error_count}")
        
        return error_count == 0

    except Exception as e:
        logger.error(f"Critical error in batch processing: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    # Check for process lock first
    if not acquire_lock():
        logger.warning("Another instance is already running. Exiting.")
        sys.exit(0)
    
    parser = argparse.ArgumentParser(description='Send WhatsApp messages for pending WPQs')
    parser.add_argument('--env', choices=['test', 'prod'], default='test',
                      help='Environment to run in (test or prod)')
    parser.add_argument('--timeout', type=int, default=300,
                      help='Maximum execution time in seconds')
    
    args = parser.parse_args()
    
    is_test = args.env == 'test'
    env_name = "TEST" if is_test else "PRODUCTION"
    
    logger.info("=" * 50)
    logger.info(f"Starting WhatsApp notification service")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info(f"Environment: {env_name}")
    logger.info(f"Lock file: {LOCK_FILE_PATH}")
    logger.info(f"Execution timeout: {args.timeout} seconds")
    logger.info("=" * 50)
    
    try:
        # Set execution timeout (Unix/Linux only)
        if hasattr(signal, 'alarm'):
            signal.alarm(args.timeout)
        else:
            logger.info("Timeout mechanism not available on this platform (Windows)")
        
        success = process_wpq_notifications(is_test_env=is_test)
        
        if success:
            logger.info("Batch processing completed successfully!")
            sys.exit(0)
        else:
            logger.error("Errors occurred during batch processing")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Critical application error: {e}")
        sys.exit(1)
    finally:
        if hasattr(signal, 'alarm'):
            signal.alarm(0)  # Disable alarm
        release_lock()