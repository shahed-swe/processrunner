#!/usr/bin/env python3
# saveattachment_multi_linux.py

import imaplib
import email
import os
import mysql.connector
from mysql.connector import Error
import mimetypes
from datetime import datetime, timedelta
import configparser
from email.header import decode_header

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
    'server': config.get('Email', 'imap_server', fallback='imap.gmail.com'),
    'port': config.getint('Email', 'imap_port', fallback=993),
    'email': config.get('Email', 'email_address', fallback='po@supsol-scm.com'),
    'use_ssl': config.getboolean('Email', 'use_ssl', fallback=True)
}

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
            mail = imaplib.IMAP4_SSL(EMAIL_CONFIG['server'], EMAIL_CONFIG['port'])
        else:
            mail = imaplib.IMAP4(EMAIL_CONFIG['server'], EMAIL_CONFIG['port'])
        
        mail.login(email_address, password)
        mail.select('inbox')
        print_and_log(f"✅ Connected to email server: {EMAIL_CONFIG['server']}")
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

def get_unread_emails_last_48h(mail):
    """Get unread emails from last 48 hours"""
    try:
        # Calculate date 48 hours ago
        hours_48_ago = datetime.now() - timedelta(hours=48)
        date_filter = hours_48_ago.strftime("%d-%b-%Y")
        
        # Search for unread emails since 48 hours ago
        search_criteria = f'(UNSEEN SINCE "{date_filter}")'
        print_and_log(f"Searching for unread emails since: {date_filter}")
        
        status, messages = mail.search(None, search_criteria)
        
        if status != 'OK':
            print_and_log("❌ Failed to search emails")
            return []
        
        email_ids = messages[0].split()
        print_and_log(f"Found {len(email_ids)} unread emails from last 48 hours")
        
        return email_ids
    except Exception as e:
        print_and_log(f"Error searching emails: {e}")
        return []

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
        
        # Check if file is supported
        supported_extensions = ['.pdf', '.doc', '.docx', '.txt', '.jpg', '.jpeg', '.png', '.tiff']
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

def filter_attachments_for_po(msg):
    """Filter attachments that might be PO-related"""
    po_attachments = []
    
    for part in msg.walk():
        if part.get_content_disposition() == 'attachment':
            filename = part.get_filename()
            if not filename:
                continue
                
            filename = decode_mime_words(filename)
            
            # Check file extension
            if not filename.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.doc', '.docx')):
                continue
                
            # Check if filename suggests PO content
            if is_po_related_filename(filename):
                po_attachments.append((part, filename))
                continue
                
            # If no clear indication from filename, include PDF files for AI analysis
            if filename.lower().endswith('.pdf'):
                po_attachments.append((part, filename))
    
    return po_attachments

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

