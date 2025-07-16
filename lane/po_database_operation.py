#po_database_operations-fixed.py
import mysql.connector
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '113.30.189.140'),
    'database': os.getenv('DB_DATABASE', 'supsol_db'),
    'user': os.getenv('DB_USER', 'WA'),
    'password': os.getenv('DB_PASSWORD', 'g&3cX@$tNt*S7@Qs'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4'),
    'connect_timeout': int(os.getenv('DB_CONNECT_TIMEOUT', '10')),
    'allow_user_variables': os.getenv('DB_ALLOW_USER_VARIABLES', 'False'),
    'autocommit': True
}

@contextmanager
def get_db_connection():
    """Create a database connection using environment variables"""
    connection = None
    try:
        connection = connect_to_database()
        yield connection
    finally:
        if connection:
            try:
                connection.close()
                logging.info("Database connection closed.")
            except mysql.connector.Error as err:
                logging.error(f"Error closing database connection: {err}")

def connect_to_database():
    """Connect to database using environment variables"""
    logging.info("Connecting to database...")
    connection_params = {
        'host': DB_CONFIG.get('host'),
        'user': DB_CONFIG['user'],
        'password': DB_CONFIG['password'],
        'database': DB_CONFIG['database'],
        'charset': DB_CONFIG.get('charset', 'utf8mb4'),
        'use_unicode': True,
        'allow_local_infile': True
    }
    
    if DB_CONFIG.get('allow_user_variables', 'False').lower() == 'true':
        connection_params['sql_mode'] = 'ALLOW_INVALID_DATES'
        connection_params['init_command'] = "SET sql_mode='ALLOW_INVALID_DATES'"

    try:
        connection = mysql.connector.connect(**connection_params)
        logging.info("Successfully connected to database")
        return connection
    except mysql.connector.Error as err:
        logging.error(f"Error connecting to database: {err}")
        return None

def mark_wpq_in_process(connection, wpq_number):
    """
    Mark WPQ as being processed (ProcessingStatus = 1).
    """
    logging.info(f"Marking WPQ {wpq_number} as in process")
    with connection.cursor() as cursor:
        query = """
        UPDATE sol_servicecalls 
        SET ProcessingStatus = 1 
        WHERE WPQNumber = %s
        """
        try:
            cursor.execute(query, (wpq_number,))
            connection.commit()
            logging.info(f"Successfully marked WPQ {wpq_number} as in process")
            return True
        except mysql.connector.Error as err:
            logging.error(f"Error marking WPQ {wpq_number} as in process: {err}")
            connection.rollback()
            return False

def release_wpq(connection, wpq_number):
    """
    Release WPQ back to available status (ProcessingStatus = 0).
    """
    logging.info(f"Releasing WPQ {wpq_number}")
    with connection.cursor() as cursor:
        query = """
        UPDATE sol_servicecalls 
        SET ProcessingStatus = 0 
        WHERE WPQNumber = %s
        """
        try:
            cursor.execute(query, (wpq_number,))
            connection.commit()
            logging.info(f"Successfully released WPQ {wpq_number}")
            return True
        except mysql.connector.Error as err:
            logging.error(f"Error releasing WPQ {wpq_number}: {err}")
            connection.rollback()
            return False

def cleanup_stuck_records(connection, hours=2):
    """
    Release records that have been stuck in ProcessingStatus = 1 for too long.
    Default is 2 hours - adjust based on your typical processing time.
    """
    logging.info(f"Cleaning up stuck records older than {hours} hours")
    with connection.cursor() as cursor:
        query = """
        UPDATE sol_servicecalls 
        SET ProcessingStatus = 0 
        WHERE ProcessingStatus = 1 
        AND LastModifiedDate < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """
        try:
            cursor.execute(query, (hours,))
            affected_rows = cursor.rowcount
            connection.commit()
            if affected_rows > 0:
                logging.warning(f"Released {affected_rows} stuck records")
            else:
                logging.info("No stuck records found")
            return affected_rows
        except mysql.connector.Error as err:
            logging.error(f"Error cleaning up stuck records: {err}")
            connection.rollback()
            return 0

