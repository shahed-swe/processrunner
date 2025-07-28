#!/usr/bin/env python3
# test_email_connection.py - Simple IMAP connection test

import imaplib
import configparser

def test_imap_connection():
    """Test IMAP connection with current credentials"""
    
    # Load config
    config = configparser.ConfigParser()
    config.read('configi.ini')
    
    # Read credentials
    try:

        email_addr = "po@supsol-scm.com"
        password = "wxljvjkysxmrzsst"
        print(f"Testing connection for: {email_addr}")
        print(f"Password length: {len(password)} characters")
        print(f"Password (first 4 chars): {password[:4]}...")
        print(f"Password (last 4 chars): ...{password[-4:]}")
        print(f"Full password for debugging: '{password}'")
        print(f"Password hex representation: {password.encode('utf-8').hex()}")
    except Exception as e:
        print(f"Error reading credentials: {e}")
        return
    
    # Get email config
    server = config.get('Email', 'imap_server', fallback='outlook.office365.com')
    port = config.getint('Email', 'imap_port', fallback=993)
    use_ssl = config.getboolean('Email', 'use_ssl', fallback=True)
    
    print(f"Connecting to: {server}:{port} (SSL: {use_ssl})")
    
    try:
        # Connect to IMAP server
        if use_ssl:
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
        
        print("✅ Connected to IMAP server")
        
        # Try login
        try:
            result = mail.login(email_addr, password)
            print(f"✅ Login successful: {result}")
        except imaplib.IMAP4.error as login_error:
            print(f"❌ Login failed: {login_error}")
            
            # Try to get more detailed error info
            try:
                # Send a manual login command to get detailed response
                mail.send(f'{mail._get_tag()} LOGIN "{email_addr}" "{password}"\r\n'.encode())
                response = mail.readline().decode()
                print(f"Raw server response: {response}")
            except:
                pass
            
            raise login_error
        
        # Try selecting inbox
        result = mail.select('inbox')
        print(f"✅ Inbox selected: {result}")
        
        # Get inbox info
        status, messages = mail.search(None, 'ALL')
        if status == 'OK':
            email_count = len(messages[0].split())
            print(f"✅ Found {email_count} emails in inbox")
        
        # Logout
        mail.logout()
        print("✅ Successfully logged out")
        
    except imaplib.IMAP4.error as e:
        print(f"❌ IMAP Error: {e}")
        print("\nPossible solutions:")
        print("1. Generate a new App Password in Microsoft Account Security")
        print("2. Enable IMAP access in Outlook settings")
        print("3. Check if 2FA is properly configured")
        
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        print("\nPossible solutions:")
        print("1. Check internet connection")
        print("2. Verify server settings")
        print("3. Check firewall/proxy settings")

if __name__ == "__main__":
    test_imap_connection()
