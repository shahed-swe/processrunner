#!/usr/bin/env python3
# email_notifications_linux.py

import imaplib
import email
import smtplib
import os
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import json
import time
import configparser
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# Load configuration
config = configparser.ConfigParser()
config.read('configi.ini')

# Database configuration from config.ini
DB_CONFIG = {
    'host': config['Production']['server'],
    'database': config['Production']['database'],
    'user': config['Production']['user'],
    'password': config['Production']['password']
}

# Email configuration
EMAIL_CONFIG = {
    'imap_server': config.get('Email', 'imap_server', fallback='outlook.office365.com'),
    'imap_port': config.getint('Email', 'imap_port', fallback=993),
    'smtp_server': config.get('Email', 'smtp_server', fallback='smtp.office365.com'),
    'smtp_port': config.getint('Email', 'smtp_port', fallback=587),
    'email': config.get('Email', 'email_address', fallback='po@supsol-scm.com'),
    'use_ssl': config.getboolean('Email', 'use_ssl', fallback=True)
}

# Default supporter emails (fallback)
DEFAULT_SUPPORTER_EMAILS = ["support@supsol-scm.com", "elinoamgoury@supsol-scm.com"]

def create_db_connection():
    """Create database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def print_and_log(message):
    """Print message to console with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_credentials(file_path):
    """Read email credentials from file"""
    try:
        with open(file_path, 'r') as file:
            email_addr = file.readline().strip()
            password = file.readline().strip()
        print(f"Credentials read for email: {email_addr}")
        return email_addr, password
    except Exception as e:
        print(f"Error reading credentials file: {e}")
        return None, None

def connect_to_email(email_address, password):
    """Connect to email server via IMAP"""
    try:
        if EMAIL_CONFIG['use_ssl']:
            mail = imaplib.IMAP4_SSL(EMAIL_CONFIG['imap_server'], EMAIL_CONFIG['imap_port'])
        else:
            mail = imaplib.IMAP4(EMAIL_CONFIG['imap_server'], EMAIL_CONFIG['imap_port'])
        
        mail.login(email_address, password)
        mail.select('inbox')
        print_and_log(f"✅ Connected to email server: {EMAIL_CONFIG['imap_server']}")
        return mail
    except Exception as e:
        print_and_log(f"❌ Error connecting to email server: {e}")
        return None

def decode_mime_words(s):
    """Decode MIME encoded strings"""
    try:
        decoded_parts = decode_header(s)
        decoded_string = ''
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_string += part.decode(encoding or 'utf-8')
            else:
                decoded_string += part
        return decoded_string
    except:
        return s

def get_emails_for_notification(connection):
    """Get emails that need notification - grouped by email_id"""
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Get all attachments ready for notification, grouped by email
        query = """
        SELECT email_id, 
               MAX(subject) as subject,
               MAX(sender_email) as sender_email,
               COUNT(*) as total_attachments,
               SUM(CASE WHEN current_step = 'email_notification' THEN 1 ELSE 0 END) as ready_attachments,
               SUM(CASE WHEN api_loaded = 'Y' THEN 1 ELSE 0 END) as successful_pos,
               SUM(CASE WHEN api_loaded = 'SKIPPED' THEN 1 ELSE 0 END) as skipped_attachments,
               SUM(CASE WHEN api_loaded = 'N' AND current_step = 'email_notification' THEN 1 ELSE 0 END) as failed_attachments,
               GROUP_CONCAT(DISTINCT classification_result) as all_classifications,
               GROUP_CONCAT(DISTINCT original_file_name) as all_filenames,
               MAX(CASE WHEN api_loaded = 'Y' THEN api_request_data END) as sample_api_data,
               MAX(CASE WHEN api_loaded = 'Y' THEN api_response END) as sample_api_response,
               GROUP_CONCAT(DISTINCT error_message) as error_messages,
               MAX(email_sent) as email_sent,
               MAX(retry_count) as max_retry_count
        FROM email_processing_log 
        WHERE email_sent = 'N' 
          AND current_step = 'email_notification'
          AND retry_count < 3
        GROUP BY email_id
        HAVING ready_attachments = total_attachments
        ORDER BY MAX(first_processed) ASC
        """
        
        cursor.execute(query)
        emails = cursor.fetchall()
        cursor.close()
        
        print(f"Found {len(emails)} emails ready for notification")
        return emails
        
    except Error as e:
        print(f"Error getting emails for notification: {e}")
        return []