def fetch_vendor_language(connection, vendor_id):
    """
    Fetch the preferred language for a vendor.
    Returns 'he' (Hebrew) as default if no language is specified.
    """
    logging.info(f"Fetching vendor language for Vendor ID: {vendor_id}")
    with connection.cursor(dictionary=True) as cursor:
        query = """
        SELECT FirstLanguage FROM sol_enterprise_vendors
        WHERE ID = %s
        """
        try:
            cursor.execute(query, (vendor_id,))
            result = cursor.fetchone()
            if result and result['FirstLanguage'] and result['FirstLanguage'].strip():
                logging.info(f"Fetched language for Vendor ID {vendor_id}: {result['FirstLanguage']}")
                return result['FirstLanguage']
            else:
                logging.info(f"No language specified for Vendor ID {vendor_id}, defaulting to Hebrew")
                return 'he'
        except mysql.connector.Error as err:
            logging.error(f"Error fetching vendor language for ID {vendor_id}: {err}")
            return 'he'

def fetch_open_pos(connection, wpq_number=None):
    """
    Fetch open POs with status 100 and ProcessingStatus = 0 (not being processed).
    If wpq_number is provided, fetch specific PO, otherwise fetch all available open POs.
    """
    logging.info(f"Fetching open POs with CallStatus 100 and ProcessingStatus 0{f' for WPQ {wpq_number}' if wpq_number else ''}")
    with connection.cursor(dictionary=True) as cursor:
        base_query = """
            SELECT 
                sc.*,
                ev.CompanyName,
                ev.Email as VendorEmail,
                ev.FirstLanguage,
                ev.VendorSetupProcessCompleted
            FROM sol_servicecalls sc
            LEFT JOIN sol_enterprise_vendors ev ON sc.VendorID = ev.ID
            WHERE sc.CallStatus = 100 
            AND sc.PQNumber IS NOT NULL 
            AND sc.PQNumber != ''
            AND sc.ProcessingStatus = 0
        """
        
        try:
            if wpq_number:
                query = f"{base_query} AND sc.WPQNumber = %s"
                cursor.execute(query, (wpq_number,))
                po = cursor.fetchone()
                if po:
                    logging.info(f"Successfully fetched available PO for WPQ {wpq_number}")
                    return po
                else:
                    logging.info(f"No available open PO found for WPQ {wpq_number} (may be in process or not open)")
                    return None
            else:
                cursor.execute(base_query)
                pos = cursor.fetchall()
                logging.info(f"Successfully fetched {len(pos)} available open POs")
                return pos
        except mysql.connector.Error as err:
            logging.error(f"Database error while fetching POs: {err}")
            return None if wpq_number else []

def fetch_po_items(connection, wpq_number):
    """
    Fetch all line items for a specific WPQ number.
    """
    logging.info(f"Fetching line items for WPQ: {wpq_number}")
    with connection.cursor(dictionary=True) as cursor:
        query = """
        SELECT * FROM sol_servicecalls_items
        WHERE WPQNumber = %s
        ORDER BY ItemID
        """
        try:
            cursor.execute(query, (wpq_number,))
            items = cursor.fetchall()
            logging.info(f"Successfully fetched {len(items)} line items for WPQ {wpq_number}")
            return items
        except mysql.connector.Error as err:
            logging.error(f"Error fetching line items for WPQ {wpq_number}: {err}")
            return []

def fetch_po_audit_logs(connection, wpq_number):
    """
    Fetch audit logs for a specific WPQ number.
    Only fetches relevant audit types (700-1200).
    """
    logging.info(f"Fetching audit logs for WPQ: {wpq_number}")
    with connection.cursor(dictionary=True) as cursor:
        query = """
        SELECT * FROM sol_servicecalls_audit_logs
        WHERE WPQNumber = %s 
        AND AuditTypeID IN (700, 800, 900, 1000, 1100, 1200)
        ORDER BY CreationDate DESC
        """
        try:
            cursor.execute(query, (wpq_number,))
            logs = cursor.fetchall()
            logging.info(f"Successfully fetched {len(logs)} audit logs for WPQ {wpq_number}")
            return logs
        except mysql.connector.Error as err:
            logging.error(f"Error fetching audit logs for WPQ {wpq_number}: {err}")
            return []

def fetch_vendor_details(connection, vendor_id):
    """
    Fetch complete vendor details for a specific vendor ID.
    """
    logging.info(f"Fetching vendor details for Vendor ID: {vendor_id}")
    with connection.cursor(dictionary=True) as cursor:
        query = """
        SELECT * FROM sol_enterprise_vendors
        WHERE ID = %s
        """
        try:
            cursor.execute(query, (vendor_id,))
            vendor = cursor.fetchone()
            if vendor:
                logging.info(f"Successfully fetched details for Vendor ID {vendor_id}")
                return vendor
            else:
                logging.info(f"No vendor found with ID {vendor_id}")
                return None
        except mysql.connector.Error as err:
            logging.error(f"Error fetching vendor details for ID {vendor_id}: {err}")
            return None