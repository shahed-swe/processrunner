#!/usr/bin/env python3
# main_mail_send_linux.py

import sys
import os
import configparser
import time
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from typing import Optional, Dict, List
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def setup_logging():
    """Setup logging configuration"""
    log_dir = os.path.expanduser("~/scripts/logs")
    os.makedirs(log_dir, mode=0o755, exist_ok=True)
    
    log_file = os.path.join(log_dir, f"mail_send_{datetime.now().strftime('%Y%m%d')}.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

def log_info(logger, message):
    """Log info message"""
    logger.info(message)

def log_error(logger, message):
    """Log error message"""
    logger.error(message)

def read_config(config_path: str) -> configparser.ConfigParser:
    """Read configuration file"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    config = configparser.ConfigParser()
    config.read(config_path)
    
    required_sections = ['Database', 'Production', 'Email', 'EmailTest']
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required section: {section}")
    
    return config

class DatabaseManager:
    """Database connection manager"""
    
    def __init__(self, connection):
        self.connection = connection
        self.cursor = connection.cursor(dictionary=True)
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict]:
        """Execute query and return results"""
        try:
            self.cursor.execute(query, params or ())
            
            if query.strip().upper().startswith('SELECT'):
                results = self.cursor.fetchall()
                return results
            else:
                # For UPDATE/INSERT queries
                self.connection.commit()
                return [{'affected_rows': self.cursor.rowcount}]
                
        except Error as e:
            log_error(logging.getLogger(__name__), f"Database query error: {e}")
            return []
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()

def connect_to_database(config_section) -> Optional[DatabaseManager]:
    """Connect to database"""
    try:
        connection = mysql.connector.connect(
            host=config_section['server'],
            database=config_section['database'],
            user=config_section['user'],
            password=config_section['password'],
            charset=config_section.get('charset', 'utf8mb4'),
            autocommit=False
        )
        
        return DatabaseManager(connection)
        
    except Error as e:
        log_error(logging.getLogger(__name__), f"Database connection error: {e}")
        return None

def close_database_connection(db_manager: DatabaseManager):
    """Close database connection"""
    if db_manager:
        db_manager.close()

def get_credentials(file_path: str) -> tuple:
    """Read email credentials from file"""
    try:
        with open(file_path, 'r') as file:
            email_addr = file.readline().strip()
            password = file.readline().strip()
        return email_addr, password
    except Exception as e:
        log_error(logging.getLogger(__name__), f"Error reading credentials: {e}")
        return None, None

def send_email(config: configparser.ConfigParser, wpq: Dict, audit: Dict, is_test: bool) -> bool:
    """Send email notification"""
    logger = logging.getLogger(__name__)
    
    try:
        # Get email credentials
        credentials_file = config['Email']['credentials_file']
        sender_email, sender_password = get_credentials(credentials_file)
        
        if not sender_email or not sender_password:
            log_error(logger, "Failed to get email credentials")
            return False
        
        # Determine recipient
        if is_test:
            recipient = config['EmailTest']['recipient_email']
            cc_recipient = config['EmailTest'].get('cc_email', '')
        else:
            # Use supporter email if available, otherwise vendor email
            recipient = wpq.get('SupporterEmail') or wpq.get('VendorEmail') or wpq.get('TempVendorEmail')
            cc_recipient = ''
        
        if not recipient:
            log_error(logger, f"No recipient email found for WPQ: {wpq['WPQNumber']}")
            return False
        
        # Create email message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient
        if cc_recipient:
            msg['Cc'] = cc_recipient
        
        # Email subject based on audit type
        audit_type_subjects = {
            100: f"WPQ {wpq['WPQNumber']} - New Service Call Created",
            700: f"WPQ {wpq['WPQNumber']} - Quote Request",
            800: f"WPQ {wpq['WPQNumber']} - Purchase Order Created", 
            900: f"WPQ {wpq['WPQNumber']} - Service Update",
            1200: f"WPQ {wpq['WPQNumber']} - Delivery Confirmation Required",
            1300: f"WPQ {wpq['WPQNumber']} - Invoice Submitted",
            1900: f"WPQ {wpq['WPQNumber']} - Service Completed"
        }
        
        msg['Subject'] = audit_type_subjects.get(audit['AuditTypeID'], f"WPQ {wpq['WPQNumber']} - Service Notification")
        
        # Email body
        vendor_name = wpq.get('VendorName') or wpq.get('TempVendorName', 'Vendor')
        supporter_name = wpq.get('SupporterName', 'Support Team')
        
        email_body = f"""
Dear {vendor_name},

WPQ Number: {wpq['WPQNumber']}
PO Number: {wpq.get('PONumber', 'N/A')}
Creation Date: {wpq['CreationDate']}
Urgency: {wpq.get('UrgencyType', 'Standard')}
Supporter: {supporter_name}

Message:
{audit.get('EnglishText') or audit.get('Text', 'No message content')}

Please respond promptly to this service call.

This is an automated notification from the SupSol system.

Best regards,
SupSol Support Team
"""
        
        if is_test:
            email_body = f"[TEST MODE]\n\n{email_body}"
        
        msg.attach(MIMEText(email_body, 'plain'))
        
        # Send email via SMTP
        smtp_server = config['Email'].get('smtp_server', 'smtp.office365.com')
        smtp_port = config['Email'].getint('smtp_port', 587)
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        
        recipients = [recipient]
        if cc_recipient:
            recipients.append(cc_recipient)
        
        text = msg.as_string()
        server.sendmail(sender_email, recipients, text)
        server.quit()
        
        log_info(logger, f"Email sent successfully to {recipient} for WPQ: {wpq['WPQNumber']}, Audit: {audit['ID']}")
        return True
        
    except Exception as e:
        log_error(logger, f"Error sending email: {e}")
        return False

def get_environment() -> str:
    """Get user's choice of environment"""
    while True:
        print("\nSelect environment:")
        print("1. Production")
        print("2. Development")
        choice = input("Enter choice (1/2): ").strip()
        
        if choice == '1':
            return 'Production'
        elif choice == '2':
            return 'Database'
        
        print("Invalid choice. Please enter 1 or 2.")

def get_unprocessed_wpqs(db_manager: DatabaseManager) -> List[Dict]:
    """Fetch unprocessed WPQs with vendor information"""
    query = """
    SELECT DISTINCT 
        sc.WPQNumber,
        sc.PONumber,
        sc.CreationDate,
        sc.UrgencyType,
        sc.VendorID,
        sc.TempVendorEmail,
        sc.TempVendorName,
        eu.EU_FullName as SupporterName,
        eu.EU_Email as SupporterEmail,
        v.Email as VendorEmail,
        v.CompanyName as VendorName,
        v.FirstLanguage
    FROM 
        sol_servicecalls sc
    LEFT JOIN 
        sol_enterprise_users eu ON sc.SupporterID = eu.EU_UserID
    LEFT JOIN 
        sol_enterprise_vendors v ON sc.VendorID = v.ID
    WHERE 
        sc.CallStatus IN (0, 20, 40, 100)
        AND sc.CreationDate >= '2024-05-01'
        AND EXISTS (
            SELECT 1 
            FROM sol_servicecalls_audit_logs sal 
            WHERE sal.WPQNumber = sc.WPQNumber 
            AND sal.AuditTypeID IN (100, 700, 800, 900, 1200, 1300, 1900)
            AND (sal.ExecutionStatus IS NULL OR sal.ExecutionStatus != 999)
        )
    ORDER BY 
        CASE WHEN sc.UrgencyType != 'Standard' THEN 0 ELSE 1 END,
        sc.CreationDate DESC
    LIMIT 50
    """
    
    results = db_manager.execute_query(query)
    return results if results else []

def get_audit_logs(db_manager: DatabaseManager, wpq_number: str) -> List[Dict]:
    """Fetch audit logs for a WPQ"""
    query = """
    SELECT 
        ID,
        Text,
        EnglishText,
        AuditTypeID
    FROM 
        sol_servicecalls_audit_logs
    WHERE 
        WPQNumber = %s
        AND AuditTypeID IN (100, 700, 800, 900, 1200, 1300, 1900)
        AND (ExecutionStatus IS NULL OR ExecutionStatus != 999)
    ORDER BY 
        CreationDate DESC
    """
    
    results = db_manager.execute_query(query, (wpq_number,))
    return results if results else []

def update_audit_status(db_manager: DatabaseManager, audit_id: int) -> bool:
    """Update audit log status after email is sent"""
    query = """
    UPDATE sol_servicecalls_audit_logs
    SET ExecutionStatus = 999,
        LastModifiedDate = NOW()
    WHERE ID = %s
    """
    
    results = db_manager.execute_query(query, (audit_id,))
    return bool(results and results[0].get('affected_rows', 0) > 0)

def main():
    """Main function to process WPQs and send emails"""
    logger = setup_logging()
    log_info(logger, "Starting WPQ processor (Linux)")
    
    try:
        # Load configuration - look in same directory as script
        config_path = os.path.join(os.path.dirname(__file__), "configi.ini")
        if not os.path.exists(config_path):
            # Fallback to current directory
            config_path = "configi.ini"
        
        config = read_config(config_path)
        log_info(logger, f"Loaded config from: {config_path}")
        
        # Get environment choice
        env = get_environment()
        log_info(logger, f"Selected environment: {env}")
        
        # Get test mode choice
        is_test = input("Is this a test run? (y/n): ").lower().strip() == 'y'
        log_info(logger, f"Test mode: {is_test}")
        
        # Connect to database
        db_manager = connect_to_database(config[env])
        if not db_manager:
            log_error(logger, "Failed to connect to database")
            return 1
        
        log_info(logger, f"Connected to database: {config[env]['database']}")
        
        try:
            processed_count = 0
            
            while True:
                # Get unprocessed WPQs
                wpqs = get_unprocessed_wpqs(db_manager)
                if not wpqs:
                    log_info(logger, "No more WPQs to process")
                    break
                
                log_info(logger, f"Found {len(wpqs)} WPQs to process")
                
                # Process each WPQ
                for wpq in wpqs:
                    try:
                        # Get audit logs for this WPQ
                        audits = get_audit_logs(db_manager, wpq['WPQNumber'])
                        if not audits:
                            log_info(logger, f"No audit logs found for WPQ: {wpq['WPQNumber']}")
                            continue
                        
                        # Process each audit log
                        for audit in audits:
                            try:
                                # Send email
                                if send_email(config, wpq, audit, is_test):
                                    # Update audit status
                                    if update_audit_status(db_manager, audit['ID']):
                                        log_info(logger, f"Successfully processed audit {audit['ID']} (Type: {audit['AuditTypeID']}) for WPQ: {wpq['WPQNumber']}")
                                        processed_count += 1
                                    else:
                                        log_error(logger, f"Failed to update audit {audit['ID']} for WPQ: {wpq['WPQNumber']}")
                                else:
                                    log_error(logger, f"Failed to send email for audit {audit['ID']}, WPQ: {wpq['WPQNumber']}")
                                
                                # Small delay between emails
                                time.sleep(2)
                                    
                            except Exception as e:
                                log_error(logger, f"Error processing audit {audit['ID']}: {str(e)}")
                                continue
                                
                    except Exception as e:
                        log_error(logger, f"Error processing WPQ {wpq['WPQNumber']}: {str(e)}")
                        continue
                
                # Brief pause between batches
                time.sleep(5)
                
        finally:
            close_database_connection(db_manager)
            log_info(logger, "Database connection closed")
            
    except KeyboardInterrupt:
        log_info(logger, "Process interrupted by user")
        return 0
    except Exception as e:
        log_error(logger, f"Fatal error: {str(e)}")
        return 1
    
    log_info(logger, f"Process completed successfully. Processed {processed_count} notifications.")
    return 0

if __name__ == "__main__":
    sys.exit(main())