#!/usr/bin/env python3
# ai_classification_linux.py

import os
import openai
import time
import shutil
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import configparser

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

# OpenAI API key from config
OPENAI_API_KEY = config['OpenAI']['api_key']

# Linux-compatible path configurations
TEXT_FILES_DIRECTORY = os.path.expanduser('~/scripts/PO/converted_to_txt')
PO_FOLDER = os.path.expanduser('~/scripts/PO/finalAI')
PQ_FOLDER = os.path.expanduser('~/scripts/PQ/finalAI')
INV_FOLDER = os.path.expanduser('~/scripts/INV')
OTHER_FOLDER = os.path.expanduser('~/scripts/else')

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

def get_attachments_for_classification(connection):
    """Get attachments that need AI classification"""
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Get attachments where text conversion completed but classification not done
        query = """
        SELECT email_id, attachment_sequence, translated_file_name, translated_file_path, 
               original_file_name, retry_count, processing_method, pdf_type, subject
        FROM email_processing_log 
        WHERE text_converted = 'Y' 
          AND ai_classified = 'N' 
          AND retry_count < 3
          AND translated_file_path IS NOT NULL
        ORDER BY email_id, attachment_sequence ASC
        """
        
        cursor.execute(query)
        attachments = cursor.fetchall()
        cursor.close()
        
        print(f"Found {len(attachments)} attachments ready for AI classification")
        return attachments
        
    except Error as e:
        print(f"Error getting attachments for classification: {e}")
        return []

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

def check_email_classification_complete(connection, email_id):
    """Check if all attachments for an email have been classified"""
    try:
        cursor = connection.cursor()
        
        # Get total count and classified count for this email
        query = """
        SELECT 
            COUNT(*) as total_attachments,
            SUM(CASE WHEN ai_classified = 'Y' THEN 1 ELSE 0 END) as classified_attachments,
            GROUP_CONCAT(DISTINCT classification_result) as classifications
        FROM email_processing_log 
        WHERE email_id = %s
        """
        
        cursor.execute(query, (email_id,))
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            total = result[0]
            classified = result[1]
            classifications = result[2] if result[2] else ""
            
            is_complete = (total == classified)
            has_po = "Purchase Order" in classifications if classifications else False
            
            return is_complete, has_po, total, classified
        
        return False, False, 0, 0
        
    except Error as e:
        print(f"Error checking email classification status: {e}")
        return False, False, 0, 0

def create_enhanced_classification_prompt(text_content, filename, processing_method):
    """Create focused prompt for GPT classification - simple and direct"""
    
    base_prompt = f"""
    Below is the content of a business document. Based on the information provided, your task is to analyze the content and determine whether the document is most likely an Invoice, a Purchase Order, or a Request for Quote (RFQ).

    Document filename: {filename}
    Processing method used: {processing_method}

    CRITICAL DECISION RULES - Follow these in order of priority:

    🔴 STRONGEST INDICATOR - PURCHASE ORDER:
    If you see ANY of these phrases, it is DEFINITELY a Purchase Order:
    - "Purchase Order" (in title or anywhere in document)
    - "Purchase order" 
    - "PO Number"
    - "Order Number" followed by numbers
    - "Order:" followed by numbers
    - Companies ordering FROM suppliers (buyer-seller relationship)
    
    Even if the document mentions quotation numbers or references quotes, if it contains "Purchase Order" or order numbers with line items, it is ALWAYS a Purchase Order. Purchase Orders often reference the original quotes they are based on.

    📋 PURCHASE ORDER CHARACTERISTICS:
    Look for these specific patterns that indicate authorization to purchase:
    - Document titled "Purchase Order" or similar
    - Order numbers like "Order 4500476884"
    - Line items with quantities, prices, delivery instructions
    - "Please deliver to:" addresses
    - Payment terms like "Net due 30 days"
    - Buyer company details and supplier/vendor information
    - References like "This PO refers to quotation..." (still a Purchase Order!)

    🧾 INVOICE CHARACTERISTICS:
    Invoices request payment for completed work:
    - "Invoice", "Invoice Number", "Amount Due", "Total Due"
    - Payment instructions and past-tense language
    - Bills for services already rendered or goods already delivered

    💭 REQUEST FOR QUOTE (RFQ) CHARACTERISTICS:
    RFQs ask for pricing information:
    - "Request for Quote", "RFQ", "Please provide pricing"
    - Future-tense language asking for quotes or availability
    - No authorization to purchase, just requesting information

    ANALYSIS INSTRUCTIONS:
    1. Look at the document title first - this is usually definitive
    2. If you see "Purchase Order" anywhere, classify as Purchase Order
    3. Look for order numbers and authorization language
    4. Ignore quote references if the document is clearly authorizing a purchase
    5. Focus on the document's primary purpose: authorizing purchase vs. requesting information

    Document content:
    {text_content}

    Based on these guidelines, classify the document. Remember: if it says "Purchase Order" or has order numbers with line items, it's a Purchase Order regardless of quote references.

    Please respond in this exact format:
    Classification: [Invoice/Purchase Order/RFQ/Other]
    Confidence: [High/Medium/Low]
    Reasoning: [Brief explanation focusing on the key indicators you found]
    Key identifiers found: [List the specific phrases or numbers that led to your decision]
    """
    
    return base_prompt

