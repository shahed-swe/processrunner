#!/usr/bin/env python3
# APIProcessingPO_linux.py

import openai
import os
import json
import http.client
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

# API Configuration
OPENAI_API_KEY = config['OpenAI']['api_key']
API_URL = "support.supsol-scm.com"
API_ENDPOINT = "/api/v1/ServiceCall/POCreate"

# Linux-compatible path configurations
PO_FOLDER = os.path.expanduser('~/scripts/PO/finalAI')
PROCESSED_FOLDER = os.path.expanduser('~/scripts/PO/api_processed')

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

def get_attachments_for_api_processing(connection):
    """Get attachments that need API processing (Purchase Orders only)"""
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Get attachments where AI classified as Purchase Order but API not loaded
        query = """
        SELECT email_id, attachment_sequence, translated_file_name, translated_file_path, 
               original_file_name, classification_result, retry_count, subject
        FROM email_processing_log 
        WHERE ai_classified = 'Y' 
          AND classification_result LIKE '%Purchase Order%'
          AND api_loaded = 'N' 
          AND retry_count < 3
          AND translated_file_path IS NOT NULL
        ORDER BY email_id, attachment_sequence ASC
        """
        
        cursor.execute(query)
        attachments = cursor.fetchall()
        cursor.close()
        
        print(f"Found {len(attachments)} Purchase Order attachments ready for API processing")
        return attachments
        
    except Error as e:
        print(f"Error getting attachments for API processing: {e}")
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

