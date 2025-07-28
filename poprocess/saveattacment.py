#saveattacment-grpah
#!/usr/bin/env python3
# saveattachment_graph_linux.py - Using Microsoft Graph API

import os
import requests
import msal
import mysql.connector
from mysql.connector import Error
import mimetypes
from datetime import datetime, timedelta
import configparser
import base64
import time
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

# Graph API configuration - Add this section to your configi.ini
try:
    GRAPH_CONFIG = {
        'client_id': config['GraphAPI']['client_id'],
        'client_secret': config['GraphAPI']['client_secret'],
        'tenant_id': config['GraphAPI']['tenant_id'],
        'user_email': config['GraphAPI']['user_email']  # po@supsol-scm.com
    }
except KeyError:
    print("ERROR: Missing [GraphAPI] section in configi-linux.ini!")
    print("Please add:")
    print("[GraphAPI]")
    print("client_id = your_client_id")
    print("client_secret = your_client_secret") 
    print("tenant_id = your_tenant_id")
    print("user_email = po@supsol-scm.com")
    exit(1)

class GraphEmailProcessor:
    """Microsoft Graph API client for email processing"""
    
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
    
    def get_unread_emails_last_48h(self):
        """Get unread emails from last 48 hours using Graph API"""
        access_token = self._get_access_token()
        if not access_token:
            return []
        
        try:
            # Calculate date 48 hours ago
            hours_48_ago = datetime.now() - timedelta(hours=48)
            filter_date = hours_48_ago.isoformat() + 'Z'
            
            url = f"https://graph.microsoft.com/v1.0/users/{GRAPH_CONFIG['user_email']}/messages"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Filter for unread emails from last 48 hours with attachments
            params = {
                '$filter': f"isRead eq false and receivedDateTime ge {filter_date} and hasAttachments eq true",
                '$select': 'id,subject,from,receivedDateTime,hasAttachments,internetMessageId,bodyPreview',
                '$orderby': 'receivedDateTime desc',
                '$top': 50  # Limit to 50 emails
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                emails = response.json().get('value', [])
                logger.info(f"Found {len(emails)} unread emails with attachments from last 48 hours")
                return emails
            else:
                logger.error(f"Failed to get emails: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Exception getting emails: {e}")
            return []
    
    def get_email_attachments(self, email_id):
        """Get attachments for a specific email"""
        access_token = self._get_access_token()
        if not access_token:
            return []
        
        try:
            url = f"https://graph.microsoft.com/v1.0/users/{GRAPH_CONFIG['user_email']}/messages/{email_id}/attachments"
            
            headers = {
                'Authorization': f'Bearer {access_token}'
            }
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                attachments = response.json().get('value', [])
                logger.info(f"Found {len(attachments)} attachments for email {email_id[:10]}...")
                return attachments
            else:
                logger.error(f"Failed to get attachments: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Exception getting attachments: {e}")
            return []
    
    def download_attachment(self, email_id, attachment_id, save_path):
        """Download attachment content and save to file"""
        access_token = self._get_access_token()
        if not access_token:
            return False
        
        try:
            url = f"https://graph.microsoft.com/v1.0/users/{GRAPH_CONFIG['user_email']}/messages/{email_id}/attachments/{attachment_id}"
            
            headers = {
                'Authorization': f'Bearer {access_token}'
            }
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                attachment_data = response.json()
                
                # Get content bytes
                if 'contentBytes' in attachment_data:
                    content_bytes = base64.b64decode(attachment_data['contentBytes'])
                    
                    # Save to file
                    with open(save_path, 'wb') as f:
                        f.write(content_bytes)
                    
                    logger.info(f"Downloaded attachment to: {save_path}")
                    return True
                else:
                    logger.error("No contentBytes in attachment data")
                    return False
            else:
                logger.error(f"Failed to download attachment: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception downloading attachment: {e}")
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

def check_file_type(file_path):
    """Check file type and return file information"""
    result = {
        'file_path': file_path,
        'file_name': os.path.basename(file_path),
        'extension': None,
        'mime_type': None,
        'is_pdf': False,
        'is_supported': False,
        'file_size': 0,
        'error': None
    }
    
    try:
        if not os.path.exists(file_path):
            result['error'] = 'File does not exist'
            return result
            
        # Get file size
        result['file_size'] = os.path.getsize(file_path)
        
        # Get extension
        _, extension = os.path.splitext(file_path.lower())
        result['extension'] = extension
        
        # Get MIME type
        mime_type, _ = mimetypes.guess_type(file_path)
        result['mime_type'] = mime_type
        
        # Check if it's PDF
        result['is_pdf'] = (extension == '.pdf' or mime_type == 'application/pdf')
        
        # Check if file is supported - PDF files only
        supported_extensions = ['.pdf']
        result['is_supported'] = extension in supported_extensions
        
        # Additional PDF verification by header
        if result['is_pdf']:
            try:
                with open(file_path, 'rb') as file:
                    header = file.read(4)
                    if header != b'%PDF':
                        result['is_pdf'] = False
                        result['error'] = 'File extension is PDF but header is invalid'
            except Exception as e:
                result['error'] = f'Could not verify PDF header: {e}'
                
    except Exception as e:
        result['error'] = f'Error checking file: {e}'
    
    return result

def is_po_related_filename(filename):
    """Check if filename suggests it's PO-related"""
    po_keywords = [
        'po', 'purchase.order', 'order', 'requisition', 
        'procurement', 'buying', 'invoice', 'quote', 'rfq'
    ]
    
    filename_lower = filename.lower()
    return any(keyword in filename_lower for keyword in po_keywords)

def filter_attachments_for_po(attachments):
    """Filter attachments that might be PO-related - PDF files only"""
    po_attachments = []
    
    for attachment in attachments:
        filename = attachment.get('name', '')
        content_type = attachment.get('contentType', '')
        
        if not filename:
            continue
            
        # Only process PDF files - skip all image files
        if not filename.lower().endswith('.pdf'):
            continue
            
        # Check if filename suggests PO content
        if is_po_related_filename(filename):
            po_attachments.append(attachment)
            continue
            
        # Include PDF files for AI analysis (even if filename doesn't clearly indicate PO)
        po_attachments.append(attachment)
    
    return po_attachments

def check_attachment_exists(connection, email_id, attachment_sequence):
    """Check if attachment record already exists"""
    try:
        cursor = connection.cursor()
        
        check_query = "SELECT pdf_extracted FROM email_processing_log WHERE email_id = %s AND attachment_sequence = %s"
        cursor.execute(check_query, (email_id, attachment_sequence))
        result = cursor.fetchone()
        cursor.close()
        
        if result and result[0] == 'Y':  # Already successfully processed
            return True, True  # exists, processed
        elif result:
            return True, False  # exists, not processed
        else:
            return False, False  # doesn't exist
            
    except Error as e:
        print(f"Error checking attachment existence: {e}")
        return False, False

def insert_attachment_record(connection, email_data, attachment_sequence):
    """Insert new attachment record"""
    try:
        cursor = connection.cursor()
        
        insert_query = """
        INSERT INTO email_processing_log (
            email_id, attachment_sequence, subject, sender_email, received_date, 
            attachment_count, po_attachments_found, current_step, first_processed, last_processed
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(insert_query, (
            email_data['email_id'],
            attachment_sequence,
            email_data['subject'],
            email_data['sender_email'],
            email_data['received_date'],
            email_data['attachment_count'],
            email_data['po_attachments_found'],
            'pdf_extraction',
            datetime.now(),
            datetime.now()
        ))
        
        connection.commit()
        cursor.close()
        print(f"Inserted attachment record: {email_data['subject']} - Attachment {attachment_sequence}")
        return True
        
    except Error as e:
        print(f"Error inserting attachment record: {e}")
        return False

def update_attachment_status(connection, email_id, attachment_sequence, **kwargs):
    """Update attachment processing status in database"""
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
        values.append(attachment_sequence)
        
        if updates:
            query = f"UPDATE email_processing_log SET {', '.join(updates)} WHERE email_id = %s AND attachment_sequence = %s"
            cursor.execute(query, values)
            connection.commit()
        
        cursor.close()
        return True
        
    except Error as e:
        print(f"Error updating attachment status: {e}")
        return False

def update_attachment_file_record(connection, email_id, attachment_sequence, file_data):
    """Update attachment record with file information"""
    try:
        cursor = connection.cursor()
        
        update_query = """
        UPDATE email_processing_log 
        SET original_file_name = %s, original_file_path = %s, file_type = %s, 
            file_size = %s, mime_type = %s, pdf_extracted = %s, 
            pdf_extracted_at = %s, current_step = %s
        WHERE email_id = %s AND attachment_sequence = %s
        """
        
        cursor.execute(update_query, (
            file_data['original_file_name'],
            file_data['original_file_path'],
            file_data['file_type'],
            file_data['file_size'],
            file_data['mime_type'],
            'Y',
            datetime.now(),
            'text_conversion',
            email_id,
            attachment_sequence
        ))
        
        connection.commit()
        cursor.close()
        return True
        
    except Error as e:
        print(f"Error updating attachment file record: {e}")
        return False

def process_emails_with_graph_api(connection, save_folder):
    """Process emails using Microsoft Graph API"""
    print_and_log("Starting email processing with Graph API")
    
    # Initialize Graph API client
    graph_client = GraphEmailProcessor()
    
    # Get unread emails from last 48 hours
    emails = graph_client.get_unread_emails_last_48h()
    
    if not emails:
        print_and_log("No unread emails with attachments found from last 48 hours")
        return
    
    processed_emails = 0
    
    for email_data in emails:
        try:
            email_id = email_data['id']
            internet_message_id = email_data.get('internetMessageId', f'graph_{email_id}')
            subject = email_data.get('subject', 'No Subject')
            sender = email_data.get('from', {})
            sender_email = sender.get('emailAddress', {}).get('address', 'Unknown') if sender else 'Unknown'
            received_date = email_data.get('receivedDateTime', '')
            
            print_and_log(f"Processing email: {subject} from {sender_email}")
            print_and_log(f"Email ID: {email_id}")
            
            # Get attachments for this email
            attachments = graph_client.get_email_attachments(email_id)
            
            if not attachments:
                print_and_log(f"No attachments found for email: {subject}")
                continue
            
            # Filter for PO-related attachments
            po_attachments = filter_attachments_for_po(attachments)
            
            print_and_log(f"Found {len(attachments)} total attachments, {len(po_attachments)} PO-related")
            
            # ONLY process emails that have PO-related attachments
            if len(po_attachments) == 0:
                print_and_log(f"❌ No PO-related attachments found - SKIPPING email: {subject}")
                continue
            
            # Prepare email data for database
            email_record = {
                'email_id': internet_message_id,
                'subject': subject,
                'sender_email': sender_email,
                'received_date': datetime.now(),  # Could parse the actual date
                'attachment_count': len(attachments),
                'po_attachments_found': len(po_attachments)
            }
            
            # Process each PO-related attachment separately
            processed_attachments = 0
            attachment_sequence = 1
            
            for attachment in po_attachments:
                attachment_id = attachment['id']
                original_filename = attachment['name']
                content_type = attachment.get('contentType', '')
                size = attachment.get('size', 0)
                
                print_and_log(f"Processing attachment {attachment_sequence}: {original_filename}")
                
                # Check if this attachment already exists in database
                exists, processed = check_attachment_exists(connection, internet_message_id, attachment_sequence)
                
                if exists and processed:
                    print_and_log(f"Attachment {attachment_sequence} already processed successfully: {original_filename}")
                    attachment_sequence += 1
                    continue
                
                # Create unique filename to avoid conflicts
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_name, extension = os.path.splitext(original_filename)
                unique_filename = f"{base_name}_{timestamp}_{attachment_sequence}{extension}"
                attachment_path = os.path.join(save_folder, unique_filename)
                
                try:
                    # Download attachment using Graph API
                    if graph_client.download_attachment(email_id, attachment_id, attachment_path):
                        print_and_log(f"Downloaded attachment: {unique_filename}")
                        
                        # Check file type
                        file_info = check_file_type(attachment_path)
                        
                        if file_info['error']:
                            print_and_log(f"File check error for {unique_filename}: {file_info['error']}")
                            # Clean up bad file
                            try:
                                os.remove(attachment_path)
                            except:
                                pass
                            attachment_sequence += 1
                            continue
                        
                        # Insert or update attachment record in database
                        if not exists:
                            if not insert_attachment_record(connection, email_record, attachment_sequence):
                                print_and_log(f"Failed to insert database record for attachment {attachment_sequence}")
                                attachment_sequence += 1
                                continue
                        
                        # Update database with file information
                        file_data = {
                            'original_file_name': unique_filename,
                            'original_file_path': attachment_path,
                            'file_type': file_info['extension'].upper().replace('.', '') if file_info['extension'] else 'UNKNOWN',
                            'file_size': file_info['file_size'],
                            'mime_type': file_info['mime_type']
                        }
                        
                        if update_attachment_file_record(connection, internet_message_id, attachment_sequence, file_data):
                            print_and_log(f"Updated database record for attachment {attachment_sequence}: {unique_filename}")
                            processed_attachments += 1
                        else:
                            print_and_log(f"Failed to update database for attachment {attachment_sequence}: {unique_filename}")
                            update_attachment_status(connection, internet_message_id, attachment_sequence,
                                                    error_message="Failed to update file record", 
                                                    error_step='database_update')
                    else:
                        print_and_log(f"Failed to download attachment {attachment_sequence}: {original_filename}")
                        update_attachment_status(connection, internet_message_id, attachment_sequence,
                                                error_message="Failed to download attachment", 
                                                error_step='attachment_download')
                        
                except Exception as e:
                    print_and_log(f"Error processing attachment {attachment_sequence} ({original_filename}): {e}")
                    update_attachment_status(connection, internet_message_id, attachment_sequence,
                                            error_message=f"Attachment error: {str(e)}", 
                                            error_step='attachment_processing')
                
                attachment_sequence += 1
            
            if processed_attachments > 0:
                print_and_log(f"✅ Processed {processed_attachments} attachments for email: {subject}")
                processed_emails += 1
                
                # Mark email as read after successful processing
                graph_client.mark_email_as_read(email_id)
            else:
                print_and_log(f"No attachments processed successfully for email: {subject}")
            
        except Exception as e:
            print_and_log(f"Error processing email: {e}")
    
    print_and_log(f"Total emails processed: {processed_emails}")

def main():
    """Main function"""
    print_and_log("Script 1 started - Email PDF Attachments Extraction using Graph API (Linux)")
    
    # Test configuration loading
    try:
        print(f"Loaded config - Database: {config['Production']['database']}")
        print(f"Loaded config - Server: {config['Production']['server']}")
        print(f"Loaded config - Graph User: {GRAPH_CONFIG['user_email']}")
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return
    
    connection = create_db_connection()
    if not connection:
        print("Failed to connect to database. Exiting.")
        return
    
    try:
        # Use Linux-compatible path
        save_folder = os.path.expanduser('~/scripts/PO')
        
        if not os.path.exists(save_folder):
            os.makedirs(save_folder, mode=0o755)
            print_and_log(f"Created directory: {save_folder}")

        print_and_log("Processing emails with Graph API and saving PDF attachments only from unread emails (last 48 hours)")
        process_emails_with_graph_api(connection, save_folder)

        print_and_log("Script 1 finished - Email PDF Attachments Extraction using Graph API completed")
        
    except Exception as e:
        print_and_log(f"Error in main: {e}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()