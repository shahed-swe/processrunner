#po_gpt_operation-fixed.py

import openai
import json
import logging
import re
import http.client
from datetime import datetime

def read_prompt_file(file_path):
    """
    Read and return the content of the prompt template file.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        logging.error(f"Prompt file not found: {file_path}")
        return None
    except Exception as e:
        logging.error(f"Error reading prompt file: {str(e)}")
        return None

def prepare_po_gpt_data(po, po_items, audit_logs, config, vendor_status, vendor_language, text_limit):
    """
    Prepare data for GPT processing by combining PO information, items, and audit logs.
    """
    logging.info(f"Preparing GPT data for WPQ: {po.get('WPQNumber')}")
    
    prompt = read_prompt_file('PO_chatgpt_prompt.txt')
    if not prompt:
        return None

    # Format line items into a readable table structure
    line_items = []
    for item in po_items:
        line_item = (
            f"- Description: {item.get('ServiceDescription', 'N/A')}\n"
            f"  Initial Execution Date: {format_date(item.get('InitialExecutionDate'))}\n"
            f"  Current Execution Date: {format_date(item.get('CurrentExecutionDate'))}\n"
            f"  Requested Execution Date: {format_date(item.get('RequestedExecutionDate'))}\n"
            f"  Cost: {format_price(item.get('PurchasePrice'))}"
        )
        line_items.append(line_item)
    
    formatted_line_items = "\n".join(line_items)

    # Format audit logs with proper date formatting
    audit_logs_formatted = []
    for log in audit_logs:
        log_entry = (
            f"Date: {format_date(log.get('CreationDate'))}\n"
            f"Type: {log.get('AuditTypeID', 'N/A')}\n"
            f"Status: {log.get('ExecutionStatus', 'N/A')}\n"
            f"Text: {log.get('Text', 'N/A')}\n"
            f"Mail ID: {log.get('_MailID', 'N/A')}"
        )
        audit_logs_formatted.append(log_entry)
    
    formatted_audit_logs = "\n\n".join(audit_logs_formatted)

    # Extract and format mail IDs
    mail_ids = []
    for log in audit_logs:
        if log.get('_MailID'):
            mail_id_entry = (
                f"Mail ID: {log.get('_MailID', 'N/A')}, "
                f"Subject: {log.get('Subject', 'N/A')}"
            )
            mail_ids.append(mail_id_entry)
    
    formatted_mail_ids = "\n".join(mail_ids)

    # Format the data using PQNumber
    data = prompt.format(
        service="Vendor Setup",
        wpq_number=po.get('WPQNumber', 'N/A'),
        po_number=po.get('PQNumber', 'N/A'),
        creation_date=format_date(po.get('CreationDate')),
        urgency_type=po.get('UrgencyType', 'Not specified'),
        vendor_status=vendor_status,
        vendor_language=vendor_language,
        line_items=formatted_line_items,
        audit_logs=formatted_audit_logs,
        mail_ids=formatted_mail_ids,
        text_limit=text_limit
    )

    logging.info(f"Successfully prepared GPT data for WPQ: {po.get('WPQNumber')}")
    return data

def send_to_gpt(data, api_key):
    """
    Send prepared data to GPT API and get response.
    Updated to use newer OpenAI API format.
    """
    logging.info("Sending data to GPT API")
    
    # Set the API key for the client
    client = openai.OpenAI(api_key=api_key)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an AI assistant helping with vendor communication for Purchase Orders."},
                {"role": "user", "content": data}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        logging.info("Successfully received GPT response")
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Error sending data to ChatGPT: {str(e)}")
        return None

def parse_gpt_response(response):
    """
    Parse GPT response and extract the JSON content.
    """
    logging.info("Parsing GPT response")
    try:
        # Use regex to find the JSON object in the response
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in the response")
        
        json_str = json_match.group()
        parsed_response = json.loads(json_str)
        
        # Validate required fields
        required_fields = ['wpqNumber', 'auditTypeID', 'executionStatus', 'actionStatus', 
                          'category', 'service', 'subject', 'text', 'englishText']
        
        for field in required_fields:
            if field not in parsed_response:
                raise ValueError(f"Missing required field: {field}")

        logging.info("Successfully parsed GPT response")
        return parsed_response
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse GPT response as JSON: {e}")
        return None
    except ValueError as e:
        logging.error(f"Error in GPT response: {e}")
        return None

def call_po_api(json_response):
    """
    Send the processed data to the PO API endpoint.
    """
    logging.info(f"Calling PO API for WPQ {json_response.get('wpqNumber')}")
    
    conn = http.client.HTTPSConnection("support.supsol-scm.com")
    
    payload = json.dumps({
        "wpqNumber": json_response.get('wpqNumber'),
        "auditTypeID": json_response.get('auditTypeID'),
        "executionStatus": json_response.get('executionStatus'),
        "actionStatus": json_response.get('actionStatus'),
        "category": json_response.get('category'),
        "service": json_response.get('service'),
        "subject": json_response.get('subject'),
        "text": json_response.get('text'),
        "englishText": json_response.get('englishText'),
        "_MailID": json_response.get('_MailID', ''),
        "_ConversationID": json_response.get('_ConversationID', 0),
        "_Future1": json_response.get('_Future1', 0),
        "_Future2": json_response.get('_Future2', 0)
    })
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    try:
        conn.request("POST", "/api/v1/ServiceCall/AuditCreate", payload, headers)
        response = conn.getresponse()
        data = response.read()
        
        if response.status == 200:
            logging.info(f"Successfully sent data to API for WPQ {json_response['wpqNumber']}")
            return True
        else:
            logging.error(f"HTTP Error {response.status} sending data to API: {data.decode('utf-8')}")
            return False
    except Exception as e:
        logging.error(f"Error sending data to API: {str(e)}")
        return False
    finally:
        conn.close()

def format_date(date_value):
    """
    Format date values consistently.
    """
    if not date_value:
        return 'N/A'
    
    if isinstance(date_value, str):
        try:
            date_value = datetime.strptime(date_value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return date_value
    
    return date_value.strftime('%Y-%m-%d %H:%M:%S')

def format_price(price):
    """
    Format price values consistently.
    """
    if price is None:
        return 'N/A'
    try:
        return f"{float(price):,.2f}"
    except (ValueError, TypeError):
        return str(price)

def initialize_text_limit(default_limit=1500):
    """
    Initialize text limit for the application.
    For cron/automated runs, returns default value instead of asking for user input.
    """
    # Check if running in interactive mode (has a terminal)
    import sys
    if sys.stdin.isatty():
        # Interactive mode - ask user
        return get_user_input_text_limit()
    else:
        # Non-interactive mode (cron) - use default
        logging.info(f"Running in non-interactive mode, using default text limit: {default_limit}")
        return default_limit

def get_user_input_text_limit():
    """
    Get text limit from user input with validation.
    """
    while True:
        try:
            text_limit = int(input("Enter the text limit for GPT responses: "))
            if text_limit > 0:
                return text_limit
            else:
                print("Please enter a positive integer.")
        except ValueError:
            print("Invalid input. Please enter a positive integer.")
        except EOFError:
            # Handle case where input is not available (like in cron)
            logging.info("No input available, using default text limit: 1500")
            return 1500