def extract_data_with_openai(file_path, file_name, connection, email_id, attachment_sequence):
    """Extract structured data from text file using OpenAI"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            text_content = file.read()

        prompt_text = (
            "Read the following Purchase Order document and extract data points in strict JSON format:\n"
            "- Look for the quote number. It usually appears near the description and consists of 6 digits like 101230 or starts with 'pq'. Fill this number at 'wpqNumber'. If there isn't any value, return the PO number.\n"
            "- Identify the Purchase Order (PO) number. It typically appears as 'Purchase Order' or 'PO' followed by the number. Fill this at 'poNumber'.\n"
            "- Locate the customer tax ID, the customer tax ID appears before the description tax id. It is located next to the customer name. It's the identifier number of the customer it is not 'tax payer id'. Fill this at 'customerTaxID' it can appear next to tax ID and it is not vendor number. Make sure to identify it correctly. If the customer is Stratasys Ltd set the customer ID as 512607698.\n"
            "- Identify the vendor tax ID. It should be in the format IL516163649 or only the numbers 516163649. If not found, write 11111111. Fill this at 'vendorTaxID', in case you don't identify the ID and you find the sopsol then return 516163649.\n"
            "- Please return for the tax ID all characters include the two letters at start, without gap between the letters and the number\n"
            "- Find the currency type mentioned within the document, ensuring it matches international banking system standards (e.g., USD, EUR, GBP, JPY, AUD, SGD). Note: ILS and NIS are considered the same, return ILS if not found. Fill this at 'currencyType'.\n"
            "- Extract the price (without breakdown and currency). Fill this at 'price'.\n"
            "Ensure the JSON format is correct and includes all the required fields. Here is the JSON structure:\n"
            "{\n"
            "  \"wpqNumber\": <wpqNumber>,\n"
            "  \"poNumber\": \"<poNumber>\",\n"
            "  \"customerTaxID\": \"<customerTaxID>\",\n"
            "  \"vendorTaxID\": \"<vendorTaxID>\",\n"
            "  \"currencyType\": \"<currencyType>\",\n"
            "  \"price\": <price>\n"
            "}\n\n"
            f"Here is the Purchase Order document content:\n\n{text_content}\n\n"
            "Return ONLY the JSON data, no additional text or explanations."
        )

        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "Extract data from Purchase Order text files and return it in JSON format. Return only valid JSON, no additional text."},
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.1,
            max_tokens=512,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stop=["\n\n"],
        )

        assistant_response = response['choices'][0]['message']['content'].strip()
        print(f"OpenAI API Response for file '{file_name}':")
        print(assistant_response)

        # Extract JSON from response
        start_index = assistant_response.find("{")
        end_index = assistant_response.rfind("}")

        if start_index != -1 and end_index != -1:
            json_content = assistant_response[start_index:end_index + 1]
            if json_content:
                extracted_data = json.loads(json_content)
                
                # Try to convert wpqNumber to int, if fails, use poNumber
                try:
                    extracted_data['wpqNumber'] = int(extracted_data['wpqNumber'])
                except (ValueError, TypeError):
                    try:
                        extracted_data['wpqNumber'] = int(extracted_data['poNumber'])
                    except (ValueError, TypeError):
                        extracted_data['wpqNumber'] = None
                
                # Store the request data in database for tracking
                update_attachment_status(connection, email_id, attachment_sequence,
                                        api_request_data=json.dumps(extracted_data, indent=2))
                
                return extracted_data
            else:
                print(f"No JSON data extracted for file '{file_name}'.")
                return None
        else:
            print(f"No valid JSON found in response for file '{file_name}'.")
            return None
            
    except Exception as e:
        print(f"Error extracting data from file '{file_name}': {str(e)}")
        update_attachment_status(connection, email_id, attachment_sequence,
                                 error_message=f"Data extraction error: {str(e)}",
                                 error_step='data_extraction')
        return None

def send_to_api(extracted_data, file_name, connection, email_id, attachment_sequence):
    """Send extracted data to external API"""
    try:
        payload = json.dumps(extracted_data)
        headers = {'Content-Type': 'application/json'}

        print(f"Sending API request for file '{file_name}':")
        print(f"URL: {API_URL}{API_ENDPOINT}")
        print(f"Payload: {payload}")

        conn = http.client.HTTPSConnection(API_URL)
        conn.request("POST", API_ENDPOINT, payload, headers)
        response = conn.getresponse()

        api_response = response.read().decode('utf-8')
        print(f"API Response for file '{file_name}':")
        print(f"Status: {response.status}")
        print(f"Response: {api_response}")

        # Store API response in database
        update_attachment_status(connection, email_id, attachment_sequence,
                                api_response=api_response)

        conn.close()
        
        if response.status == 200:
            print(f"API transmission successful for file '{file_name}'.")
            return True, api_response
        else:
            print(f"API transmission failed for file '{file_name}'. Status code: {response.status}")
            return False, api_response
            
    except Exception as e:
        error_msg = f"API transmission error: {str(e)}"
        print(error_msg)
        update_attachment_status(connection, email_id, attachment_sequence,
                                error_message=error_msg,
                                error_step='api_transmission')
        return False, str(e)

def move_processed_file(file_path, file_name, success=True):
    """Move processed file to appropriate folder"""
    try:
        # Ensure processed folder exists with proper permissions
        os.makedirs(PROCESSED_FOLDER, mode=0o755, exist_ok=True)
        
        if success:
            # Add success suffix
            base_name, extension = os.path.splitext(file_name)
            new_filename = f"{base_name}-api_success{extension}"
        else:
            # Add failed suffix  
            base_name, extension = os.path.splitext(file_name)
            new_filename = f"{base_name}-api_failed{extension}"
        
        new_file_path = os.path.join(PROCESSED_FOLDER, new_filename)
        
        # Handle filename conflicts
        counter = 1
        while os.path.exists(new_file_path):
            base_name, extension = os.path.splitext(file_name)
            suffix = "-api_success" if success else "-api_failed"
            new_filename = f"{base_name}{suffix}_{counter}{extension}"
            new_file_path = os.path.join(PROCESSED_FOLDER, new_filename)
            counter += 1
        
        shutil.move(file_path, new_file_path)
        print(f"Moved '{file_name}' to '{new_file_path}'")
        return new_file_path
        
    except Exception as e:
        print(f"Error moving file '{file_name}': {e}")
        return file_path

def ensure_directories_exist():
    """Ensure all required directories exist with proper permissions"""
    directories = [PO_FOLDER, PROCESSED_FOLDER]
    
    for directory in directories:
        try:
            os.makedirs(directory, mode=0o755, exist_ok=True)
            print_and_log(f"Directory ready: {directory}")
        except Exception as e:
            print_and_log(f"Error creating directory {directory}: {e}")

def process_purchase_orders(connection):
    """Process Purchase Orders for API submission"""
    
    # Ensure directories exist
    ensure_directories_exist()
    
    # Get Purchase Order attachments that need API processing
    attachments_to_process = get_attachments_for_api_processing(connection)
    
    if not attachments_to_process:
        print("No Purchase Order attachments found that need API processing.")
        return

    for attachment_record in attachments_to_process:
        email_id = attachment_record['email_id']
        attachment_sequence = attachment_record['attachment_sequence']
        translated_file_path = attachment_record['translated_file_path']
        translated_file_name = attachment_record['translated_file_name']
        original_file_name = attachment_record['original_file_name']
        subject = attachment_record['subject']
        
        print(f"\nProcessing API submission for attachment {attachment_sequence}: {translated_file_name}")
        print(f"Email: {subject}")
        print(f"Original file: {original_file_name}")
        print(f"Classification: {attachment_record['classification_result']}")
        
        try:
            # Check if file exists
            if not os.path.exists(translated_file_path):
                print(f"Translated file not found: {translated_file_path}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        error_message="Translated file not found on disk",
                                        error_step='file_not_found',
                                        retry_count=attachment_record['retry_count'] + 1)
                continue
            
            # Update status to indicate API processing started
            update_attachment_status(connection, email_id, attachment_sequence, current_step='api_processing')
            
            # Extract data using OpenAI
            print(f"Extracting structured data from: {translated_file_name}")
            extracted_data = extract_data_with_openai(translated_file_path, translated_file_name, 
                                                     connection, email_id, attachment_sequence)
            
            if extracted_data is None:
                print(f"Failed to extract data from {translated_file_name}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        retry_count=attachment_record['retry_count'] + 1,
                                        error_message="Failed to extract structured data",
                                        error_step='data_extraction')
                continue
            
            # Send data to API
            print(f"Sending data to API for: {translated_file_name}")
            api_success, api_response = send_to_api(extracted_data, translated_file_name, 
                                                   connection, email_id, attachment_sequence)
            
            if api_success:
                # Update database with success
                update_attachment_status(connection, email_id, attachment_sequence,
                                        api_loaded='Y',
                                        api_loaded_at=datetime.now(),
                                        current_step='email_notification')
                
                # Move file to processed folder with success indicator
                new_file_path = move_processed_file(translated_file_path, translated_file_name, success=True)
                
                # Update file path in database
                update_attachment_status(connection, email_id, attachment_sequence, 
                                        translated_file_path=new_file_path)
                
                print(f"Successfully processed attachment {attachment_sequence}: {translated_file_name}")
                
            else:
                # Update database with failure
                update_attachment_status(connection, email_id, attachment_sequence,
                                        api_loaded='N',
                                        retry_count=attachment_record['retry_count'] + 1,
                                        error_message=f"API submission failed: {api_response}",
                                        error_step='api_submission')
                
                # Move file to processed folder with failure indicator
                new_file_path = move_processed_file(translated_file_path, translated_file_name, success=False)
                
                # Update file path in database
                update_attachment_status(connection, email_id, attachment_sequence,
                                        translated_file_path=new_file_path)
                
                print(f"API submission failed for attachment {attachment_sequence}: {translated_file_name}")
            
            print("-" * 50)

        except Exception as e:
            print(f"Error processing attachment {attachment_sequence} ({translated_file_name}): {e}")
            update_attachment_status(connection, email_id, attachment_sequence,
                                    error_message=f"Processing error: {str(e)}",
                                    error_step='api_processing',
                                    retry_count=attachment_record['retry_count'] + 1)

def main():
    """Main function"""
    connection = create_db_connection()
    if not connection:
        print("Failed to connect to database. Exiting.")
        return
    
    # Validate API keys
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_api_key_here":
        print("ERROR: Please update the OPENAI_API_KEY in configi.ini!")
        return
    
    print_and_log("Script 4 started - API Processing (Purchase Orders Only) - Linux")
    
    try:
        # Initialize the OpenAI API client
        openai.api_key = OPENAI_API_KEY
        print("Connected to OpenAI successfully.")
        print(f"Using database: {config['Production']['database']} on {config['Production']['server']}")
        print(f"Working directories:")
        print(f"  PO Folder: {PO_FOLDER}")
        print(f"  Processed Folder: {PROCESSED_FOLDER}")
        
        process_purchase_orders(connection)
        print_and_log("Script 4 finished - API processing completed")
        
    except Exception as e:
        print_and_log(f"Error in main: {e}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()