def update_email_attachments_status(connection, email_id, **kwargs):
    """Update all attachments for an email"""
    try:
        cursor = connection.cursor()
        
        updates = []
        values = []
        
        # Add any status updates passed as keyword arguments
        for key, value in kwargs.items():
            updates.append(f"{key} = %s")
            values.append(value)
            
        # Always update last_processed timestamp
        updates.append("last_processed = %s")
        values.append(datetime.now())
        values.append(email_id)
        
        if updates:
            query = f"UPDATE email_processing_log SET {', '.join(updates)} WHERE email_id = %s"
            cursor.execute(query, values)
            connection.commit()
            print(f"Updated {cursor.rowcount} attachments for email: {email_id[:20] if len(str(email_id)) > 20 else email_id}...")
        
        cursor.close()
        return True
        
    except Error as e:
        print(f"Error updating email attachments status: {e}")
        return False

def extract_wpq_number(api_request_data):
    """Extract WPQ number from API request data"""
    try:
        if api_request_data:
            data = json.loads(api_request_data)
            wpq_number = data.get('wpqNumber')
            if wpq_number:
                return str(wpq_number)
        return None
    except Exception as e:
        print(f"Error extracting WPQ number: {e}")
        return None

def get_supporter_by_wpq(wpq_number, connection):
    """Get supporter email by WPQ number from database"""
    try:
        if not wpq_number:
            return None, None
            
        print(f"Looking up supporter for WPQ: {wpq_number}")
        
        cursor = connection.cursor(dictionary=True)
        
        # Query to find supporter by WPQ number
        query = """
        SELECT eu.EU_FullName as supporter_name, eu.EU_Email as supporter_email
        FROM sol_servicecalls sc
        JOIN sol_enterprise_users eu ON sc.SupporterID = eu.EU_UserID
        WHERE sc.WPQNumber = %s
        AND eu.EU_ActivityStatus = 1
        """
        
        cursor.execute(query, (wpq_number,))
        result = cursor.fetchone()
        cursor.close()
        
        if result and result['supporter_email']:
            print(f"Found supporter for WPQ {wpq_number}: {result['supporter_name']} ({result['supporter_email']})")
            return result['supporter_name'], result['supporter_email']
        else:
            print(f"No supporter found in database for WPQ {wpq_number}")
            return None, None
            
    except Exception as e:
        print(f"Error getting supporter for WPQ {wpq_number}: {e}")
        return None, None

def determine_recipient_emails(email_record, connection):
    """Determine recipient emails based on processing status and WPQ"""
    recipient_emails = []
    supporter_name = None
    
    try:
        # For successfully processed Purchase Orders, try to find specific supporter
        if (email_record['successful_pos'] > 0 and 
            email_record['all_classifications'] and 
            'Purchase Order' in email_record['all_classifications']):
            
            # Extract WPQ number and find supporter
            wpq_number = extract_wpq_number(email_record['sample_api_data'])
            if wpq_number:
                supporter_name, supporter_email = get_supporter_by_wpq(wpq_number, connection)
                if supporter_email:
                    recipient_emails = [supporter_email]
                    print(f"Using specific supporter: {supporter_name} ({supporter_email}) for WPQ: {wpq_number}")
                else:
                    print(f"No specific supporter found for WPQ: {wpq_number}, using default")
            else:
                print("No WPQ number found, using default supporters")
        
        # If no specific supporter found, use default
        if not recipient_emails:
            recipient_emails = DEFAULT_SUPPORTER_EMAILS
            print(f"Using default supporters: {', '.join(recipient_emails)}")
            
        return recipient_emails, supporter_name
        
    except Exception as e:
        print(f"Error determining recipient emails: {e}")
        return DEFAULT_SUPPORTER_EMAILS, None