def classify_content_with_chatgpt(text_content, filename, processing_method):
    """Classify the content of a text using ChatGPT"""
    try:
        openai.api_key = OPENAI_API_KEY

        # Create enhanced prompt
        prompt = create_enhanced_classification_prompt(text_content, filename, processing_method)

        # Send the message to ChatGPT using GPT-4
        response = openai.ChatCompletion.create(
            model="gpt-4o-2024-05-13",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that classifies business document content. Always respond in the exact format requested."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=500
        )

        # Extract the assistant's reply from the response
        assistant_reply = response['choices'][0]['message']['content']
        return assistant_reply
        
    except Exception as e:
        print(f"Error classifying content with ChatGPT: {e}")
        return "Unknown"

def parse_classification_response(response_text):
    """Parse the classification response to extract structured data"""
    result = {
        'classification': 'Other',
        'confidence': 'Low',
        'reasoning': '',
        'key_identifiers': ''
    }
    
    try:
        lines = response_text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('Classification:'):
                result['classification'] = line.split(':', 1)[1].strip()
            elif line.startswith('Confidence:'):
                result['confidence'] = line.split(':', 1)[1].strip()
            elif line.startswith('Reasoning:'):
                result['reasoning'] = line.split(':', 1)[1].strip()
            elif line.startswith('Key identifiers found:'):
                result['key_identifiers'] = line.split(':', 1)[1].strip()
                
    except Exception as e:
        print(f"Error parsing classification response: {e}")
    
    return result

def determine_destination_folder(classification):
    """Determine destination folder based on classification"""
    classification_lower = classification.lower()
    
    if "purchase order" in classification_lower or "po" in classification_lower:
        return PO_FOLDER
    elif "quotation" in classification_lower or "rfq" in classification_lower or "quote" in classification_lower:
        return PQ_FOLDER
    elif "proposal" in classification_lower:
        return PQ_FOLDER  # Route proposals to PQ folder
    elif "invoice" in classification_lower:
        return INV_FOLDER
    else:
        return OTHER_FOLDER

def move_file_to_destination(source_path, destination_folder, filename):
    """Move file to destination folder with conflict handling"""
    try:
        # Ensure destination folder exists with proper permissions
        os.makedirs(destination_folder, mode=0o755, exist_ok=True)
        
        destination_path = os.path.join(destination_folder, filename)
        
        # Handle file name conflicts by adding a unique suffix
        count = 1
        base_name, extension = os.path.splitext(filename)
        while os.path.exists(destination_path):
            new_filename = f"{base_name}_{count}{extension}"
            destination_path = os.path.join(destination_folder, new_filename)
            count += 1

        shutil.move(source_path, destination_path)
        print(f"Moved {filename} to {destination_folder}")
        return destination_path
        
    except Exception as e:
        print(f"Error moving file {filename}: {e}")
        return source_path

def ensure_directories_exist():
    """Ensure all required directories exist with proper permissions"""
    directories = [TEXT_FILES_DIRECTORY, PO_FOLDER, PQ_FOLDER, INV_FOLDER, OTHER_FOLDER]
    
    for directory in directories:
        try:
            os.makedirs(directory, mode=0o755, exist_ok=True)
            print_and_log(f"Directory ready: {directory}")
        except Exception as e:
            print_and_log(f"Error creating directory {directory}: {e}")

