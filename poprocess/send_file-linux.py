#send_file_linux-grpah#!/usr/bin/env python3
# email_notifications_graph_linux.py - Using Microsoft Graph API

import os
import requests
import msal
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import json
import time
import configparser
import base64
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

# Graph API configuration
try:
    GRAPH_CONFIG = {
        'client_id': config['GraphAPI']['client_id'],
        'client_secret': config['GraphAPI']['client_secret'],
        'tenant_id': config['GraphAPI']['tenant_id'],
        'user_email': config['GraphAPI']['user_email']  # po@supsol-scm.com
    }
except KeyError:
    print("ERROR: Missing [GraphAPI] section in configi.ini!")
    print("Please add GraphAPI configuration section")
    exit(1)

# Default supporter emails (fallback)
DEFAULT_SUPPORTER_EMAILS = ["support@supsol-scm.com", "elinoamgoury@supsol-scm.com"]

class GraphEmailSender:
    """Microsoft Graph API client for sending emails"""
    
    def __init__(self):
        self.access_token = None
        self.token_expires_at = None
        
    def _get_access_token(self):
        """Get or refresh access token"""
        try:
            if self.access_token and self.token_expires_at:
                if time.time() < self.token_expires_at - 300:  # 5 min buffer
                    return self.access_token
            
            app = msal.ConfidentialClientApplication(
                client_id=GRAPH_CONFIG['client_id'],
                client_credential=GRAPH_CONFIG['client_secret'],
                authority=f"https://login.microsoftonline.com/{GRAPH_CONFIG['tenant_id']}"
            )
            
            result = app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
            
            if "access_token" in result:
                self.access_token = result["access_token"]
                expires_in = result.get("expires_in", 3600)
                self.token_expires_at = time.time() + expires_in
                logger.info("Successfully obtained Graph API access token")
                return self.access_token
            else:
                logger.error(f"Failed to get access token: {result.get('error_description', 'Unknown error')}")
                return None
                
        except Exception as e:
            logger.error(f"Exception getting access token: {e}")
            return None
    
    def find_original_email_by_message_id(self, message_id):
        """Find original email by internet message ID"""
        access_token = self._get_access_token()
        if not access_token:
            return None
        
        try:
            # Search for email by internetMessageId
            url = f"https://graph.microsoft.com/v1.0/users/{GRAPH_CONFIG['user_email']}/messages"
            
            headers = {
                'Authorization': f'Bearer {access_token}'
            }
            
            # Filter by internetMessageId
            params = {
                '$filter': f"internetMessageId eq '{message_id}'",
                '$select': 'id,subject,from,receivedDateTime,body,internetMessageId',
                '$top': 1
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                emails = response.json().get('value', [])
                if emails:
                    logger.info(f"Found original email: {emails[0].get('subject', 'No Subject')}")
                    return emails[0]
                else:
                    logger.warning(f"Original email not found with message ID: {message_id[:50]}...")
                    return None
            else:
                logger.error(f"Failed to search for original email: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Exception finding original email: {e}")
            return None
    
    def forward_email_with_comment(self, original_email_id, to_recipients, comment):
        """Forward original email with comment using Graph API native forward"""
        access_token = self._get_access_token()
        if not access_token:
            return False
        
        try:
            url = f"https://graph.microsoft.com/v1.0/users/{GRAPH_CONFIG['user_email']}/messages/{original_email_id}/forward"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Build recipients list
            to_recipients_list = [{"emailAddress": {"address": email}} for email in to_recipients]
            
            # Build forward data
            forward_data = {
                "toRecipients": to_recipients_list,
                "comment": comment
            }
            
            response = requests.post(url, headers=headers, json=forward_data)
            
            if response.status_code == 202:  # Accepted
                logger.info(f"Email forwarded successfully using Graph API")
                return True
            else:
                logger.error(f"Failed to forward email: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception forwarding email: {e}")
            return False
    
    def send_notification_email(self, to_recipients, subject, message_content):
        """Send notification email using Graph API"""
        access_token = self._get_access_token()
        if not access_token:
            return False
        
        try:
            url = f"https://graph.microsoft.com/v1.0/users/{GRAPH_CONFIG['user_email']}/sendMail"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Build recipients list
            to_recipients_list = [{"emailAddress": {"address": email}} for email in to_recipients]
            
            # Build email message
            email_message = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "Text",
                        "content": message_content
                    },
                    "toRecipients": to_recipients_list,
                    "from": {
                        "emailAddress": {
                            "address": GRAPH_CONFIG['user_email']
                        }
                    }
                }
            }
            
            response = requests.post(url, headers=headers, json=email_message)
            
            if response.status_code == 202:  # Accepted
                logger.info(f"Notification email sent successfully")
                return True
            else:
                logger.error(f"Failed to send notification email: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception sending notification email: {e}")
            return False
    
    def mark_email_as_read(self, email_id):
        """Mark email as read"""
        access_token = self._get_access_token()
        if not access_token:
            return False
        
        try:
            url = f"https://graph.microsoft.com/v1.0/users/{GRAPH_CONFIG['user_email']}/messages/{email_id}"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            data = {
                "isRead": True
            }
            
            response = requests.patch(url, headers=headers, json=data)
            
            if response.status_code == 200:
                logger.info(f"Marked email as read: {email_id[:10]}...")
                return True
            else:
                logger.error(f"Failed to mark email as read: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Exception marking email as read: {e}")
            return False

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