def find_original_email_by_id(mail, email_id):
    """Find original email by message ID in inbox"""
    try:
        print(f"Searching for original email with ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}")
        
        # Search for all emails in inbox
        status, messages = mail.search(None, 'ALL')
        
        if status != 'OK':
            print("Failed to search emails")
            return None
        
        email_ids = messages[0].split()
        print(f"Searching through {len(email_ids)} emails in inbox...")
        
        for msg_id in email_ids:
            try:
                # Fetch email
                status, msg_data = mail.fetch(msg_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                # Parse email
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Check Message-ID
                message_id = msg.get('Message-ID', '')
                if message_id == email_id:
                    print(f"Found original email: {decode_mime_words(msg.get('Subject', 'No Subject'))}")
                    return msg, msg_id
                    
            except Exception as e:
                continue
        
        print(f"Original email not found with ID: {email_id[:50]}...")
        return None, None
        
    except Exception as e:
        print(f"Error finding original email: {e}")
        return None, None

def create_notification_email(email_record, recipient_emails, supporter_name, original_msg, sender_email, sender_password):
    """Create notification email with original email as attachment or forward"""
    try:
        email_id = email_record['email_id']
        subject = email_record['subject']
        sender_email_addr = email_record['sender_email']
        total_attachments = email_record['total_attachments']
        successful_pos = email_record['successful_pos']
        skipped_attachments = email_record['skipped_attachments']
        failed_attachments = email_record['failed_attachments']
        
        # Create notification email
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = ", ".join(recipient_emails)
        
        # Set subject with FW: prefix
        if not subject.upper().startswith('FW:'):
            msg['Subject'] = f"FW: {subject}"
        else:
            msg['Subject'] = subject
        
        # Create professional notification message
        wpq_number = extract_wpq_number(email_record['sample_api_data'])
        supporter_info = f"Assigned Supporter: {supporter_name}\n" if supporter_name else ""
        
        # Get file names for reference
        filenames_list = email_record['all_filenames'].split(',') if email_record['all_filenames'] else []
        file_summary = f"Files: {', '.join([f.strip() for f in filenames_list[:3]])}" if filenames_list else "Files: Not specified"
        if len(filenames_list) > 3:
            file_summary += "..."
        
        # Determine the notification message based on processing status
        if successful_pos > 0:
            if successful_pos == total_attachments:
                # All successful
                notification_message = f"""ACTION REQUIRED: Please review and validate Purchase Orders in the system portal.

Purchase Order Processing Summary:
Status: Successfully processed and loaded into system
WPQ Number: {wpq_number or 'Not specified'}
{supporter_info}Files Processed: {total_attachments}
{file_summary}

This is an automated notification. The Purchase Orders are now available for processing in the system portal.

Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}
----------------------------------------

Original Email Content:
"""
            else:
                # Mixed results
                notification_message = f"""ACTION REQUIRED: 
- Review successful Purchase Orders in the system portal
- Manually process failed items from the original email below

Purchase Order Processing Summary:
Successfully Processed: {successful_pos} of {total_attachments} files
Failed Processing: {failed_attachments}
{f'Skipped Files: {skipped_attachments}' if skipped_attachments > 0 else ''}

WPQ Number: {wpq_number or 'Not specified'}
{supporter_info}{file_summary}

This is an automated notification.

Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}
----------------------------------------

Original Email Content:
"""
                
        elif skipped_attachments > 0 and failed_attachments == 0:
            # All attachments were skipped
            notification_message = f"""ACTION REQUIRED: Please review the original email below and process files manually if they contain Purchase Orders.

Processing Summary:
Status: Files skipped - not in supported format (PDF required)
Files: {total_attachments}
{file_summary}

This is an automated notification.

Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}
----------------------------------------

Original Email Content:
"""
            
        else:
            # Some or all attachments failed
            error_details = email_record['error_messages'] or 'Processing failed - please check original email'
            notification_message = f"""ACTION REQUIRED: Manual processing needed for failed items in the original email below.

Processing Summary:
Status: Processing failed
Total Files: {total_attachments}
Failed: {failed_attachments}
{f'Successful: {successful_pos}' if successful_pos > 0 else ''}
{f'Skipped: {skipped_attachments}' if skipped_attachments > 0 else ''}

{file_summary}
Error Details: {error_details}

This is an automated notification.

Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}
----------------------------------------

Original Email Content:
"""
        
        # Add original email content
        if original_msg:
            try:
                # Get original email body
                original_body = ""
                for part in original_msg.walk():
                    if part.get_content_type() == "text/plain":
                        original_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                    elif part.get_content_type() == "text/html":
                        original_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                
                full_message = notification_message + "\n" + (original_body or "[Original email content could not be retrieved]")
            except Exception as e:
                print(f"Error extracting original email body: {e}")
                full_message = notification_message + "\n[Original email content could not be retrieved]"
        else:
            full_message = notification_message + "\n[Original email not found]"
        
        # Attach the message
        msg.attach(MIMEText(full_message, 'plain'))
        
        return msg
        
    except Exception as e:
        print(f"Error creating notification email: {e}")
        return None

def send_smtp_email(msg, sender_email, sender_password):
    """Send email via SMTP"""
    try:
        # Connect to SMTP server
        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()  # Enable encryption
        server.login(sender_email, sender_password)
        
        # Send email
        text = msg.as_string()
        server.sendmail(sender_email, msg['To'].split(", "), text)
        server.quit()
        
        print(f"Email sent successfully via SMTP")
        return True
        
    except Exception as e:
        print(f"Error sending email via SMTP: {e}")
        return False

def move_email_to_folder(mail, msg_id, folder_name="Processed"):
    """Move email to a folder (Outlook/Exchange specific)"""
    try:
        # This is a simplified version - in practice, moving emails via IMAP
        # depends on the server implementation
        # For now, we'll just mark it as read
        mail.store(msg_id, '+FLAGS', '\\Seen')
        print(f"Marked email as read (folder move not implemented for IMAP)")
        return True
        
    except Exception as e:
        print(f"Error marking email as read: {e}")
        return False

def send_notifications(connection):
    """Send professional notification emails"""
    
    # Get email credentials
    try:
        credentials_file = config['Email']['credentials_file']
        sender_email, sender_password = get_credentials(credentials_file)
        
        if not sender_email or not sender_password:
            print_and_log("Failed to get email credentials")
            return
    except Exception as e:
        print_and_log(f"Error getting credentials: {e}")
        return
    
    # Connect to email server
    mail = connect_to_email(sender_email, sender_password)
    if not mail:
        print("Could not connect to email server. Cannot send notifications.")
        return
    
    # Get emails that need notification
    emails_to_notify = get_emails_for_notification(connection)
    
    if not emails_to_notify:
        print("No emails found that need notification.")
        mail.close()
        mail.logout()
        return

    successful_notifications = 0
    failed_notifications = 0
    
    for email_record in emails_to_notify:
        email_id = email_record['email_id']
        subject = email_record['subject']
        total_attachments = email_record['total_attachments']
        successful_pos = email_record['successful_pos']
        
        print(f"\nProcessing notification for email: {subject}")
        print(f"Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}...")
        print(f"Total attachments: {total_attachments}, Successful POs: {successful_pos}")
        print(f"Skipped: {email_record['skipped_attachments']}, Failed: {email_record['failed_attachments']}")
        
        try:
            # 1. Find the original email in inbox
            original_msg, original_msg_id = find_original_email_by_id(mail, email_id)
            
            # 2. Determine recipient emails
            recipient_emails, supporter_name = determine_recipient_emails(email_record, connection)
            
            # 3. Create notification email
            notification_msg = create_notification_email(email_record, recipient_emails, supporter_name, original_msg, sender_email, sender_password)
            
            if not notification_msg:
                print(f"Failed to create notification email for: {subject}")
                update_email_attachments_status(connection, email_id,
                                               retry_count=email_record['max_retry_count'] + 1,
                                               error_message="Failed to create notification email",
                                               error_step='email_creation')
                failed_notifications += 1
                continue
            
            # 4. Send the notification email
            if send_smtp_email(notification_msg, sender_email, sender_password):
                print(f"Notification sent successfully for: {subject}")
                print(f"Recipients: {', '.join(recipient_emails)}")
                
                # 5. Update database to mark as sent
                update_email_attachments_status(connection, email_id,
                                               email_sent='Y',
                                               email_sent_at=datetime.now(),
                                               current_step='completed')
                
                # 6. Mark original email as read (or move to folder if supported)
                if original_msg_id:
                    move_email_to_folder(mail, original_msg_id, "Processed")
                
                successful_notifications += 1
            else:
                print(f"Failed to send notification for: {subject}")
                update_email_attachments_status(connection, email_id,
                                               retry_count=email_record['max_retry_count'] + 1,
                                               error_message="Failed to send notification email",
                                               error_step='email_sending')
                failed_notifications += 1
                
        except Exception as e:
            print(f"Error processing notification for {subject}: {e}")
            update_email_attachments_status(connection, email_id,
                                           retry_count=email_record['max_retry_count'] + 1,
                                           error_message=f"Notification error: {str(e)}",
                                           error_step='email_notification')
            failed_notifications += 1
        
        # Small delay between emails
        time.sleep(1)
    
    print(f"\nNotification Summary:")
    print(f"Successful: {successful_notifications}")
    print(f"Failed: {failed_notifications}")
    print(f"Total Processed: {successful_notifications + failed_notifications}")
    
    # Close email connection
    mail.close()
    mail.logout()

def main():
    """Main function"""
    connection = create_db_connection()
    if not connection:
        print("Failed to connect to database. Exiting.")
        return
    
    print_and_log("Script 5 started - Email Notifications (Linux)")
    
    try:
        print(f"Using database: {config['Production']['database']} on {config['Production']['server']}")
        
        send_notifications(connection)
        
        print_and_log("Script 5 finished - Email notification process completed")
        
    except Exception as e:
        print_and_log(f"Error in main: {e}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()