def process_attachment_classification(connection):
    """Process attachments for AI classification"""
    
    # Ensure all destination folders exist
    ensure_directories_exist()
    
    # Get attachments that need classification
    attachments_to_classify = get_attachments_for_classification(connection)
    
    if not attachments_to_classify:
        print("No attachments found that need AI classification.")
        return

    # Counter to track API requests for rate limiting
    request_counter = 0
    
    for attachment_record in attachments_to_classify:
        email_id = attachment_record['email_id']
        attachment_sequence = attachment_record['attachment_sequence']
        translated_file_path = attachment_record['translated_file_path']
        translated_file_name = attachment_record['translated_file_name']
        original_file_name = attachment_record['original_file_name']
        processing_method = attachment_record['processing_method']
        pdf_type = attachment_record['pdf_type']
        subject = attachment_record['subject']
        
        print(f"\nProcessing classification for: {translated_file_name}")
        print(f"Email: {subject}")
        print(f"Attachment {attachment_sequence}: {original_file_name}")
        print(f"Processing method: {processing_method}, PDF type: {pdf_type}")
        
        try:
            # Check if file exists
            if not os.path.exists(translated_file_path):
                print(f"Translated file not found: {translated_file_path}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        error_message="Translated file not found on disk",
                                        error_step='file_not_found',
                                        retry_count=attachment_record['retry_count'] + 1)
                continue
            
            # Update status to indicate classification started
            update_attachment_status(connection, email_id, attachment_sequence, current_step='ai_classification')
            
            # Read the content of the file
            with open(translated_file_path, 'r', encoding='utf-8') as file:
                file_content = file.read()
            
            # Check if file has meaningful content
            if len(file_content.strip()) < 100:
                print(f"File has insufficient content for classification: {translated_file_name}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        error_message="Insufficient text content for classification",
                                        error_step='content_validation',
                                        retry_count=attachment_record['retry_count'] + 1)
                continue

            # Classify the content using ChatGPT
            print(f"Sending to AI for classification...")
            raw_classification = classify_content_with_chatgpt(file_content, original_file_name, processing_method)
            
            # Parse the classification response
            classification_data = parse_classification_response(raw_classification)
            
            print(f"AI Classification Result:")
            print(f"  Classification: {classification_data['classification']}")
            print(f"  Confidence: {classification_data['confidence']}")
            print(f"  Reasoning: {classification_data['reasoning']}")
            
            # Determine destination folder
            destination_folder = determine_destination_folder(classification_data['classification'])
            
            # Move the file to appropriate destination folder
            new_file_path = move_file_to_destination(translated_file_path, destination_folder, translated_file_name)
            
            # Determine next step based on classification
            is_purchase_order = "purchase order" in classification_data['classification'].lower()
            next_step = 'api_processing' if is_purchase_order else 'email_notification'
            
            # Update database with classification results
            update_attachment_status(connection, email_id, attachment_sequence,
                                   ai_classified='Y',
                                   ai_classified_at=datetime.now(),
                                   classification_result=classification_data['classification'],
                                   classification_confidence=classification_data['confidence'],
                                   translated_file_path=new_file_path,
                                   current_step=next_step,
                                   notes=f"AI Reasoning: {classification_data['reasoning'][:500]}")  # Limit reasoning length
            
            print(f"Successfully classified attachment {attachment_sequence}: {translated_file_name}")
            
            # Check if all attachments for this email have been classified
            is_complete, has_po, total_attachments, classified_attachments = check_email_classification_complete(connection, email_id)
            
            print(f"Email classification status: {classified_attachments}/{total_attachments} attachments classified")
            
            print("-" * 50)

            # Increment request counter
            request_counter += 1

            # Rate limiting: Sleep after every 3 requests to respect OpenAI limits
            if request_counter % 3 == 0:
                print("Rate limiting: Sleeping for 20 seconds...")
                time.sleep(20)
            else:
                # Small delay between requests
                time.sleep(2)

        except Exception as e:
            print(f"Error processing classification for {translated_file_name}: {e}")
            update_attachment_status(connection, email_id, attachment_sequence,
                                   error_message=f"Classification error: {str(e)}",
                                   error_step='ai_classification',
                                   retry_count=attachment_record['retry_count'] + 1)

def main():
    """Main function"""
    connection = create_db_connection()
    if not connection:
        print("Failed to connect to database. Exiting.")
        return
    
    # Validate OpenAI API key
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_api_key_here":
        print("ERROR: Please update the OPENAI_API_KEY in configi.ini!")
        return
    
    print_and_log("Script 3 started - AI Classification (Linux)")
    
    try:
        print(f"Using database: {config['Production']['database']} on {config['Production']['server']}")
        print(f"Working directories:")
        print(f"  PO Folder: {PO_FOLDER}")
        print(f"  PQ Folder: {PQ_FOLDER}")
        print(f"  Invoice Folder: {INV_FOLDER}")
        print(f"  Other Folder: {OTHER_FOLDER}")
        
        process_attachment_classification(connection)
        print_and_log("Script 3 finished - AI classification completed")
        
    except Exception as e:
        print_and_log(f"Error in main: {e}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()