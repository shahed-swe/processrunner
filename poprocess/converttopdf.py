#converttopdf-linux.py
import os
import fitz  # PyMuPDF library for PDF processing
from langdetect import detect
import subprocess
from io import StringIO, BytesIO
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage
import shutil
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from PIL import Image
import pytesseract
import configparser
from pathlib import Path

# Load configuration
config = configparser.ConfigParser()
config.read('configi.ini')

# Database configuration from config.ini - using Production section
DB_CONFIG = {
    'host': config['Production']['server'],
    'database': config['Production']['database'],
    'user': config['Production']['user'],
    'password': config['Production']['password']
}

# Install the specific version of googletrans if needed
# subprocess.check_call(["pip", "install", "googletrans==3.1.0a0"])

from deep_translator import GoogleTranslator

# Path configurations - Linux compatible paths
BASE_DIR = Path.home() / "my_script" / "test" / "PO"
INPUT_FOLDER = str(BASE_DIR)
OUTPUT_FOLDER = str(BASE_DIR / "converted_to_txt")
PROCESSED_FOLDER = str(BASE_DIR / "processed")
NON_PDF_FOLDER = str(BASE_DIR / "non_pdf")

def create_db_connection():
    """Create database connection"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def print_and_log(message):
    """Print message to console"""
    print(message)

def get_attachments_for_processing(connection):
    """Get attachments that need processing (updated for composite key)"""
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Get attachments where PDF was extracted but not yet processed
        query = """
        SELECT email_id, attachment_sequence, original_file_name, original_file_path, file_type, 
               retry_count, attachment_count, po_attachments_found, subject
        FROM email_processing_log 
        WHERE pdf_extracted = 'Y' 
          AND text_converted = 'N' 
          AND email_sent = 'N'
          AND retry_count < 3
          AND original_file_path IS NOT NULL
        ORDER BY email_id, attachment_sequence ASC
        """
        
        cursor.execute(query)
        attachments = cursor.fetchall()
        cursor.close()
        
        print(f"Found {len(attachments)} attachments ready for processing")
        return attachments
        
    except Error as e:
        print(f"Error getting attachments for processing: {e}")
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

def is_pdf_file(file_path, file_type):
    """Check if file is actually a PDF"""
    try:
        # Check file extension and type from database
        if file_type != 'PDF':
            return False
            
        # Verify by reading file header
        if os.path.exists(file_path):
            with open(file_path, 'rb') as file:
                header = file.read(4)
                return header == b'%PDF'
        return False
        
    except Exception as e:
        print(f"Error checking if file is PDF: {e}")
        return False

def skip_to_email_notification(connection, email_id, attachment_sequence, reason, file_name):
    """Skip all processing steps and mark for email notification"""
    try:
        print(f"Skipping {file_name} to email notification: {reason}")
        
        # Update status to skip AI processing and mark ready for email
        update_attachment_status(connection, email_id, attachment_sequence,
                                text_converted='SKIPPED',
                                ai_classified='SKIPPED', 
                                api_loaded='SKIPPED',
                                current_step='email_notification',
                                error_message=f"Non-PDF file: {reason}",
                                error_step='file_type_check')
        
        return True
        
    except Exception as e:
        print(f"Error skipping to email notification: {e}")
        return False

def analyze_pdf_type(pdf_path):
    """
    Analyze if PDF contains text or is scanned images
    Returns: dict with analysis results
    """
    result = {
        'file_path': pdf_path,
        'pdf_type': 'unknown',  # 'text', 'scanned', 'mixed', 'empty'
        'total_pages': 0,
        'text_pages': 0,
        'image_pages': 0,
        'extractable_text_length': 0,
        'has_images': False,
        'processing_method': 'text'  # 'text', 'ocr', 'mixed'
    }
    
    try:
        pdf_document = fitz.open(pdf_path)
        result['total_pages'] = pdf_document.page_count
        
        total_text_length = 0
        pages_with_text = 0
        pages_with_images = 0
        
        for page_num in range(pdf_document.page_count):
            page = pdf_document.load_page(page_num)
            
            # Check for text content
            text = page.get_text("text").strip()
            if len(text) > 50:  # Meaningful text threshold
                pages_with_text += 1
                total_text_length += len(text)
            
            # Check for images
            image_list = page.get_images()
            if image_list:
                pages_with_images += 1
                result['has_images'] = True
        
        result['text_pages'] = pages_with_text
        result['image_pages'] = pages_with_images
        result['extractable_text_length'] = total_text_length
        
        # Determine PDF type and processing method
        text_ratio = pages_with_text / result['total_pages'] if result['total_pages'] > 0 else 0
        
        if total_text_length > 500 and text_ratio > 0.7:
            result['pdf_type'] = 'text'
            result['processing_method'] = 'text'
        elif pages_with_images > 0 and total_text_length < 100:
            result['pdf_type'] = 'scanned'
            result['processing_method'] = 'ocr'
        elif pages_with_images > 0 and total_text_length > 100:
            result['pdf_type'] = 'mixed'
            result['processing_method'] = 'mixed'
        else:
            result['pdf_type'] = 'empty'
            result['processing_method'] = 'text'
            
        pdf_document.close()
        
    except Exception as e:
        result['error'] = f"Error analyzing PDF: {e}"
    
    return result

def convert_pdf_to_text_pymupdf(pdf_file_path):
    """Convert PDF to text using PyMuPDF"""
    try:
        pdf_document = fitz.open(pdf_file_path)
        text = ""

        for page_number in range(pdf_document.page_count):
            page = pdf_document.load_page(page_number)
            text += page.get_text("text")  # Use "text" option for text extraction

        pdf_document.close()
        return text.strip()
    except Exception as e:
        print(f"Error converting PDF to text using PyMuPDF: {e}")
        return None

def convert_pdf_to_text_pdfminer(pdf_file_path):
    """Convert PDF to text using pdfminer"""
    try:
        resource_manager = PDFResourceManager()
        string_io = StringIO()
        device = TextConverter(resource_manager, string_io, laparams=LAParams())
        interpreter = PDFPageInterpreter(resource_manager, device)

        with open(pdf_file_path, 'rb') as file:
            for page in PDFPage.get_pages(file):
                interpreter.process_page(page)

        text = string_io.getvalue()
        device.close()
        string_io.close()

        return text.strip()
    except Exception as e:
        print(f"Error converting PDF to text using pdfminer: {e}")
        return None

def extract_text_with_ocr(pdf_path):
    """Extract text from scanned PDF using OCR"""
    try:
        pdf_document = fitz.open(pdf_path)
        extracted_text = ""
        
        for page_num in range(pdf_document.page_count):
            page = pdf_document.load_page(page_num)
            
            # Convert page to image with higher resolution
            mat = fitz.Matrix(2.0, 2.0)  # Increase resolution for better OCR
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            # Use OCR to extract text
            image = Image.open(BytesIO(img_data))
            
            # OCR with specific config for better results
            custom_config = r'--oem 3 --psm 6 -l eng+heb'  # Support English and Hebrew
            try:
                page_text = pytesseract.image_to_string(image, config=custom_config)
            except:
                # Fallback to English only if Hebrew not available
                custom_config = r'--oem 3 --psm 6 -l eng'
                page_text = pytesseract.image_to_string(image, config=custom_config)
            
            extracted_text += f"\n--- Page {page_num + 1} ---\n"
            extracted_text += page_text
            
        pdf_document.close()
        return extracted_text.strip()
        
    except Exception as e:
        print(f"Error in OCR processing: {e}")
        return None

def reverse_hebrew_words(text):
    """Reverse Hebrew words for proper display"""
    def is_hebrew(word):
        # Check if word contains Hebrew characters
        return any('\u0590' <= char <= '\u05FF' for char in word)

    reversed_text = ""
    current_word = ""
    for char in text:
        if char.isalpha():
            current_word += char
        else:
            if is_hebrew(current_word):
                current_word = current_word[::-1]  # Reverse Hebrew word
            reversed_text += current_word + char
            current_word = ""
    # Handle last word if any
    if current_word:
        if is_hebrew(current_word):
            current_word = current_word[::-1]  # Reverse Hebrew word
        reversed_text += current_word
    return reversed_text

def translate_text_to_english(text):
    """Translate text to English"""
    try:
        if text:
            translated_text = GoogleTranslator(source='he', target='en').translate(text)
            return translated_text
        else:
            print("Input text is empty or None.")
            return ""
    except Exception as e:
        print(f"Error translating text: {e}")
        return ""

def process_pdf_with_intelligence(pdf_path, output_folder, connection, email_id, attachment_sequence):
    """
    Intelligently process PDF based on its type
    """
    print(f"Starting intelligent processing of: {os.path.basename(pdf_path)}")
    
    # Analyze PDF type
    analysis = analyze_pdf_type(pdf_path)
    
    # Update database with PDF analysis
    update_attachment_status(connection, email_id, attachment_sequence,
                            pdf_type=analysis['pdf_type'],
                            processing_method=analysis['processing_method'],
                            ocr_required='Y' if analysis['processing_method'] in ['ocr', 'mixed'] else 'N')
    
    extracted_text = ""
    processing_method = analysis['processing_method']
    
    try:
        if processing_method == 'text':
            # Standard text extraction
            extracted_text = convert_pdf_to_text_pymupdf(pdf_path)
            if not extracted_text:
                # Fallback to pdfminer
                extracted_text = convert_pdf_to_text_pdfminer(pdf_path)
            print(f"Processed as text PDF: {os.path.basename(pdf_path)}")
            
        elif processing_method == 'ocr':
            # OCR processing for scanned documents
            extracted_text = extract_text_with_ocr(pdf_path)
            print(f"Processed as scanned PDF with OCR: {os.path.basename(pdf_path)}")
            
        elif processing_method == 'mixed':
            # Try text extraction first, then OCR for image-heavy pages
            text_content = convert_pdf_to_text_pymupdf(pdf_path)
            if len(text_content) < 200:  # If text extraction yields little content
                ocr_content = extract_text_with_ocr(pdf_path)
                extracted_text = f"{text_content}\n\n--- OCR Content ---\n{ocr_content}"
            else:
                extracted_text = text_content
            print(f"Processed as mixed PDF: {os.path.basename(pdf_path)}")
            
        # If we still don't have text, try OCR as last resort
        if not extracted_text or len(extracted_text.strip()) < 50:
            print(f"Limited text extracted, trying OCR as fallback...")
            extracted_text = extract_text_with_ocr(pdf_path)
            update_attachment_status(connection, email_id, attachment_sequence, processing_method='ocr')
            
    except Exception as e:
        print(f"Error processing PDF {pdf_path}: {e}")
        update_attachment_status(connection, email_id, attachment_sequence,
                                error_message=f"PDF processing error: {str(e)}",
                                error_step='pdf_processing')
        return None, analysis
    
    return extracted_text, analysis

def move_non_pdf_file(file_path, file_name):
    """Move non-PDF files to separate folder"""
    try:
        os.makedirs(NON_PDF_FOLDER, exist_ok=True)
        destination = os.path.join(NON_PDF_FOLDER, file_name)
        
        # Handle filename conflicts
        counter = 1
        base_name, extension = os.path.splitext(file_name)
        while os.path.exists(destination):
            new_name = f"{base_name}_{counter}{extension}"
            destination = os.path.join(NON_PDF_FOLDER, new_name)
            counter += 1
            
        shutil.move(file_path, destination)
        print(f"Moved non-PDF file to: {destination}")
        return destination
        
    except Exception as e:
        print(f"Error moving non-PDF file: {e}")
        return file_path

def create_unique_translated_filename(original_filename, attachment_sequence):
    """Create unique translated filename using original name and sequence"""
    try:
        # Remove extension from original filename
        base_name = os.path.splitext(original_filename)[0]
        
        # Create unique translated filename with attachment sequence
        translated_filename = f"{base_name}_seq{attachment_sequence}_translated.txt"
        
        return translated_filename
        
    except Exception as e:
        print(f"Error creating translated filename: {e}")
        # Fallback to simple naming
        return f"attachment_{attachment_sequence}_translated.txt"

def process_attachments(connection):
    """Process attachments - PDFs only, skip others to email notification"""
    # Ensure folders exist
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(PROCESSED_FOLDER, exist_ok=True)
    os.makedirs(NON_PDF_FOLDER, exist_ok=True)

    # Get attachments that need processing
    attachments_to_process = get_attachments_for_processing(connection)
    
    if not attachments_to_process:
        print("No attachments found that need processing.")
        return

    for attachment_record in attachments_to_process:
        email_id = attachment_record['email_id']
        attachment_sequence = attachment_record['attachment_sequence']
        original_file_path = attachment_record['original_file_path']
        original_file_name = attachment_record['original_file_name']
        file_type = attachment_record['file_type']
        attachment_count = attachment_record['attachment_count']
        po_attachments_found = attachment_record['po_attachments_found']
        subject = attachment_record['subject']
        
        print(f"\nProcessing attachment {attachment_sequence}: {original_file_name}")
        print(f"Email: {subject}")
        print(f"File type: {file_type}, Total attachments: {attachment_count}, PO attachments: {po_attachments_found}")
        
        try:
            # Check if file exists
            if not os.path.exists(original_file_path):
                print(f"File not found: {original_file_path}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        error_message="File not found on disk",
                                        error_step='file_not_found',
                                        retry_count=attachment_record['retry_count'] + 1)
                continue
            
            # Check if this is a PDF file
            if not is_pdf_file(original_file_path, file_type):
                print(f"Non-PDF file detected: {original_file_name} (Type: {file_type})")
                
                # Move non-PDF file to separate folder
                new_path = move_non_pdf_file(original_file_path, original_file_name)
                
                # Skip to email notification step
                skip_to_email_notification(connection, email_id, attachment_sequence,
                                          f"File type {file_type} is not supported for processing", 
                                          original_file_name)
                
                # Update file path
                update_attachment_status(connection, email_id, attachment_sequence, original_file_path=new_path)
                continue
            
            # Handle multiple attachments - inform that processing this specific PDF
            if attachment_count > 1:
                print(f"Email has {attachment_count} attachments, processing attachment {attachment_sequence}: {original_file_name}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        notes=f"Processing attachment {attachment_sequence} of {attachment_count}")
            
            # Update status to indicate PDF processing started
            update_attachment_status(connection, email_id, attachment_sequence, current_step='text_conversion')
            
            # Process PDF intelligently
            text_content, analysis = process_pdf_with_intelligence(
                original_file_path, OUTPUT_FOLDER, connection, email_id, attachment_sequence
            )
            
            if text_content is None:
                print(f"Failed to extract text from {original_file_name}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        retry_count=attachment_record['retry_count'] + 1)
                continue
            
            if text_content:
                # Reverse Hebrew words if needed
                reversed_text = reverse_hebrew_words(text_content)
                
                # Split text into chunks of 60 lines for translation
                lines = reversed_text.split('\n')
                chunk_size = 60
                translated_chunks = []
                
                for i in range(0, len(lines), chunk_size):
                    chunk = '\n'.join(lines[i:i+chunk_size])
                    
                    # Translate chunk to English
                    translated_chunk = translate_text_to_english(chunk)
                    translated_chunks.append(translated_chunk)
                    print(f"Translated chunk {i//chunk_size + 1} for attachment {attachment_sequence}: {original_file_name}")
                
                # Create unique translated filename using original name and sequence
                translated_filename = create_unique_translated_filename(original_file_name, attachment_sequence)
                translated_output_path = os.path.join(OUTPUT_FOLDER, translated_filename)
                
                with open(translated_output_path, 'w', encoding='utf-8') as text_file:
                    text_file.write('\n'.join(translated_chunks))
                
                print(f"Saved translated text to: {translated_output_path}")
                
                # Update database with success
                update_attachment_status(connection, email_id, attachment_sequence,
                                        text_converted='Y',
                                        text_converted_at=datetime.now(),
                                        translated_file_name=translated_filename,
                                        translated_file_path=translated_output_path,
                                        current_step='ai_classification')
                
                # Move the successfully processed PDF with unique name
                base_name = os.path.splitext(original_file_name)[0]
                new_pdf_name = f"{base_name}_seq{attachment_sequence}_Proc.pdf"
                new_pdf_path = os.path.join(PROCESSED_FOLDER, new_pdf_name)
                shutil.move(original_file_path, new_pdf_path)
                print(f"Moved {original_file_name} to processed folder as {new_pdf_name}")
                
                # Update file path in database
                update_attachment_status(connection, email_id, attachment_sequence, original_file_path=new_pdf_path)
                
            else:
                print(f"No text content extracted from {original_file_name}")
                update_attachment_status(connection, email_id, attachment_sequence,
                                        error_message="No text content extracted",
                                        error_step='text_extraction',
                                        retry_count=attachment_record['retry_count'] + 1)
                
        except Exception as e:
            print(f"Error processing attachment {attachment_sequence} ({original_file_name}): {e}")
            update_attachment_status(connection, email_id, attachment_sequence,
                                    error_message=f"Processing error: {str(e)}",
                                    error_step='text_conversion',
                                    retry_count=attachment_record['retry_count'] + 1)

def main():
    """Main function"""
    connection = create_db_connection()
    if not connection:
        print("Failed to connect to database. Exiting.")
        return
    
    print_and_log("Script 2 started - PDF Processing with Multiple Attachments Support")
    
    try:
        print(f"Loaded config - Database: {config['Production']['database']}")
        print(f"Loaded config - Server: {config['Production']['server']}")
        
        process_attachments(connection)
        print_and_log("Script 2 finished - PDF processing completed")
        
    except Exception as e:
        print_and_log(f"Error in main: {e}")
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()