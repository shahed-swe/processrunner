#!/usr/bin/env python3
# email_handler_linux.py

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict
import configparser

def read_credentials(credentials_file: str) -> tuple:
    """Read email credentials from file"""
    try:
        with open(credentials_file, 'r') as file:
            sender_email = file.readline().strip()
            sender_password = file.readline().strip()
        return sender_email, sender_password
    except Exception as e:
        logging.error(f"Error reading credentials: {e}")
        raise

def create_email_body(wpq: Dict, audit: Dict, is_test: bool = False) -> str:
    """Create email body using existing audit texts"""
    
    # Test mode warning message
    test_warning = ""
    if is_test:
        test_warning = """
        <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; margin-bottom: 20px; border-radius: 5px;">
            <strong>⚠️ AUTOMATED TEST MESSAGE</strong><br>
            This is an automated message that is being sent to you, instead of the vendor, to check if the data is accurate. 
            The system has marked this vendor and service call as needing your attention.
        </div>
        """
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
            .container {{ padding: 20px; }}
            .header {{ background-color: #f8f9fa; padding: 10px; }}
            .content {{ margin: 20px 0; }}
            .footer {{ background-color: #f8f9fa; padding: 10px; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            {test_warning}
            
            <div class="header">
                <h2>SupSol Support: WPQ {wpq['WPQNumber']}</h2>
            </div>
            
            <div class="content">
                <!-- Translated content from audit -->
                <p>{audit.get('Text', 'No message content')}</p>
                <p>Supporter Name: {wpq.get('SupporterName', 'N/A')}</p>
                <p>Supporter Email: {wpq.get('SupporterEmail', 'N/A')}</p>
            </div>

            <div class="content">
                <!-- English content from audit -->
                <h3>English</h3>
                <p>{audit.get('EnglishText', 'No English translation available')}</p>
                <p>Supporter Name: {wpq.get('SupporterName', 'N/A')}</p>
                <p>Supporter Email: {wpq.get('SupporterEmail', 'N/A')}</p>
            </div>

            <div class="footer">
                <p>This is an automated message. Please do not reply directly to this email.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html

def get_smtp_config(config: configparser.ConfigParser) -> Dict:
    """Get SMTP configuration from config file"""
    try:
        smtp_config = {
            'server': config['Email'].get('smtp_server', 'smtp.office365.com'),
            'port': config['Email'].getint('smtp_port', 587),
            'use_tls': config['Email'].getboolean('use_tls', True)
        }
        return smtp_config
    except Exception as e:
        logging.error(f"Error getting SMTP config: {e}")
        # Return default values
        return {
            'server': 'smtp.office365.com',
            'port': 587,
            'use_tls': True
        }

def send_email(config: configparser.ConfigParser, wpq: Dict, audit: Dict, is_test: bool = False) -> bool:
    """Send email using SMTP"""
    try:
        # Get credentials
        credentials_file = config['Email']['credentials_file']
        sender_email, sender_password = read_credentials(credentials_file)

        # Determine recipient and CC
        if is_test:
            recipient_email = wpq.get('SupporterEmail', config['EmailTest']['recipient_email'])
            cc_email = config['EmailTest'].get('cc_email', '')
        else:
            recipient_email = wpq.get('VendorEmail') or wpq.get('TempVendorEmail')
            cc_email = wpq.get('SupporterEmail', '')

        if not recipient_email:
            logging.error(f"Missing recipient email for WPQ {wpq['WPQNumber']}")
            return False

        # Get SMTP configuration
        smtp_config = get_smtp_config(config)

        # Create email message
        msg = MIMEMultipart('alternative')
        
        # Set email headers
        subject_prefix = "[TEST] " if is_test else ""
        msg['Subject'] = f"{subject_prefix}SupSol Support: WPQ {wpq['WPQNumber']}"
        msg['From'] = sender_email
        msg['To'] = recipient_email
        
        if cc_email:
            msg['Cc'] = cc_email

        # Create HTML body
        html_body = create_email_body(wpq, audit, is_test)
        
        # Create plain text version as fallback
        plain_text = f"""
SupSol Support: WPQ {wpq['WPQNumber']}

{"[TEST MESSAGE] " if is_test else ""}

Message: {audit.get('Text', 'No message content')}

English: {audit.get('EnglishText', 'No English translation available')}

Supporter Name: {wpq.get('SupporterName', 'N/A')}
Supporter Email: {wpq.get('SupporterEmail', 'N/A')}

This is an automated message. Please do not reply directly to this email.
        """

        # Attach both plain text and HTML versions
        part1 = MIMEText(plain_text, 'plain')
        part2 = MIMEText(html_body, 'html')
        
        msg.attach(part1)
        msg.attach(part2)

        # Connect to SMTP server and send email
        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            if smtp_config['use_tls']:
                server.starttls()
            
            server.login(sender_email, sender_password)
            
            # Prepare recipient list
            recipients = [recipient_email]
            if cc_email:
                recipients.append(cc_email)
            
            # Send email
            text = msg.as_string()
            server.sendmail(sender_email, recipients, text)

        mode = "TEST MODE" if is_test else "PRODUCTION"
        logging.info(f"Email sent successfully ({mode}) for WPQ {wpq['WPQNumber']} to {recipient_email}")
        if cc_email:
            logging.info(f"CC sent to: {cc_email}")
        
        return True

    except smtplib.SMTPAuthenticationError as e:
        logging.error(f"SMTP Authentication failed for WPQ {wpq['WPQNumber']}: {e}")
        return False
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error for WPQ {wpq['WPQNumber']}: {e}")
        return False
    except Exception as e:
        logging.error(f"Failed to send email for WPQ {wpq['WPQNumber']}: {e}")
        return False

def validate_email_config(config: configparser.ConfigParser) -> bool:
    """Validate email configuration"""
    try:
        # Check required sections
        if 'Email' not in config or 'EmailTest' not in config:
            logging.error("Missing Email or EmailTest sections in configuration")
            return False

        # Check required fields in Email section
        email_fields = ['credentials_file']
        for field in email_fields:
            if field not in config['Email']:
                logging.error(f"Missing {field} in Email configuration")
                return False

        # Check if credentials file exists and is readable
        credentials_file = config['Email']['credentials_file']
        try:
            sender_email, sender_password = read_credentials(credentials_file)
            if not sender_email or not sender_password:
                logging.error("Invalid or empty credentials in credentials file")
                return False
        except Exception as e:
            logging.error(f"Cannot read credentials file: {e}")
            return False

        # Check EmailTest section
        if 'recipient_email' not in config['EmailTest']:
            logging.error("Missing recipient_email in EmailTest configuration")
            return False

        logging.info("Email configuration validation passed")
        return True

    except Exception as e:
        logging.error(f"Error validating email config: {e}")
        return False

def test_smtp_connection(config: configparser.ConfigParser) -> bool:
    """Test SMTP connection"""
    try:
        credentials_file = config['Email']['credentials_file']
        sender_email, sender_password = read_credentials(credentials_file)
        smtp_config = get_smtp_config(config)

        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            if smtp_config['use_tls']:
                server.starttls()
            
            server.login(sender_email, sender_password)
            logging.info("SMTP connection test successful")
            return True

    except Exception as e:
        logging.error(f"SMTP connection test failed: {e}")
        return False