# email_handler_graph.py

import requests
import msal
import logging
import time
from typing import Dict
import configparser

class GraphEmailSender:
    """Microsoft Graph API client for sending emails"""
    
    def __init__(self, config: configparser.ConfigParser):
        self.config = config
        self.access_token = None
        self.token_expires_at = None
        self.logger = logging.getLogger(__name__)
        
        # Load Graph API configuration
        try:
            self.graph_config = {
                'client_id': config['GraphAPI']['client_id'],
                'client_secret': config['GraphAPI']['client_secret'],
                'tenant_id': config['GraphAPI']['tenant_id'],
                'user_email': config['GraphAPI']['user_email']
            }
        except KeyError as e:
            self.logger.error(f"Missing GraphAPI configuration: {e}")
            raise ValueError(f"Missing GraphAPI configuration: {e}")
    
    def _get_access_token(self) -> str:
        """Get or refresh access token"""
        try:
            if self.access_token and self.token_expires_at:
                if time.time() < self.token_expires_at - 300:  # 5 min buffer
                    return self.access_token
            
            app = msal.ConfidentialClientApplication(
                client_id=self.graph_config['client_id'],
                client_credential=self.graph_config['client_secret'],
                authority=f"https://login.microsoftonline.com/{self.graph_config['tenant_id']}"
            )
            
            result = app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
            
            if "access_token" in result:
                self.access_token = result["access_token"]
                expires_in = result.get("expires_in", 3600)
                self.token_expires_at = time.time() + expires_in
                self.logger.info("Successfully obtained Graph API access token")
                return self.access_token
            else:
                error_msg = result.get('error_description', 'Unknown error')
                self.logger.error(f"Failed to get access token: {error_msg}")
                raise Exception(f"Failed to get access token: {error_msg}")
                
        except Exception as e:
            self.logger.error(f"Exception getting access token: {e}")
            raise
    
    def send_email_via_graph(self, to_recipients: list, cc_recipients: list, subject: str, 
                           html_body: str, plain_body: str) -> bool:
        """Send email using Graph API"""
        try:
            access_token = self._get_access_token()
            
            url = f"https://graph.microsoft.com/v1.0/users/{self.graph_config['user_email']}/sendMail"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Build recipients list
            to_recipients_list = [{"emailAddress": {"address": email}} for email in to_recipients]
            cc_recipients_list = [{"emailAddress": {"address": email}} for email in cc_recipients if email]
            
            # Build email message
            email_message = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "HTML",
                        "content": html_body
                    },
                    "toRecipients": to_recipients_list,
                    "from": {
                        "emailAddress": {
                            "address": self.graph_config['user_email']
                        }
                    }
                }
            }
            
            # Add CC recipients if any
            if cc_recipients_list:
                email_message["message"]["ccRecipients"] = cc_recipients_list
            
            response = requests.post(url, headers=headers, json=email_message)
            
            if response.status_code == 202:  # Accepted
                self.logger.info(f"Email sent successfully via Graph API")
                return True
            else:
                self.logger.error(f"Failed to send email: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"Exception sending email via Graph API: {e}")
            return False

def read_credentials(credentials_file: str) -> tuple:
    """Read email credentials from file (kept for compatibility, not used with Graph API)"""
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

def create_plain_email_body(wpq: Dict, audit: Dict, is_test: bool = False) -> str:
    """Create plain text email body"""
    test_prefix = "[TEST MESSAGE] " if is_test else ""
    
    plain_text = f"""
{test_prefix}SupSol Support: WPQ {wpq['WPQNumber']}

Message: {audit.get('Text', 'No message content')}

English: {audit.get('EnglishText', 'No English translation available')}

Supporter Name: {wpq.get('SupporterName', 'N/A')}
Supporter Email: {wpq.get('SupporterEmail', 'N/A')}

This is an automated message. Please do not reply directly to this email.
    """
    return plain_text

def get_smtp_config(config: configparser.ConfigParser) -> Dict:
    """Get SMTP configuration from config file (kept for compatibility)"""
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
    """Send email using Graph API (main function - signature unchanged)"""
    logger = logging.getLogger(__name__)
    
    try:
        # Initialize Graph API sender
        graph_sender = GraphEmailSender(config)
        
        # Determine recipient and CC
        if is_test:
            recipient_email = wpq.get('SupporterEmail', config['EmailTest']['recipient_email'])
            cc_email = config['EmailTest'].get('cc_email', '')
        else:
            recipient_email = wpq.get('VendorEmail') or wpq.get('TempVendorEmail')
            cc_email = wpq.get('SupporterEmail', '')

        if not recipient_email:
            logger.error(f"Missing recipient email for WPQ {wpq['WPQNumber']}")
            return False

        # Prepare recipients lists
        to_recipients = [recipient_email]
        cc_recipients = [cc_email] if cc_email else []

        # Create email subject
        subject_prefix = "[TEST] " if is_test else ""
        subject = f"{subject_prefix}SupSol Support: WPQ {wpq['WPQNumber']}"

        # Create email bodies
        html_body = create_email_body(wpq, audit, is_test)
        plain_body = create_plain_email_body(wpq, audit, is_test)

        # Send email via Graph API
        success = graph_sender.send_email_via_graph(
            to_recipients=to_recipients,
            cc_recipients=cc_recipients,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body
        )

        if success:
            mode = "TEST MODE" if is_test else "PRODUCTION"
            logger.info(f"Email sent successfully ({mode}) for WPQ {wpq['WPQNumber']} to {recipient_email}")
            if cc_email:
                logger.info(f"CC sent to: {cc_email}")
        
        return success

    except Exception as e:
        logger.error(f"Failed to send email for WPQ {wpq['WPQNumber']}: {e}")
        return False

def validate_email_config(config: configparser.ConfigParser) -> bool:
    """Validate email configuration (updated for Graph API)"""
    try:
        # Check required sections
        if 'GraphAPI' not in config or 'EmailTest' not in config:
            logging.error("Missing GraphAPI or EmailTest sections in configuration")
            return False

        # Check required fields in GraphAPI section
        graph_fields = ['client_id', 'client_secret', 'tenant_id', 'user_email']
        for field in graph_fields:
            if field not in config['GraphAPI']:
                logging.error(f"Missing {field} in GraphAPI configuration")
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
    """Test Graph API connection (replaces SMTP test)"""
    logger = logging.getLogger(__name__)
    
    try:
        graph_sender = GraphEmailSender(config)
        # Test by getting access token
        access_token = graph_sender._get_access_token()
        
        if access_token:
            logger.info("Graph API connection test successful")
            return True
        else:
            logger.error("Graph API connection test failed")
            return False

    except Exception as e:
        logger.error(f"Graph API connection test failed: {e}")
        return False