def create_notification_message(email_record, supporter_name):
    """Create professional notification message"""
    try:
        email_id = email_record['email_id']
        subject = email_record['subject']
        sender_email_addr = email_record['sender_email']
        total_attachments = email_record['total_attachments']
        successful_pos = email_record['successful_pos']
        skipped_attachments = email_record['skipped_attachments']
        failed_attachments = email_record['failed_attachments']
        
        # Get file names for reference
        filenames_list = email_record['all_filenames'].split(',') if email_record['all_filenames'] else []
        file_summary = f"Files: {', '.join([f.strip() for f in filenames_list[:3]])}" if filenames_list else "Files: Not specified"
        if len(filenames_list) > 3:
            file_summary += "..."
        
        # Extract WPQ info
        wpq_number = extract_wpq_number(email_record['sample_api_data'])
        supporter_info = f"Assigned Supporter: {supporter_name}\n" if supporter_name else ""
        
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

Original Email Subject: {subject}
From: {sender_email_addr}
Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}

Please check the system portal for the processed Purchase Orders and take appropriate action.
"""
            else:
                # Mixed results
                notification_message = f"""ACTION REQUIRED: 
- Review successful Purchase Orders in the system portal
- Manually process failed items from the original email

Purchase Order Processing Summary:
Successfully Processed: {successful_pos} of {total_attachments} files
Failed Processing: {failed_attachments}
{f'Skipped Files: {skipped_attachments}' if skipped_attachments > 0 else ''}

WPQ Number: {wpq_number or 'Not specified'}
{supporter_info}{file_summary}

Original Email Subject: {subject}
From: {sender_email_addr}
Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}

This is an automated notification. Please check both the system portal and the original email.
"""
                
        elif skipped_attachments > 0 and failed_attachments == 0:
            # All attachments were skipped
            notification_message = f"""ACTION REQUIRED: Please review the original email and process files manually if they contain Purchase Orders.

Processing Summary:
Status: Files skipped - not in supported format (PDF required)
Files: {total_attachments}
{file_summary}

Original Email Subject: {subject}
From: {sender_email_addr}
Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}

This is an automated notification. The original email may contain Purchase Orders that need manual processing.
"""
            
        else:
            # Some or all attachments failed
            error_details = email_record['error_messages'] or 'Processing failed - please check original email'
            notification_message = f"""ACTION REQUIRED: Manual processing needed for failed items.

Processing Summary:
Status: Processing failed
Total Files: {total_attachments}
Failed: {failed_attachments}
{f'Successful: {successful_pos}' if successful_pos > 0 else ''}
{f'Skipped: {skipped_attachments}' if skipped_attachments > 0 else ''}

{file_summary}
Error Details: {error_details}

Original Email Subject: {subject}
From: {sender_email_addr}
Email ID: {email_id[:50] if len(str(email_id)) > 50 else email_id}

This is an automated notification. Please manually review and process the original email.
"""
        
        return notification_message
        
    except Exception as e:
        print(f"Error creating notification message: {e}")
        return f"Error creating notification for email: {email_record.get('subject', 'Unknown')}"

def send_notifications_with_graph(connection):
    """Send professional notification emails using Graph API"""
    
    # Initialize Graph API client
    graph_client = GraphEmailSender()
    
    # Get emails that need notification
    emails_to_notify = get_emails_for_notification(connection)
    
    if not emails_to_notify:
        print("No emails found that need notification.")
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
            # 1. Determine recipient emails
            recipient_emails, supporter_name = determine_recipient_emails(email_record, connection)
            
            # 2. Create notification message
            notification_message = create_notification_message(email_record, supporter_name)
            
            # 3. Create subject with FW: prefix
            notification_subject = f"FW: {subject}" if not subject.upper().startswith('FW:') else subject
            
            # 4. Try to find and forward original email, or send new notification
            original_email = graph_client.find_original_email_by_message_id(email_id)
            
            email_sent = False
            
            if original_email and original_email.get('id'):
                # Forward original email with notification comment
                print(f"Forwarding original email with notification comment")
                if graph_client.forward_email_with_comment(
                    original_email['id'], 
                    recipient_emails, 
                    notification_message
                ):
                    email_sent = True
                    print(f"Original email forwarded with notification")
                    
                    # Mark original as read
                    graph_client.mark_email_as_read(original_email['id'])
                else:
                    print(f"Failed to forward original email, sending notification")
            
            # If forwarding failed or original not found, send notification email
            if not email_sent:
                print(f"Sending notification email")
                if graph_client.send_notification_email(
                    recipient_emails, 
                    notification_subject, 
                    notification_message
                ):
                    email_sent = True
                    print(f"Notification email sent successfully")
                else:
                    print(f"Failed to send notification email")
            
            if email_sent:
                print(f"Notification sent successfully for: {subject}")
                print(f"Recipients: {', '.join(recipient_emails)}")
                
                # Update database to mark as sent
                update_email_attachments_status(connection, email_id,
                                               email_sent='Y',
                                               email_sent_at=datetime.now(),
                                               current_step='completed')
                
                successful_notifications += 1
            else:
                print(f"Failed to send notification for: {subject}")
                update_email_attachments_status(connection, email_id,
                                               retry_count=email_record['max_retry_count'] + 1,
                                               error_message="Failed to send notification via Graph API",
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

def main():
    """Main function"""
    connection = create_db_connection()
    if not connection:
        print("Failed to connect to database. Exiting.")
        return
    
    print_and_log("Script 5 started - Email Notifications using Graph API (Linux)")
    
    try:
        print(f"Using database: {config['Production']['database']} on {config['Production']['server']}")
        print(f"Using Graph API user: {GRAPH_CONFIG['user_email']}")
        
        send_notifications_with_graph(connection)
        
        print_and_log("Script 5 finished - Email notification process using Graph API completed")
        
    except Exception as e:
        print_and_log(f"Error in main: {e}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()