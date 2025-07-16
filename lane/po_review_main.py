#PO_review _main.py
import os
import logging
import argparse
import configparser
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Import operations from our modules
from po_database_operation import (
    get_db_connection,
    fetch_open_pos,
    fetch_po_items,
    fetch_po_audit_logs,
    fetch_vendor_language,
    fetch_vendor_details,
    mark_wpq_in_process,
    release_wpq,
    cleanup_stuck_records
)
from po_gpt_operation import (
    prepare_po_gpt_data,
    send_to_gpt,
    parse_gpt_response,
    call_po_api,
    initialize_text_limit
)

# Load environment variables and configure logging
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('po_review.log', encoding='utf-8')
    ]
)

def read_config(config_path):
    """
    Read and validate configuration file.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")

    logging.info(f"Reading configuration from: {config_path}")
    config = configparser.ConfigParser()
    config.read(config_path)
    
    # Validate required sections and keys
    required_sections = ['OpenAI', 'CommunicationTimeframes']
    for section in required_sections:
        if section not in config:
            raise KeyError(f"Required configuration section '{section}' not found")

    # Check if at least one database section exists
    db_sections = ['Database', 'Production']
    if not any(section in config for section in db_sections):
        raise KeyError("No database configuration section found. Need either 'Database' or 'Production' section")

    return config

def should_process_po(audit_logs, config):
    """
    Determine if a PO should be processed based on its audit logs and configuration.
    """
    if not audit_logs:
        logging.info("No audit logs found - PO should be processed")
        return True

    def parse_date(date_value):
        if isinstance(date_value, datetime):
            return date_value
        try:
            return datetime.strptime(date_value, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            logging.error(f"Invalid date format: {date_value}")
            return None

    # Get the most recent action time
    valid_dates = [parse_date(log['CreationDate']) for log in audit_logs if parse_date(log['CreationDate'])]
    if not valid_dates:
        logging.warning("No valid dates found in audit logs")
        return True

    last_action_time = max(valid_dates)
    time_since_last_action = datetime.now() - last_action_time

    # Get maximum wait time from configuration
    communication_timeframes = config['CommunicationTimeframes']
    try:
        max_wait_time = max(
            float(communication_timeframes['SendEmail']),
            float(communication_timeframes['TextHim']),
            float(communication_timeframes['CallHim']),
            float(communication_timeframes['EscalateToCustomer'])
        )
    except (ValueError, KeyError) as e:
        logging.error(f"Error processing communication timeframes: {e}")
        return False

    should_process = time_since_last_action > timedelta(hours=max_wait_time)
    logging.info(f"Time since last action: {time_since_last_action}, Should process: {should_process}")
    return should_process

def process_single_po(connection, po, config, text_limit):
    """
    Process a single PO: mark as in process, fetch related data, prepare for GPT, and send to API.
    """
    wpq_number = po['WPQNumber']
    pq_number = po['PQNumber']
    logging.info(f"\nProcessing PO: {pq_number} (WPQ: {wpq_number})")
    
    # First, mark this WPQ as being processed
    if not mark_wpq_in_process(connection, wpq_number):
        logging.error(f"Failed to mark WPQ {wpq_number} as in process")
        return False
    
    try:
        # Fetch all related data
        po_items = fetch_po_items(connection, wpq_number)
        if not po_items:
            logging.warning(f"No items found for WPQ {wpq_number}")
            release_wpq(connection, wpq_number)  # Release since we can't process
            return False

        audit_logs = fetch_po_audit_logs(connection, wpq_number)
        
        # Check if PO should be processed
        if not should_process_po(audit_logs, config):
            logging.info(f"Skipping PO {pq_number} - recent communication exists")
            release_wpq(connection, wpq_number)  # Release since we're skipping
            return False

        # Get vendor information
        vendor_setup_completed = po.get('VendorSetupProcessCompleted', 0)
        vendor_status = 'Complete' if vendor_setup_completed == 1 else 'Incomplete'
        vendor_language = fetch_vendor_language(connection, po['VendorID'])
        
        # Prepare and send data to GPT
        gpt_data = prepare_po_gpt_data(po, po_items, audit_logs, config, vendor_status, vendor_language, text_limit)
        if not gpt_data:
            logging.error(f"Failed to prepare GPT data for PO {pq_number}")
            release_wpq(connection, wpq_number)
            return False

        gpt_response = send_to_gpt(gpt_data, config['OpenAI']['api_key'])
        if not gpt_response:
            logging.error(f"No response from GPT for PO {pq_number}")
            release_wpq(connection, wpq_number)
            return False

        # Parse GPT response and send to API
        parsed_response = parse_gpt_response(gpt_response)
        if not parsed_response:
            logging.error(f"Failed to parse GPT response for PO {pq_number}")
            release_wpq(connection, wpq_number)
            return False

        # Send to API
        api_success = call_po_api(parsed_response)
        if api_success:
            logging.info(f"Successfully processed PO {pq_number}")
            # Keep ProcessingStatus = 1 to indicate completed processing
            # Or optionally release it if you want to allow reprocessing
            return True
        else:
            logging.error(f"Failed to send API request for PO {pq_number}")
            release_wpq(connection, wpq_number)  # Release for retry
            return False

    except Exception as e:
        logging.error(f"Error processing PO {pq_number}: {str(e)}")
        release_wpq(connection, wpq_number)  # Always release on error
        return False

def main():
    """
    Main function to orchestrate the PO review process.
    """
    logging.info("Starting PO Review System")
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Process POs in the system.")
    parser.add_argument('--WPQ', type=str, help='Specific WPQ number to process')
    parser.add_argument('--config', type=str, default="/path/to/config.ini",
                       help='Path to configuration file')
    parser.add_argument('--cleanup', action='store_true', 
                       help='Clean up stuck records before processing')
    parser.add_argument('--text-limit', type=int, default=1500,
                       help='Text limit for GPT responses (default: 1500)')
    parser.add_argument('--db-section', type=str, default='Database',
                       help='Database configuration section to use (default: Database)')
    args = parser.parse_args()

    try:
        # Read configuration
        config = read_config(args.config)
        logging.info("Configuration loaded successfully")
        
        # Use text limit from command line or initialize
        if args.text_limit:
            text_limit = args.text_limit
            logging.info(f"Using text limit from command line: {text_limit}")
        else:
            text_limit = initialize_text_limit()
            logging.info(f"Text limit set to: {text_limit}")
        
        # Connect to database
        db_section = args.db_section
        if db_section not in config:
            logging.error(f"Database section '{db_section}' not found in configuration")
            return
            
        logging.info(f"Using database configuration from section: {db_section}")
        with get_db_connection(dict(config[db_section])) as connection:
            if not connection:
                logging.error("Failed to connect to the database. Exiting.")
                return

            # Optional: Clean up stuck records first
            if args.cleanup:
                cleanup_stuck_records(connection)

            # Process specific WPQ or all open POs
            if args.WPQ:
                logging.info(f"Processing specific WPQ: {args.WPQ}")
                po = fetch_open_pos(connection, args.WPQ)
                if po:
                    success = process_single_po(connection, po, config, text_limit)
                    if success:
                        logging.info(f"Successfully processed WPQ {args.WPQ}")
                    else:
                        logging.warning(f"Failed to process WPQ {args.WPQ}")
                else:
                    logging.warning(f"No available open PO found for WPQ {args.WPQ}")
            else:
                logging.info("Processing all available open POs")
                open_pos = fetch_open_pos(connection)
                
                if not open_pos:
                    logging.info("No available open POs found to process")
                    return

                processed_count = 0
                skipped_count = 0
                error_count = 0
                
                for po in open_pos:
                    try:
                        success = process_single_po(connection, po, config, text_limit)
                        if success:
                            processed_count += 1
                        else:
                            skipped_count += 1
                    except Exception as e:
                        error_count += 1
                        logging.error(f"Unexpected error processing PO {po.get('PQNumber', 'Unknown')}: {e}")
                
                logging.info(f"Processing complete. Processed: {processed_count}, Skipped: {skipped_count}, Errors: {error_count}")

    except FileNotFoundError as e:
        logging.error(f"Configuration file error: {e}")
    except KeyError as e:
        logging.error(f"Configuration error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in main execution: {str(e)}", exc_info=True)
    
    logging.info("PO Review System completed")

if __name__ == "__main__":
    main()