def save_attachments_from_unread_emails_multi(email_address, password, save_folder, connection):
    """Extract attachments from unread emails (last 48 hours) - multiple attachments support"""
    print_and_log("Entering save_attachments_from_unread_emails_multi function")
    
    try:
        # Connect to email server
        mail = connect_to_email(email_address, password)
        if not mail:
            print_and_log("❌ Could not connect to email server")
            return
        
        # Get unread emails from last 48 hours
        email_ids = get_unread_emails_last_48h(mail)
        
        if not email_ids:
            print_and_log("No unread emails found from last 48 hours")
            return
        
        processed_emails = 0
        
        for email_id in email_ids:
            try:
                # Fetch email
                status, msg_data = mail.fetch(email_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                # Parse email
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Extract email information
                subject = decode_mime_words(msg.get('Subject', 'No Subject'))
                sender_email = msg.get('From', 'Unknown')
                received_date = msg.get('Date', '')
                message_id = msg.get('Message-ID', f'generated_{email_id.decode()}')
                
                print_and_log(f"Processing email: {subject} from {sender_email}")
                print_and_log(f"Message ID: {message_id[:50] if len(message_id) > 50 else message_id}")
                
                # Get all attachments and filter for PO-related ones
                all_attachments = []
                for part in msg.walk():
                    if part.get_content_disposition() == 'attachment':
                        all_attachments.append(part)
                
                po_attachments = filter_attachments_for_po(msg)
                
                print_and_log(f"Found {len(all_attachments)} total attachments, {len(po_attachments)} PO-related")
                
                # ONLY process emails that have PO-related attachments
                if len(po_attachments) == 0:
                    print_and_log(f"❌ No PO-related attachments found - SKIPPING email: {subject}")
                    continue
                
                # Prepare email data for database
                email_data = {
                    'email_id': message_id,
                    'subject': subject,
                    'sender_email': sender_email,
                    'received_date': datetime.now(),  # You might want to parse the actual date
                    'attachment_count': len(all_attachments),
                    'po_attachments_found': len(po_attachments)
                }
                
                # Process each PO-related attachment separately
                processed_attachments = 0
                attachment_sequence = 1
                
                for attachment_part, original_filename in po_attachments:
                    print_and_log(f"Processing attachment {attachment_sequence}: {original_filename}")
                    
                    # Check if this attachment already exists in database
                    exists, processed = check_attachment_exists(connection, message_id, attachment_sequence)
                    
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
                        # Save attachment
                        with open(attachment_path, 'wb') as f:
                            f.write(attachment_part.get_payload(decode=True))
                        
                        print_and_log(f"Saved attachment '{unique_filename}' from email '{subject}'")
                        
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
                            if not insert_attachment_record(connection, email_data, attachment_sequence):
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
                        
                        if update_attachment_file_record(connection, message_id, attachment_sequence, file_data):
                            print_and_log(f"Updated database record for attachment {attachment_sequence}: {unique_filename}")
                            processed_attachments += 1
                        else:
                            print_and_log(f"Failed to update database for attachment {attachment_sequence}: {unique_filename}")
                            update_attachment_status(connection, message_id, attachment_sequence,
                                                    error_message="Failed to update file record", 
                                                    error_step='database_update')
                            
                    except Exception as e:
                        print_and_log(f"Error processing attachment {attachment_sequence} ({original_filename}): {e}")
                        update_attachment_status(connection, message_id, attachment_sequence,
                                                error_message=f"Attachment error: {str(e)}", 
                                                error_step='attachment_processing')
                    
                    attachment_sequence += 1
                
                if processed_attachments > 0:
                    print_and_log(f"✅ Processed {processed_attachments} attachments for email: {subject}")
                    processed_emails += 1
                else:
                    print_and_log(f"No attachments processed successfully for email: {subject}")
                
            except Exception as e:
                print_and_log(f"Error processing individual email: {e}")
        
        print_and_log(f"Total emails processed: {processed_emails}")
        
        # Close connection
        mail.close()
        mail.logout()
        
    except Exception as e:
        print_and_log(f"Error in save_attachments_from_unread_emails_multi: {e}")

def main():
    """Main function"""
    print_and_log("Script 1 started - Email Multiple Attachments Extraction (Linux)")
    
    # Test configuration loading
    try:
        print(f"Loaded config - Database: {config['Production']['database']}")
        print(f"Loaded config - Server: {config['Production']['server']}")
        print(f"Loaded config - Email Server: {EMAIL_CONFIG['server']}")
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return
    
    connection = create_db_connection()
    if not connection:
        print("Failed to connect to database. Exiting.")
        return
    
    try:
        # Get credentials file path from config
        credentials_file = config['Email']['credentials_file']
        email_address, password = get_credentials(credentials_file)
        
        if not email_address or not password:
            print_and_log("Failed to get email credentials")
            return
        
        # Use Linux-compatible path
        save_folder = os.path.expanduser('~/scripts/PO')
        
        if not os.path.exists(save_folder):
            os.makedirs(save_folder, mode=0o755)
            print_and_log(f"Created directory: {save_folder}")

        print_and_log("Connecting to email server and saving multiple attachments from unread emails (last 48 hours)")
        save_attachments_from_unread_emails_multi(email_address, password, save_folder, connection)

        print_and_log("Script 1 finished - Email Multiple Attachments Extraction completed")
        
    except Exception as e:
        print_and_log(f"Error in main: {e}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()