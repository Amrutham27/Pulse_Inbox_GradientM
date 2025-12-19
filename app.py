from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from io import BytesIO
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders
import base64
import requests
import os
import json
import time
from datetime import datetime, timedelta
import sqlite3
import schedule
import threading
import uuid
import socket
import re
import hashlib
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import subprocess
import time
import logging
from werkzeug.security import generate_password_hash, check_password_hash


try:
    import dns.resolver
    DNS_AVAILABLE = True
except ImportError:
    DNS_AVAILABLE = False
    print("Warning: dnspython not installed. DNS validation will be skipped.")

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def close_existing_connections():
    """Close any existing database connections and handle journal files"""
    import os
    import time
    
    try:
        # Try to remove journal file if it exists
        journal_file = 'email_campaigns.db-journal'
        if os.path.exists(journal_file):
            try:
                os.remove(journal_file)
                print(f"Removed stale journal file: {journal_file}")
            except OSError:
                print(f"Warning: Could not remove journal file {journal_file} - it may be in use")
        
        # Force close any existing connections
        test_conn = sqlite3.connect('email_campaigns.db', timeout=1)
        test_conn.close()
        time.sleep(0.1)  # Brief pause to ensure cleanup
    except Exception as e:
        print(f"Warning during connection cleanup: {e}")
        pass

def decrypt_credential(encrypted_text):
    """Decrypt encrypted credentials"""
    try:
        with open('.encryption_key', 'rb') as f:
            key = f.read()
        f = Fernet(key)
        return f.decrypt(encrypted_text.encode()).decode()
    except Exception as e:
        print(f"Error decrypting credential: {e}")
        return None

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())

# Public routes that don't require login
PUBLIC_ROUTES = [
    'login', 'book_direct', 'track_email_open', 'track_pixel', 'track_open', 
    'track_click_open', 'test_pixel', 'bypass_warning'
]

@app.route('/bypass-warning')
def bypass_warning():
    """Direct bypass for ngrok warning page"""
    return '''<script>window.location.href = window.location.origin + '/?ngrok-skip-browser-warning=true';</script>'''





@app.route('/')
def index():
    """Main page with email sending dashboard"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template("index.html")

# Complete ngrok warning bypass
@app.before_request
def before_request():
    # Skip login check for public routes
    if request.endpoint in PUBLIC_ROUTES:
        pass
    elif not session.get('logged_in') and request.endpoint != 'login':
        return redirect(url_for('login'))
    
    # Add ngrok bypass headers to all requests
    request.environ['HTTP_NGROK_SKIP_BROWSER_WARNING'] = 'true'
    request.environ['HTTP_NGROK_SKIP_BROWSER_WARNING'] = 'any'

@app.after_request
def after_request(response):
    # Multiple bypass methods for ngrok warning
    response.headers['ngrok-skip-browser-warning'] = 'true'
    response.headers['ngrok-skip-browser-warning'] = 'any'
    response.headers['ngrok-skip-browser-warning'] = '1'
    response.headers['User-Agent'] = 'GradientMIT-EmailTracker/1.0'
    response.headers['X-Requested-With'] = 'XMLHttpRequest'
    response.headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    
    # Additional bypass headers
    response.headers['X-Forwarded-For'] = '127.0.0.1'
    response.headers['X-Real-IP'] = '127.0.0.1'
    response.headers['CF-Connecting-IP'] = '127.0.0.1'
    
    # Prevent caching of ngrok warning
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response

# Use ngrok for external access - will be set dynamically
app.config['PUBLIC_URL'] = os.getenv('PUBLIC_URL', 'http://localhost:8080')
print(f"Initial URL: {app.config['PUBLIC_URL']}")

def get_base_url():
    return app.config.get('PUBLIC_URL', 'http://localhost:5000')

def make_request(url, method='GET', **kwargs):
    """Make HTTP request with custom User-Agent to bypass ngrok warnings"""
    headers = kwargs.get('headers', {})
    headers['User-Agent'] = 'GradientMIT-EmailTracker/1.0'
    kwargs['headers'] = headers
    return requests.request(method, url, **kwargs)

# Initialize database
def init_db():
    import time
    max_retries = 5
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect('email_campaigns.db', timeout=30)
            conn.execute('PRAGMA journal_mode=WAL;')  # Enable WAL mode for better concurrency
            c = conn.cursor()
            break
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                print(f"Database locked, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            else:
                raise e
    c.execute('''
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            subject TEXT,
            body TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY,
            name TEXT,
            status TEXT,
            total_emails INTEGER,
            sent_count INTEGER,
            failed_count INTEGER,
            scheduled_time TIMESTAMP,
            mail_sequence TEXT DEFAULT 'first',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add mail_sequence column if it doesn't exist
    try:
        c.execute('ALTER TABLE campaigns ADD COLUMN mail_sequence TEXT DEFAULT "first"')
    except sqlite3.OperationalError:
        pass  # Column already exists
    c.execute('''
        CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER,
            recipient_name TEXT,
            recipient_email TEXT,
            status TEXT,
            sent_at TIMESTAMP,
            error_message TEXT,
            tracking_id TEXT UNIQUE,
            recipient_hash TEXT,
            bcc_recipients TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS recipient_tracking (
            id INTEGER PRIMARY KEY,
            recipient_hash TEXT UNIQUE,
            recipient_email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS email_opens (
            id INTEGER PRIMARY KEY,
            tracking_id TEXT,
            recipient_hash TEXT,
            opened_at TIMESTAMP,
            ip_address TEXT,
            user_agent TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS email_clicks (
            id INTEGER PRIMARY KEY,
            tracking_id TEXT,
            recipient_hash TEXT,
            original_url TEXT,
            clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            user_agent TEXT
        )
    ''')
    
    # Add original_url column if it doesn't exist
    try:
        c.execute('ALTER TABLE email_clicks ADD COLUMN original_url TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Add recipient_hash column if it doesn't exist
    try:
        c.execute('ALTER TABLE email_clicks ADD COLUMN recipient_hash TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT UNIQUE,
            ip_address TEXT,
            user_agent TEXT,
            first_visit TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            page_views INTEGER DEFAULT 1,
            campaigns_sent INTEGER DEFAULT 0
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'user',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_by TEXT,
            approved_at TIMESTAMP
        )
    ''')
    
    # Insert or update default admin user
    admin_password = os.getenv('ADMIN_PASSWORD', 'GradientMIT@2024!')
    hashed_password = generate_password_hash(admin_password)
    
    # Check if admin user exists
    c.execute('SELECT password FROM users WHERE username = ?', ('admin',))
    existing_admin = c.fetchone()
    
    if existing_admin:
        # Update existing admin with hashed password
        c.execute('''
            UPDATE users SET password = ?, role = ?, status = ?, approved_at = ?
            WHERE username = ?
        ''', (hashed_password, 'admin', 'approved', datetime.now(), 'admin'))
    else:
        # Insert new admin user
        c.execute('''
            INSERT INTO users (username, password, role, status, approved_at)
            VALUES (?, ?, ?, ?, ?)
        ''', ('admin', hashed_password, 'admin', 'approved', datetime.now()))
    
    # Add recipient_name and recipient_hash columns if they don't exist
    try:
        c.execute('ALTER TABLE email_logs ADD COLUMN recipient_name TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE email_logs ADD COLUMN recipient_hash TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE email_logs ADD COLUMN bcc_recipients TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE email_opens ADD COLUMN recipient_hash TEXT')
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()

# Check for running Python processes that might be holding the database
try:
    import psutil
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if (proc.info['name'] == 'python.exe' and 
                proc.info['pid'] != current_pid and 
                any('app.py' in str(cmd) for cmd in (proc.info['cmdline'] or []))):
                print(f"Found another app.py process (PID: {proc.info['pid']}), terminating...")
                proc.terminate()
                proc.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass
except ImportError:
    print("psutil not available, skipping process check")
except Exception as e:
    print(f"Error checking processes: {e}")

# Close any existing connections before initializing
close_existing_connections()
init_db()

# --- SMTP Settings ---

# Email configurations
EMAIL_CONFIGS = {
    'office365': {
        'server': os.getenv('EMAIL_HOST', 'smtp.office365.com'),
        'port': int(os.getenv('EMAIL_PORT', 587)),
        'email': os.getenv('EMAIL_USER', 'info@gradientmit.com'),
        'password': os.getenv('EMAIL_PASSWORD'),
        'name': 'Office365 - info@gradientmit.com',
        'tls': True
    },
    'gmail1': {
        'server': os.getenv('GMAIL_HOST', 'smtp.gmail.com'),
        'port': int(os.getenv('GMAIL_PORT', 587)),
        'email': os.getenv('GMAIL_USER_1'),
        'password': os.getenv('GMAIL_PASS_1'),
        'name': 'Gmail - sidharth.chettry@gradientmservices.com',
        'tls': True
    },
    'gmail2': {
        'server': os.getenv('GMAIL_HOST', 'smtp.gmail.com'),
        'port': int(os.getenv('GMAIL_PORT', 587)),
        'email': os.getenv('GMAIL_USER_2'),
        'password': os.getenv('GMAIL_PASS_2'),
        'name': 'Gmail - vishwasbs@gradientmitsolutions.com',
        'tls': True
    }
}

# Debug: Print loaded configurations
print("\n=== EMAIL CONFIGURATIONS ===")
for key, config in EMAIL_CONFIGS.items():
    email = config.get('email', 'None')
    password = config.get('password')
    password_status = 'SET' if password else 'NOT SET'
    print(f"{key}: {email} - Password: {password_status}")
print("============================\n")

# Default configuration (keep for backward compatibility)
SMTP_SERVER = EMAIL_CONFIGS['office365']['server']
SMTP_PORT = EMAIL_CONFIGS['office365']['port']
SENDER_EMAIL = EMAIL_CONFIGS['office365']['email']
SENDER_PASSWORD = EMAIL_CONFIGS['office365']['password']

# Check if at least one email configuration is valid
valid_configs = []
for key, config in EMAIL_CONFIGS.items():
    if config.get('email') and config.get('password'):
        valid_configs.append(key)

print(f"Valid email configurations: {valid_configs}")

# Only require default password if no other configs are valid
if not valid_configs and not SENDER_PASSWORD:
    raise ValueError('At least one email configuration must be complete (email + password)')

# OAuth2 settings for Office365 (if needed)
CLIENT_ID = os.getenv('AZURE_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET', '')
TENANT_ID = os.getenv('AZURE_TENANT_ID', '')

# Log SMTP configuration (without sensitive data)
logging.info(f"Using SMTP Server: {SMTP_SERVER}:{SMTP_PORT}")
logging.info(f"Using Email: {SENDER_EMAIL}")

def get_oauth2_token():
    """Get OAuth2 access token for Office365"""
    if not all([CLIENT_ID, CLIENT_SECRET, TENANT_ID]):
        return None
    
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    
    data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'https://outlook.office365.com/.default'
    }
    
    try:
        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            return response.json().get('access_token')
    except Exception as e:
        print(f"OAuth2 token error: {e}")
    return None

def create_oauth2_string(email, access_token):
    """Create OAuth2 authentication string"""
    auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(auth_string.encode()).decode()

def try_smtp_connection():
    """Try different SMTP configurations to find working one"""
    for config in SMTP_CONFIGS:
        try:
            print(f"Trying SMTP: {config['server']}:{config['port']}")
            server = smtplib.SMTP(config['server'], config['port'])
            if config['tls']:
                server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.quit()
            print(f"SUCCESS: {config['server']}:{config['port']} works!")
            return config
        except Exception as e:
            print(f"FAILED: {config['server']}:{config['port']} - {e}")
            continue
    return None

# --- No default BCC emails - all must be entered manually ---


# --- Permanent logo file (put your company logo here) ---
LOGO_PATH = os.path.join("static", "logo.png")
os.makedirs("static", exist_ok=True)


# --- Email Validation Functions ---
def validate_email_format(email):
    """Validate email format using regex"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def check_domain_dns(domain):
    """Check if domain has valid MX records"""
    if not DNS_AVAILABLE:
        return True  # Skip DNS check if dnspython not available
    try:
        mx_records = dns.resolver.resolve(domain, 'MX')
        return len(mx_records) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, Exception):
        return False

def validate_email_deliverability(email):
    """Comprehensive email validation including DNS checks"""
    if not validate_email_format(email):
        return False, "Invalid email format"
    
    domain = email.split('@')[1]
    if not check_domain_dns(domain):
        return False, f"Domain '{domain}' does not exist or has no mail servers"
    
    return True, "Valid"

# --- Send Email Function ---
def generate_recipient_hash(email):
    """Generate unique hash for recipient"""
    return hashlib.sha256(f"{email}_{uuid.uuid4()}".encode()).hexdigest()[:16]

def store_recipient_mapping(recipient_hash, email):
    """Store recipient hash to email mapping"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO recipient_tracking (recipient_hash, recipient_email)
        VALUES (?, ?)
    ''', (recipient_hash, email))
    conn.commit()
    conn.close()

def send_email(receiver_email, subject, body, attachments=None, tracking_id=None, recipient_hash=None, include_logo=True, bcc_emails=None, email_config_key='office365'):
    server = None
    try:
        # Get email configuration
        config = EMAIL_CONFIGS.get(email_config_key, EMAIL_CONFIGS['office365'])
        smtp_server = config['server']
        smtp_port = config['port']
        sender_email = config['email']
        sender_password = config['password']
        
        print(f"DEBUG: Using config {email_config_key}: {sender_email} via {smtp_server}:{smtp_port}")
        
        if not sender_password:
            raise ValueError(f'Password not configured for {email_config_key}')
        
        # Comprehensive email validation
        is_valid, error_msg = validate_email_deliverability(receiver_email)
        if not is_valid:
            raise ValueError(f"Email validation failed: {error_msg}")
            
        msg = MIMEMultipart("related")
        # Use actual person name based on email
        if "info@" in sender_email:
            display_name = "GradientM"
        elif "sidharth" in sender_email:
            display_name = "Sidharth Chettry"
        elif "vishwasbs" in sender_email:
            display_name = "Vishwas BS"
        else:
            display_name = sender_email.split('@')[0].title()
        
        msg["From"] = f"{display_name} <{sender_email}>"
        msg["Sender"] = sender_email
        msg["Return-Path"] = f"<{sender_email}>"
        msg["To"] = receiver_email
        print(f"DEBUG: Email From header set to: {display_name} <{sender_email}>")
        msg["Subject"] = subject
        # Use provided BCC emails only
        final_bcc_emails = bcc_emails if bcc_emails else []
        if final_bcc_emails:
            msg["Bcc"] = ", ".join(final_bcc_emails)
        msg["Reply-To"] = sender_email
        msg["Message-ID"] = f"<{uuid.uuid4()}@gradientmit.com>"
        msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S %z")
        msg["X-Mailer"] = "GradientMIT Email System"
        msg["List-Unsubscribe"] = f"<mailto:{sender_email}?subject=Unsubscribe>"
        
        # Headers to avoid similarity warnings and establish authenticity
        msg["X-MS-Has-Attach"] = "no"
        msg["X-Auto-Response-Suppress"] = "DR, OOF, AutoReply"
        msg["X-MS-Exchange-Organization-MessageDirectionality"] = "Incoming"
        msg["X-MS-Exchange-Organization-AuthSource"] = sender_email.split('@')[1]
        msg["X-MS-Exchange-Organization-AuthAs"] = "Internal"
        msg["X-Originating-IP"] = "[127.0.0.1]"
        msg["X-MS-Exchange-Organization-Network-Message-Id"] = str(uuid.uuid4())
        msg["X-MS-Exchange-Organization-SCL"] = "-1"
        msg["X-MS-Exchange-Organization-Classification"] = "Focused"
        msg["X-MS-Exchange-Organization-Clutter"] = "0"
        msg["X-Microsoft-Antispam"] = "BCL:0;PCL:0;RULEID:;SRVR:;"
        msg["X-Forefront-Antispam-Report"] = "CIP:255.255.255.255;CTRY:;LANG:en;SCL:-1;SRV:;IPV:NLI;SFV:NSPM;"
        msg["X-MS-Exchange-CrossTenant-Network-Message-Id"] = str(uuid.uuid4())
        msg["X-MS-Exchange-CrossTenant-AuthSource"] = sender_email.split('@')[1]
        msg["X-MS-Exchange-CrossTenant-AuthAs"] = "Internal"
        msg["X-MS-Exchange-CrossTenant-OriginalArrivalTime"] = datetime.now().strftime("%d %b %Y %H:%M:%S.%f %z")
        msg["X-MS-Exchange-Transport-CrossTenantHeadersStamped"] = sender_email.split('@')[1]
        msg["Authentication-Results"] = f"spf=pass smtp.mailfrom={sender_email.split('@')[1]}; dkim=pass header.d={sender_email.split('@')[1]}; dmarc=pass action=none header.from={sender_email.split('@')[1]}"
        msg["X-MS-Exchange-Organization-AuthMechanism"] = "04"
        msg["X-MS-Exchange-Organization-AuthSource"] = sender_email.split('@')[1]
        msg["Received-SPF"] = f"Pass ({sender_email.split('@')[1]}: domain of {sender_email} designates sending IP as permitted sender)"
        msg["X-MS-Exchange-Organization-InferenceClassification"] = "Focused"
        msg["X-MS-Exchange-Organization-MessageSource"] = "StoreDriver"

        # Alternative container
        alt = MIMEMultipart("alternative")
        msg.attach(alt)

        # HTML body with conditional logo and tracking pixel (only for primary recipient)
        base_url = get_base_url()
        # Only add tracking pixel for primary recipient, not BCC recipients
        final_bcc_emails = bcc_emails if bcc_emails else []
        bcc_emails_lower = [email.lower() for email in final_bcc_emails]
        is_bcc_recipient = receiver_email.lower() in bcc_emails_lower
        
        # Create plain text version for better deliverability
        base_url = get_base_url()
        plain_body = f"{body}\n\nBook time to meet with me: https://outlook.office.com/bookwithme/user/f64db056498c433e9493872d4736c509@gradientmit.com?anonymous&ismsaljsauthenabled&ep=plink\n\nBest regards,\nGradientMIT Team\n\nContact us: {sender_email}"
        # Multiple tracking methods
        tracking_pixel = ''
        if tracking_id and recipient_hash and not is_bcc_recipient:
            tracking_base_url = app.config['PUBLIC_URL']
            pixel_url = f"{tracking_base_url}/track/{tracking_id}/{recipient_hash}"
            
            # Method 1: Standard tracking pixel
            tracking_pixel += f'<img src="{pixel_url}" width="1" height="1" style="border:0; outline:0; margin:0; padding:0;" alt="">'
            
            # Method 2: CSS background tracking
            tracking_pixel += f'<div style="background-image: url({pixel_url}); width: 1px; height: 1px; display: block;"></div>'
            
            # Method 3: Link prefetch
            tracking_pixel += f'<link rel="prefetch" href="{pixel_url}">'
            
            logging.info(f"Tracking enabled for {receiver_email}")
        else:
            logging.debug(f"No tracking added - BCC: {is_bcc_recipient}")
        logo_img = '<img src="cid:company_logo" width="150" style="max-width: 150px; height: auto; margin-bottom: 15px; display: block;" alt="GradientMIT Logo">' if include_logo else '<p style="margin-bottom: 15px; font-weight: bold; color: #333;">GradientMIT</p>'
        html_body = f"""
        <html>
          <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{subject}</title>
          </head>
          <body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; line-height: 1.6; background-color: #f5f5f5; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="margin-bottom: 30px;">
                    {body}
                </div>
                
                <div style="margin-top: 30px; border-top: 1px solid #eee; padding-top: 20px;">
                    <p style="margin-bottom: 15px; font-size: 14px;">
                        <a href="https://outlook.office.com/bookwithme/user/f64db056498c433e9493872d4736c509@gradientmit.com?anonymous&ismsaljsauthenabled&ep=plink" target="_blank" style="color: #0078d4; text-decoration: none; font-weight: bold;">📅 Book time to meet with me</a>
                    </p>
                    <p style="margin-bottom: 15px; color: #666; font-size: 14px;">Best regards,</p>
                    {logo_img}
                    <p style="margin: 0; font-size: 14px;">
                        Contact us: <a href="mailto:{sender_email}" style="color: #0078d4; text-decoration: none;">{sender_email}</a>
                    </p>
                    {tracking_pixel}
                </div>
            </div>
          </body>
        </html>
        """
        
        # Add click tracking link if tracking is enabled
        if tracking_id and recipient_hash and not is_bcc_recipient:
            base_url = app.config['PUBLIC_URL']
            click_tracking_url = f"{base_url}/click/{tracking_id}/{recipient_hash}"
            
            # Replace the booking link with tracking link
            html_body = html_body.replace(
                'https://outlook.office.com/bookwithme/user/f64db056498c433e9493872d4736c509@gradientmit.com?anonymous&ismsaljsauthenabled&ep=plink',
                click_tracking_url
            )
        # Attach both plain text and HTML versions
        alt.attach(MIMEText(plain_body, "plain"))
        alt.attach(MIMEText(html_body, "html"))

        # Attach logo only if include_logo is True
        if include_logo and os.path.exists(LOGO_PATH):
            try:
                with open(LOGO_PATH, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-ID", "<company_logo>")
                    img.add_header("Content-Disposition", "inline", filename="logo.png")
                    msg.attach(img)
            except Exception as logo_error:
                print(f"Warning: Could not attach logo: {logo_error}")
        elif include_logo:
            print(f"Warning: Logo not found at: {LOGO_PATH}")

        # Attach files if provided
        if attachments:
            for attachment in attachments:
                if attachment and hasattr(attachment, 'filename') and attachment.filename:
                    try:
                        part = MIMEBase('application', 'octet-stream')
                        attachment.seek(0)  # Reset file pointer to beginning
                        part.set_payload(attachment.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename="{attachment.filename}"'
                        )
                        msg.attach(part)
                        attachment.seek(0)  # Reset file pointer again
                    except Exception as attach_error:
                        print(f"Warning: Could not attach file {attachment.filename}: {attach_error}")

        # Send email
        logging.info(f"Connecting to SMTP server: {smtp_server}:{smtp_port}")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.set_debuglevel(0)  # Set to 1 for debugging
        server.starttls()
        
        # Use basic authentication for all configurations
        logging.info(f"Using basic authentication for: {sender_email}")
        print(f"DEBUG: Authenticating with SMTP as: {sender_email}")
        try:
            server.login(sender_email, sender_password)
            print(f"DEBUG: SMTP authentication successful for: {sender_email}")
        except smtplib.SMTPAuthenticationError as auth_error:
            print(f"DEBUG: SMTP Authentication FAILED for {sender_email}: {auth_error}")
            raise Exception(f"Authentication failed for {sender_email}: {auth_error}")

        # Send to primary recipient and BCC recipients
        recipients = [receiver_email]
        if final_bcc_emails:
            recipients.extend(final_bcc_emails)
        print(f"DEBUG: All recipients (TO + BCC): {recipients}")
        print(f"DEBUG: Sending email FROM: {sender_email} TO: {recipients}")
        try:
            result = server.sendmail(sender_email, recipients, msg.as_string())
            print(f"DEBUG: Email sent successfully from: {sender_email}")
            if result:
                print(f"DEBUG: SMTP send result (should be empty): {result}")
        except Exception as send_error:
            print(f"DEBUG: Email send FAILED: {send_error}")
            raise Exception(f"Failed to send email: {send_error}")
        
        logging.info(f"Successfully sent to {receiver_email}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        error_msg = f"SMTP Authentication failed: {e}. Check email credentials."
        logging.error(error_msg)
        raise Exception(error_msg)
    except smtplib.SMTPRecipientsRefused as e:
        error_msg = f"Recipients refused: {e}"
        logging.error(error_msg)
        raise Exception(error_msg)
    except smtplib.SMTPException as e:
        error_msg = f"SMTP error: {e}"
        logging.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Failed to send email to {receiver_email}: {str(e)}"
        logging.error(error_msg)
        raise Exception(error_msg)
    finally:
        if server:
            try:
                server.quit()
            except:
                pass


# --- Routes ---
def track_user_activity(action, details=""):
    """Track user activity for admin monitoring"""
    try:
        session_id = request.headers.get('X-Session-ID', str(uuid.uuid4()))
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')
        
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Update or create user session
        c.execute('''
            INSERT OR REPLACE INTO user_sessions 
            (session_id, ip_address, user_agent, first_visit, last_activity, page_views, campaigns_sent)
            VALUES (?, ?, ?, 
                COALESCE((SELECT first_visit FROM user_sessions WHERE session_id = ?), ?),
                ?, 
                COALESCE((SELECT page_views FROM user_sessions WHERE session_id = ?), 0) + 1,
                COALESCE((SELECT campaigns_sent FROM user_sessions WHERE session_id = ?), 0)
            )
        ''', (session_id, ip_address, user_agent, session_id, datetime.now(), datetime.now(), session_id, session_id))
        
        # Log activity
        c.execute('''
            INSERT INTO user_activity (session_id, action, details, ip_address)
            VALUES (?, ?, ?, ?)
        ''', (session_id, action, details, ip_address))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error tracking user activity: {e}")





@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        action = request.form.get("action", "login")
        
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        if action == "register":
            # Register new user
            try:
                hashed_password = generate_password_hash(password)
                c.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
                conn.commit()
                flash("Registration successful! Waiting for admin approval.")
            except sqlite3.IntegrityError:
                flash("Username already exists!")
            conn.close()
            return render_template("simple_login.html")
        
        # Login attempt
        c.execute('SELECT password, role, status FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        
        if user:
            stored_password, role, status = user
            # Check if password is hashed or plain text
            if stored_password.startswith('pbkdf2:sha256:') or stored_password.startswith('scrypt:'):
                # Hashed password
                if check_password_hash(stored_password, password):
                    pass  # Valid login
                else:
                    user = None
            else:
                # Plain text password (legacy) - check and update
                if stored_password == password:
                    # Update to hashed password
                    hashed_password = generate_password_hash(password)
                    c.execute('UPDATE users SET password = ? WHERE username = ?', (hashed_password, username))
                    conn.commit()
                else:
                    user = None
        else:
            role = status = None
        if user and role and status:
            if status == 'approved':
                session['logged_in'] = True
                session['username'] = username
                session['role'] = role
                
                # Log successful login
                c.execute('''
                    INSERT INTO user_activity (session_id, action, details, ip_address)
                    VALUES (?, ?, ?, ?)
                ''', (str(uuid.uuid4()), 'login', f'User {username} logged in', request.remote_addr))
                conn.commit()
                
                return redirect(url_for('admin') if role == 'admin' else url_for('index'))
            else:
                flash("Account pending admin approval")
        else:
            flash("Invalid credentials")
        
        conn.close()
    
    return render_template("simple_login.html")

@app.route("/logout")
def logout():
    """Logout route to clear session and redirect to login"""
    try:
        username = session.get('username', 'Unknown')
        
        # Log logout
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO user_activity (session_id, action, details, ip_address)
            VALUES (?, ?, ?, ?)
        ''', (str(uuid.uuid4()), 'logout', f'User {username} logged out', request.remote_addr))
        conn.commit()
        conn.close()
        
        session.clear()
        flash("You have been logged out successfully.")
        return redirect(url_for('login'))
    except Exception as e:
        print(f"Error in logout route: {e}")
        return redirect(url_for('login'))

@app.route("/admin")
def admin():
    """Admin dashboard to monitor user activity and campaigns"""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    track_user_activity("admin_access", "dashboard")
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    

    
    # Debug: Check if bcc_recipients column has data
    c.execute('SELECT COUNT(*) FROM email_logs WHERE bcc_recipients IS NOT NULL')
    bcc_count = c.fetchone()[0]
    print(f"DEBUG: Total emails with BCC data: {bcc_count}")
    
    # Get total campaigns today
    c.execute('''
        SELECT COUNT(*) 
        FROM campaigns 
        WHERE DATE(created_at) = DATE('now')
    ''')
    campaigns_today = c.fetchone()[0]
    
    # Get total emails sent today
    c.execute('''
        SELECT SUM(sent_count) 
        FROM campaigns 
        WHERE DATE(created_at) = DATE('now')
    ''')
    emails_today = c.fetchone()[0] or 0
    
    # Get total email opens today
    c.execute('''
        SELECT COUNT(DISTINCT eo.tracking_id)
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        WHERE DATE(eo.opened_at) = DATE('now')
    ''')
    opens_today = c.fetchone()[0] or 0
    
    # Get overall open rate
    c.execute('SELECT COUNT(*) FROM email_logs WHERE tracking_id IS NOT NULL')
    total_tracked = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(DISTINCT tracking_id) FROM email_opens')
    total_opened = c.fetchone()[0] or 0
    open_rate = round((total_opened / total_tracked * 100) if total_tracked > 0 else 0, 1)
    
    # Get top performing campaigns
    c.execute('''
        SELECT c.name, c.sent_count, COUNT(DISTINCT eo.tracking_id) as opens,
               ROUND(COUNT(DISTINCT eo.tracking_id) * 100.0 / c.sent_count, 1) as open_rate
        FROM campaigns c
        LEFT JOIN email_logs el ON c.id = el.campaign_id
        LEFT JOIN email_opens eo ON el.tracking_id = eo.tracking_id
        WHERE c.sent_count > 0
        GROUP BY c.id
        ORDER BY open_rate DESC LIMIT 5
    ''')
    top_campaigns = c.fetchall()
    
    # Get recent campaigns with details including BCC info
    c.execute('''
        SELECT c.name, c.sent_count, c.failed_count, c.created_at, c.status,
               GROUP_CONCAT(DISTINCT el.bcc_recipients) as bcc_list
        FROM campaigns c
        LEFT JOIN email_logs el ON c.id = el.campaign_id
        GROUP BY c.id
        ORDER BY c.created_at DESC LIMIT 10
    ''')
    recent_campaigns = c.fetchall()
    print(f"DEBUG: Recent campaigns with BCC: {recent_campaigns}")
    
    # Get recent user activity
    c.execute('''
        SELECT ua.action, ua.details, ua.timestamp, ua.ip_address, us.user_agent
        FROM user_activity ua
        JOIN user_sessions us ON ua.session_id = us.session_id
        ORDER BY ua.timestamp DESC LIMIT 20
    ''')
    recent_activity = c.fetchall()
    
    # Get BCC usage statistics
    c.execute('''
        SELECT bcc_recipients, COUNT(*) as usage_count
        FROM email_logs 
        WHERE bcc_recipients IS NOT NULL AND bcc_recipients != '' AND bcc_recipients != 'None'
        GROUP BY bcc_recipients
        ORDER BY usage_count DESC LIMIT 10
    ''')
    bcc_stats = c.fetchall()
    print(f"DEBUG: BCC stats query result: {bcc_stats}")
    
    # Get pending users for approval
    c.execute('SELECT username, created_at FROM users WHERE status = "pending" ORDER BY created_at DESC')
    pending_users = c.fetchall()
    
    # Get all users with their roles and status
    c.execute('SELECT username, role, status, created_at, approved_at FROM users ORDER BY created_at DESC')
    all_users = c.fetchall()
    
    # Get login/logout activity for today
    c.execute('''
        SELECT action, details, timestamp, ip_address
        FROM user_activity
        WHERE action IN ('login', 'logout') AND DATE(timestamp) = DATE('now')
        ORDER BY timestamp DESC LIMIT 10
    ''')
    login_activity = c.fetchall()
    
    conn.close()
    
    return render_template("admin_dashboard.html", 
                         campaigns_today=campaigns_today,
                         emails_today=emails_today,
                         opens_today=opens_today,
                         open_rate=open_rate,
                         total_tracked=total_tracked,
                         total_opened=total_opened,
                         top_campaigns=top_campaigns,
                         recent_campaigns=recent_campaigns,
                         recent_activity=recent_activity,
                         pending_users=pending_users,
                         all_users=all_users,
                         login_activity=login_activity,
                         bcc_stats=bcc_stats)

@app.route("/approve_user/<username>")
def approve_user(username):
    """Approve a pending user"""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    c.execute('UPDATE users SET status = ?, approved_by = ?, approved_at = ? WHERE username = ?', 
              ('approved', session['username'], datetime.now(), username))
    conn.commit()
    conn.close()
    
    flash(f"User '{username}' approved successfully!")
    return redirect(url_for('admin'))

@app.route("/reject_user/<username>")
def reject_user(username):
    """Reject a pending user"""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE username = ? AND status = "pending"', (username,))
    conn.commit()
    conn.close()
    
    flash(f"User '{username}' rejected and removed!")
    return redirect(url_for('admin'))

@app.route("/bulk_approve", methods=["POST"])
def bulk_approve():
    """Bulk approve multiple users"""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    usernames = request.form.getlist('selected_users')
    if not usernames:
        flash("No users selected")
        return redirect(url_for('admin'))
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    for username in usernames:
        c.execute('UPDATE users SET status = ?, approved_by = ?, approved_at = ? WHERE username = ?', 
                  ('approved', session['username'], datetime.now(), username))
    conn.commit()
    conn.close()
    
    flash(f"Approved {len(usernames)} users successfully!")
    return redirect(url_for('admin'))

@app.route("/bulk_reject", methods=["POST"])
def bulk_reject():
    """Bulk reject multiple users"""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    usernames = request.form.getlist('selected_users')
    if not usernames:
        flash("No users selected")
        return redirect(url_for('admin'))
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    for username in usernames:
        c.execute('DELETE FROM users WHERE username = ? AND status = "pending"', (username,))
    conn.commit()
    conn.close()
    
    flash(f"Rejected {len(usernames)} users successfully!")
    return redirect(url_for('admin'))

@app.route("/change_user_role/<username>/<new_role>")
def change_user_role(username, new_role):
    """Change user role (admin/user)"""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    if new_role not in ['admin', 'user']:
        flash("Invalid role")
        return redirect(url_for('admin'))
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    c.execute('UPDATE users SET role = ? WHERE username = ?', (new_role, username))
    conn.commit()
    conn.close()
    
    flash(f"User '{username}' role changed to '{new_role}'")
    return redirect(url_for('admin'))

@app.route("/user_activity_logs")
def user_activity_logs():
    """View detailed user activity logs"""
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    # Get all user activity with pagination
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    
    c.execute('''
        SELECT action, details, timestamp, ip_address
        FROM user_activity
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset))
    activities = c.fetchall()
    
    # Get total count for pagination
    c.execute('SELECT COUNT(*) FROM user_activity')
    total = c.fetchone()[0]
    
    conn.close()
    
    return render_template("user_activity_logs.html", 
                         activities=activities, 
                         page=page, 
                         per_page=per_page, 
                         total=total)

@app.route("/send", methods=["POST"])
def send():
    """Handle email sending from the main form"""
    try:
        mail_type = request.form.get("mail_type")
        mail_sequence = request.form.get("mail_sequence", "first")
        subject = request.form.get("subject")
        body = request.form.get("body")
        bcc_input = request.form.get("bcc", "").strip()
        email_config_key = request.form.get("email_account", "office365")
        print(f"DEBUG: Selected email account: {email_config_key}")
        
        # Validate mail type
        if not mail_type:
            flash("✗ Please select a mail type.")
            return redirect(url_for("index"))
            
        # Validate custom mail fields
        if mail_type == "custom":
            if not subject or not body:
                flash("✗ Subject and body are required for custom mail.")
                return redirect(url_for("index"))
        
        # Process BCC emails - only from user input
        bcc_emails = []
        if bcc_input:
            # Parse comma-separated BCC emails
            bcc_list = [email.strip() for email in bcc_input.split(',') if email.strip()]
            # Validate each BCC email
            for email in bcc_list:
                is_valid, _ = validate_email_deliverability(email)
                if is_valid:
                    bcc_emails.append(email)
                else:
                    logging.warning(f"Invalid BCC email skipped: {email}")
        
        # Get attachments
        attachments = request.files.getlist("attachments")

        file = request.files.get("file")
        if not file or not file.filename:
            flash("✗ Please upload an Excel file.")
            return redirect(url_for("index"))

        # Validate file extension
        if not file.filename.lower().endswith(('.xlsx', '.xls')):
            flash("✗ Please upload a valid Excel file (.xlsx or .xls).")
            return redirect(url_for("index"))

        try:
            df = pd.read_excel(file)
            
            if "Name" not in df.columns or "Email" not in df.columns:
                flash("✗ Excel must have columns: Name, Email")
                return redirect(url_for("index"))
                
            # Remove empty rows
            df = df.dropna(subset=['Name', 'Email'])
            if len(df) == 0:
                flash("✗ No valid email records found in the Excel file.")
                return redirect(url_for("index"))
                
        except Exception as e:
            flash(f"✗ Error reading Excel file: {str(e)}")
            return redirect(url_for("index"))

        # Create campaign record
        sequence_label = "First Mail" if mail_sequence == "first" else "Follow-up Mail"
        campaign_name = f"{sequence_label} - {mail_type.title()} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        total_emails = len(df)
        
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO campaigns (name, status, total_emails, sent_count, failed_count, mail_sequence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (campaign_name, 'running', total_emails, 0, 0, mail_sequence, datetime.now()))
        campaign_id = c.lastrowid
        conn.commit()
        conn.close()

        sent_count = 0
        fail_count = 0
        
        for index, row in df.iterrows():
            name = str(row.get("Name", "")).strip()
            email = str(row.get("Email", "")).strip().lower()

            if not name or not email or name in ['nan', 'None', ''] or email in ['nan', 'None', '']:
                fail_count += 1
                continue

            # Validate email
            is_valid, validation_error = validate_email_deliverability(email)
            if not is_valid:
                fail_count += 1
                continue
            
            # Prepare email content
            if mail_type == "ceo":
                # Get sender name based on selected email account
                config = EMAIL_CONFIGS.get(email_config_key, EMAIL_CONFIGS['office365'])
                sender_email_for_name = config['email']
                if "info@" in sender_email_for_name:
                    sender_name = "GradientM"
                elif "sidharth" in sender_email_for_name:
                    sender_name = "Sidharth Chettry"
                elif "vishwasbs" in sender_email_for_name:
                    sender_name = "Vishwas BS"
                else:
                    sender_name = "GradientMIT Team"
                
                email_subject = "Quick question"
                email_body = f"Hi {name},<br><br>Hope you're doing well.<br><br>I wanted to reach out regarding a potential opportunity that might interest you.<br><br>Would you be available for a brief conversation this week?<br><br>Best regards,<br>{sender_name}"
            elif mail_type == "custom":
                email_subject = subject if subject else "No Subject"
                email_body = body.replace("{name}", name) if body else f"Hi {name},<br><br>Custom message."
            else:
                email_subject = "Default Subject"
                email_body = f"Hi {name},<br><br>This is a default message."

            try:
                # Generate tracking ID for all emails (both first and follow-up)
                tracking_id = str(uuid.uuid4())
                recipient_hash = generate_recipient_hash(email)
                store_recipient_mapping(recipient_hash, email)
                
                # Include logo in all emails
                include_logo = True
                
                send_email(email, email_subject, email_body, attachments, tracking_id, recipient_hash, include_logo, bcc_emails, email_config_key)
                sent_count += 1
                
                # Log successful email
                conn = sqlite3.connect('email_campaigns.db')
                c = conn.cursor()
                bcc_list = ', '.join(bcc_emails) if bcc_emails else ''
                c.execute('''
                    INSERT INTO email_logs (campaign_id, recipient_name, recipient_email, status, sent_at, tracking_id, recipient_hash, bcc_recipients)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (campaign_id, name, email, 'sent', datetime.now(), tracking_id, recipient_hash, bcc_list))
                conn.commit()
                conn.close()
                
                time.sleep(1.0)
                
            except Exception as e:
                fail_count += 1
                print(f"Failed to send to {email}: {e}")

        # Update campaign status and user activity
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        c.execute('''
            UPDATE campaigns 
            SET status = ?, sent_count = ?, failed_count = ?
            WHERE id = ?
        ''', ('completed', sent_count, fail_count, campaign_id))
        
        # Update user campaigns sent count
        session_id = request.headers.get('X-Session-ID', str(uuid.uuid4()))
        c.execute('''
            UPDATE user_sessions 
            SET campaigns_sent = campaigns_sent + 1
            WHERE session_id = ?
        ''', (session_id,))
        
        conn.commit()
        conn.close()
        
        track_user_activity("campaign_sent", f"emails: {sent_count}, failed: {fail_count}")

        # Final status message
        if sent_count > 0 and fail_count == 0:
            flash(f"✓ All {sent_count} emails sent successfully!")
        elif sent_count > 0 and fail_count > 0:
            flash(f"⚠ {sent_count} emails sent, {fail_count} failed.")
        elif sent_count == 0:
            flash(f"✗ No emails were sent. {fail_count} failed.")
        
        return redirect(url_for("index"))
        
    except Exception as e:
        flash(f"✗ An error occurred: {str(e)}")
        return redirect(url_for("index"))

@app.route("/templates")
def template_manager():
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    c.execute('SELECT name, subject, body FROM templates')
    templates = [{'name': row[0], 'subject': row[1], 'body': row[2]} for row in c.fetchall()]
    conn.close()
    return render_template("template_manager.html", templates=templates)

@app.route("/save_template", methods=["POST"])
def save_template():
    name = request.form.get("template_name")
    subject = request.form.get("subject")
    body = request.form.get("body")
    
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO templates (name, subject, body) VALUES (?, ?, ?)', (name, subject, body))
        conn.commit()
        flash(f"Template '{name}' saved successfully!")
    except sqlite3.IntegrityError:
        flash(f"Template '{name}' already exists!")
    conn.close()
    return redirect(url_for('template_manager'))

@app.route("/get_template/<template_name>")
def get_template(template_name):
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    c.execute('SELECT subject, body FROM templates WHERE name = ?', (template_name,))
    result = c.fetchone()
    conn.close()
    if result:
        return jsonify({'subject': result[0], 'body': result[1]})
    return jsonify({'error': 'Template not found'})

@app.route("/debug_email_configs")
def debug_email_configs():
    """Debug route to check email configurations"""
    debug_info = {}
    for key, config in EMAIL_CONFIGS.items():
        debug_info[key] = {
            'email': config.get('email', 'NOT SET'),
            'password_set': bool(config.get('password')),
            'server': config.get('server', 'NOT SET'),
            'port': config.get('port', 'NOT SET')
        }
    return jsonify(debug_info)

@app.route("/get_email_accounts")
def get_email_accounts():
    """Get available email accounts for selection"""
    try:
        accounts = []
        
        # Office365 account
        if EMAIL_CONFIGS['office365']['email'] and EMAIL_CONFIGS['office365']['password']:
            accounts.append({
                'key': 'office365',
                'name': 'Office365 - info@gradientmit.com',
                'email': EMAIL_CONFIGS['office365']['email']
            })
        
        # Gmail account 1
        if EMAIL_CONFIGS['gmail1']['email'] and EMAIL_CONFIGS['gmail1']['password']:
            accounts.append({
                'key': 'gmail1',
                'name': 'Gmail - sidharth.chettry@gradientmservices.com',
                'email': EMAIL_CONFIGS['gmail1']['email']
            })
        
        # Gmail account 2
        if EMAIL_CONFIGS['gmail2']['email'] and EMAIL_CONFIGS['gmail2']['password']:
            accounts.append({
                'key': 'gmail2',
                'name': 'Gmail - vishwasbs@gradientmitsolutions.com',
                'email': EMAIL_CONFIGS['gmail2']['email']
            })
        
        print(f"DEBUG: Returning {len(accounts)} email accounts")
        for acc in accounts:
            print(f"  - {acc['key']}: {acc['email']}")
        
        return jsonify(accounts)
    except Exception as e:
        print(f"ERROR in get_email_accounts: {e}")
        return jsonify([{'key': 'office365', 'name': 'Default Account', 'email': 'info@gradientmit.com'}])

@app.route("/analytics")
def analytics():
    """Main analytics page - redirect to dashboard selector"""
    track_user_activity("page_visit", "analytics")
    return render_template("dashboard_selector.html")

@app.route("/first-mail-dashboard")
def first_mail_dashboard():
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    # Get first mail campaigns with open counts
    c.execute('''
        SELECT c.*, 
               COALESCE(opens_count.opens, 0) as opens, 
               opens_count.latest_open
        FROM campaigns c
        LEFT JOIN (
            SELECT el.campaign_id, COUNT(DISTINCT eo.tracking_id) as opens, MAX(eo.opened_at) as latest_open
            FROM email_logs el
            LEFT JOIN email_opens eo ON el.tracking_id = eo.tracking_id
            GROUP BY el.campaign_id
        ) opens_count ON c.id = opens_count.campaign_id
        WHERE c.mail_sequence = 'first'
        ORDER BY c.created_at DESC LIMIT 50
    ''')
    campaigns = c.fetchall()
    
    # Get first mail statistics
    c.execute('SELECT SUM(sent_count), SUM(failed_count), COUNT(*) FROM campaigns WHERE mail_sequence = "first"')
    stats = c.fetchone()
    total_sent = stats[0] or 0
    total_failed = stats[1] or 0
    total_campaigns = stats[2] or 0
    
    # Get total opens for first mail emails
    c.execute('''
        SELECT COUNT(DISTINCT eo.tracking_id) 
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        WHERE c.mail_sequence = 'first'
    ''')
    total_opens = c.fetchone()[0] or 0
    
    # Get recent first mail logs with open status
    c.execute('''
        SELECT el.recipient_email, el.status, el.sent_at, c.name,
               CASE WHEN eo.tracking_id IS NOT NULL THEN 1 ELSE 0 END as opened
        FROM email_logs el 
        JOIN campaigns c ON el.campaign_id = c.id 
        LEFT JOIN email_opens eo ON el.tracking_id = eo.tracking_id
        WHERE c.mail_sequence = 'first'
        ORDER BY el.sent_at DESC LIMIT 50
    ''')
    recent_emails = c.fetchall()
    
    conn.close()
    
    return render_template("first_mail_analytics.html", 
                         campaigns=campaigns, 
                         total_sent=total_sent,
                         total_failed=total_failed,
                         total_campaigns=total_campaigns,
                         total_opens=total_opens,
                         recent_emails=recent_emails)

@app.route("/followup-mail-dashboard")
def followup_mail_dashboard():
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    # Get follow-up campaigns with open counts
    c.execute('''
        SELECT c.*, 
               COALESCE(opens_count.opens, 0) as opens, 
               opens_count.latest_open
        FROM campaigns c
        LEFT JOIN (
            SELECT el.campaign_id, COUNT(DISTINCT eo.tracking_id) as opens, MAX(eo.opened_at) as latest_open
            FROM email_logs el
            LEFT JOIN email_opens eo ON el.tracking_id = eo.tracking_id
            GROUP BY el.campaign_id
        ) opens_count ON c.id = opens_count.campaign_id
        WHERE c.mail_sequence = 'followup'
        ORDER BY c.created_at DESC LIMIT 50
    ''')
    campaigns = c.fetchall()
    
    # Get follow-up statistics
    c.execute('SELECT SUM(sent_count), SUM(failed_count), COUNT(*) FROM campaigns WHERE mail_sequence = "followup"')
    stats = c.fetchone()
    total_sent = stats[0] or 0
    total_failed = stats[1] or 0
    total_campaigns = stats[2] or 0
    
    # Get total opens for follow-up emails
    c.execute('''
        SELECT COUNT(DISTINCT eo.tracking_id) 
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        WHERE c.mail_sequence = 'followup'
    ''')
    total_opens = c.fetchone()[0] or 0
    
    # Get recent follow-up email logs with open status
    c.execute('''
        SELECT el.recipient_email, el.status, el.sent_at, c.name,
               CASE WHEN eo.tracking_id IS NOT NULL THEN 1 ELSE 0 END as opened
        FROM email_logs el 
        JOIN campaigns c ON el.campaign_id = c.id 
        LEFT JOIN email_opens eo ON el.tracking_id = eo.tracking_id
        WHERE c.mail_sequence = 'followup'
        ORDER BY el.sent_at DESC LIMIT 50
    ''')
    recent_emails = c.fetchall()
    
    conn.close()
    
    return render_template("followup_mail_analytics.html", 
                         campaigns=campaigns, 
                         total_sent=total_sent,
                         total_failed=total_failed,
                         total_campaigns=total_campaigns,
                         total_opens=total_opens,
                         recent_emails=recent_emails)

@app.route("/dashboard")
def dashboard():
    """Display dashboard selector"""
    return render_template("dashboard_selector.html")

@app.route("/dashboard_selector")
def dashboard_selector():
    """Alternative route for dashboard selector"""
    return render_template("dashboard_selector.html")

@app.route("/email_opens")
def email_opens():
    """Display all email opens"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT el.recipient_name, el.recipient_email, c.name as campaign_name,
               eo.opened_at, eo.ip_address, eo.user_agent
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        ORDER BY eo.opened_at DESC
    ''')
    opens = c.fetchall()
    
    conn.close()
    
    return render_template("email_opens.html", opens=opens)

@app.route("/email_clicks")
def email_clicks():
    """Display all email clicks"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT el.recipient_name, el.recipient_email, c.name as campaign_name,
               ec.clicked_at, ec.ip_address, ec.user_agent, ec.original_url
        FROM email_clicks ec
        JOIN email_logs el ON ec.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        ORDER BY ec.clicked_at DESC
    ''')
    clicks = c.fetchall()
    
    conn.close()
    
    return render_template("email_clicks.html", clicks=clicks)

@app.route("/export_opens")
def export_opens():
    """Export email opens to Excel"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT el.recipient_name, el.recipient_email, c.name as campaign_name,
               eo.opened_at, eo.ip_address, eo.user_agent
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        ORDER BY eo.opened_at DESC
    ''')
    opens = c.fetchall()
    conn.close()
    
    df = pd.DataFrame(opens, columns=['Name', 'Email', 'Campaign', 'Opened At', 'IP Address', 'User Agent'])
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Email Opens', index=False)
    output.seek(0)
    
    return send_file(output, as_attachment=True, download_name=f'email_opens_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route("/first_mail_opens")
def first_mail_opens():
    """Display first mail opens only"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT el.recipient_name, el.recipient_email, c.name as campaign_name,
               eo.opened_at, eo.ip_address, eo.user_agent
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        WHERE c.mail_sequence = 'first'
        ORDER BY eo.opened_at DESC
    ''')
    opens = c.fetchall()
    
    conn.close()
    
    return render_template("first_mail_opens.html", opens=opens)

@app.route("/export_first_opens")
def export_first_opens():
    """Export first mail opens to Excel"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT el.recipient_name, el.recipient_email, c.name as campaign_name,
               eo.opened_at, eo.ip_address, eo.user_agent
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        WHERE c.mail_sequence = 'first'
        ORDER BY eo.opened_at DESC
    ''')
    opens = c.fetchall()
    conn.close()
    
    df = pd.DataFrame(opens, columns=['Name', 'Email', 'Campaign', 'Opened At', 'IP Address', 'User Agent'])
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='First Mail Opens', index=False)
    output.seek(0)
    
    return send_file(output, as_attachment=True, download_name=f'first_mail_opens_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route("/followup_mail_opens")
def followup_mail_opens():
    """Display follow-up mail opens only"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT el.recipient_name, el.recipient_email, c.name as campaign_name,
               eo.opened_at, eo.ip_address, eo.user_agent
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        WHERE c.mail_sequence = 'followup'
        ORDER BY eo.opened_at DESC
    ''')
    opens = c.fetchall()
    
    conn.close()
    
    return render_template("followup_mail_opens.html", opens=opens)



@app.route("/export_followup_opens")
def export_followup_opens():
    """Export followup mail opens to Excel"""
    conn = sqlite3.connect('email_campaigns.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT el.recipient_name, el.recipient_email, c.name as campaign_name,
               eo.opened_at, eo.ip_address, eo.user_agent
        FROM email_opens eo
        JOIN email_logs el ON eo.tracking_id = el.tracking_id
        JOIN campaigns c ON el.campaign_id = c.id
        WHERE c.mail_sequence = 'followup'
        ORDER BY eo.opened_at DESC
    ''')
    opens = c.fetchall()
    conn.close()
    
    df = pd.DataFrame(opens, columns=['Name', 'Email', 'Campaign', 'Opened At', 'IP Address', 'User Agent'])
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Followup Mail Opens', index=False)
    output.seek(0)
    
    return send_file(output, as_attachment=True, download_name=f'followup_mail_opens_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route("/track/<tracking_id>")
@app.route("/track/<tracking_id>/<recipient_hash>")
@app.route("/t/<tracking_id>")
@app.route("/t/<tracking_id>/<recipient_hash>")
def track_email_open(tracking_id, recipient_hash=None):
    """Track email opens via 1x1 pixel - only for primary recipients"""
    conn = None
    try:
        # Get real IP address from various headers
        ip_address = (
            request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or
            request.headers.get('X-Real-IP', '') or
            request.headers.get('CF-Connecting-IP', '') or
            request.environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or
            request.remote_addr
        )
        user_agent = request.headers.get('User-Agent', 'Unknown Browser')
        timestamp = datetime.now()
        print(f"\n🚨 ===== EMAIL OPENED ALERT ===== 🚨")
        print(f"📧 Tracking ID: {tracking_id}")
        print(f"🔑 Recipient Hash: {recipient_hash}")
        print(f"🌐 IP Address: {ip_address}")
        print(f"💻 Browser: {user_agent}")
        print(f"⏰ Opened At: {timestamp}")
        print(f"🚨 ================================ 🚨\n")
        
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get the recipient email for this tracking ID
        c.execute('SELECT recipient_email, recipient_name FROM email_logs WHERE tracking_id = ?', (tracking_id,))
        result = c.fetchone()
        
        if not result:
            print(f"DEBUG: ❌ ERROR - No email found for tracking ID: {tracking_id}")
        else:
            recipient_email = result[0]
            recipient_name = result[1] or recipient_email
            
            # Verify recipient hash if provided
            hash_valid = True
            if recipient_hash:
                c.execute('SELECT recipient_email FROM recipient_tracking WHERE recipient_hash = ?', (recipient_hash,))
                hash_result = c.fetchone()
                if not hash_result or hash_result[0] != recipient_email:
                    print(f"DEBUG: ❌ Hash mismatch - Expected: {recipient_email}, Hash maps to: {hash_result[0] if hash_result else 'None'}")
                    hash_valid = False
            
            if hash_valid:
                print(f"DEBUG: Valid tracking request for: {recipient_email} - proceeding with tracking")
                
                # Check for existing opens using both tracking_id and recipient_hash
                if recipient_hash:
                    c.execute('SELECT COUNT(*) FROM email_opens WHERE tracking_id = ? AND recipient_hash = ?', (tracking_id, recipient_hash))
                else:
                    c.execute('SELECT COUNT(*) FROM email_opens WHERE tracking_id = ?', (tracking_id,))
                existing_opens = c.fetchone()[0]
                
                if existing_opens == 0:
                    # This is the first open - record it with recipient hash
                    open_timestamp = datetime.now()
                    
                    c.execute('''
                        INSERT INTO email_opens (tracking_id, recipient_hash, opened_at, ip_address, user_agent)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (tracking_id, recipient_hash, open_timestamp, ip_address, user_agent))
                    
                    conn.commit()
                    
                    # Log to text file
                    log_email_open_to_file(recipient_email, open_timestamp.strftime('%a %b %d %H:%M:%S %Y'))
                    
                    print(f"\n🎉 ===== EMAIL OPEN CONFIRMED ===== 🎉")
                    print(f"✅ FIRST OPEN recorded successfully!")
                    print(f"👤 Recipient: {recipient_email} ({recipient_name})")
                    print(f"📧 Tracking ID: {tracking_id}")
                    print(f"🔑 Hash: {recipient_hash}")
                    print(f"🌐 IP: {ip_address}")
                    print(f"💻 Browser: {user_agent}")
                    print(f"⏰ Time: {open_timestamp}")
                    print(f"🎉 ================================= 🎉\n")
                    
                    # Also print to console for immediate visibility
                    print(f"\n✨ EMAIL OPENED: {recipient_email} at {open_timestamp.strftime('%H:%M:%S')} ✨")
                else:
                    print(f"\n⚠️  EMAIL ALREADY OPENED ⚠️")
                    print(f"👤 Recipient: {recipient_email}")
                    print(f"🔄 Opens: {existing_opens} times")
                    print(f"📧 Tracking ID: {tracking_id}")
                    print(f"⚠️  ==================== ⚠️\n")
                    
                    # Also print repeat open notification
                    print(f"\n🔄 REPEAT OPEN: {recipient_email} (total: {existing_opens + 1}) at {timestamp.strftime('%H:%M:%S')}")
        
        print(f"✅ TRACKING PROCESS COMPLETE at {datetime.now().strftime('%H:%M:%S')}\n")
        
    except Exception as e:
        print(f"\n❌ ===== TRACKING ERROR ===== ❌")
        print(f"🚫 Error: {str(e)}")
        print(f"📧 Tracking ID: {tracking_id}")
        print(f"🔑 Hash: {recipient_hash}")
        import traceback
        print(f"📋 Details: {traceback.format_exc()}")
        print(f"❌ ========================= ❌\n")
    finally:
        if conn:
            conn.close()
    
    # Return 1x1 transparent pixel
    from flask import Response
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x21\xF9\x04\x01\x00\x00\x00\x00\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x04\x01\x00\x3B'
    print(f"🖼️  TRACKING PIXEL ACCESSED for ID: {tracking_id} at {datetime.now()}")
    print(f"👀 USER AGENT: {user_agent}")
    print(f"🌐 IP ADDRESS: {ip_address}")
    response = Response(pixel, mimetype='image/gif')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['ngrok-skip-browser-warning'] = 'true'
    response.headers['ngrok-skip-browser-warning'] = 'any'
    response.headers['User-Agent'] = 'EmailTracker/1.0'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET'
    response.headers['Access-Control-Allow-Headers'] = '*'
    return response

@app.route("/book")
def book_meeting():
    """Show booking options page"""
    return render_template("booking.html")

@app.route("/book-direct")
def book_direct():
    """Direct redirect to Outlook booking - no login required"""
    # No login check - public route
    return redirect('https://outlook.office.com/bookwithme/user/f64db056498c433e9493872d4736c509@gradientmit.com?anonymous&ismsaljsauthenabled&ep=plink')

@app.route("/pixel/<tracking_id>")
@app.route("/pixel/<tracking_id>/<recipient_hash>")
def track_pixel(tracking_id, recipient_hash=None):
    """Alternative pixel tracking endpoint"""
    return track_email_open(tracking_id, recipient_hash)

@app.route("/open/<tracking_id>")
@app.route("/open/<tracking_id>/<recipient_hash>")
def track_open(tracking_id, recipient_hash=None):
    """Alternative open tracking endpoint"""
    return track_email_open(tracking_id, recipient_hash)

@app.route("/click/<tracking_id>/<recipient_hash>")
def track_click_open(tracking_id, recipient_hash):
    """Track email clicks and opens via clickable link and redirect to booking page"""
    try:
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get recipient info
        c.execute('SELECT recipient_email, recipient_name FROM email_logs WHERE tracking_id = ?', (tracking_id,))
        result = c.fetchone()
        
        if result:
            recipient_email = result[0]
            recipient_name = result[1] or recipient_email
            ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
            user_agent = request.headers.get('User-Agent', 'Click Tracker')
            
            # Record the click
            c.execute('''
                INSERT INTO email_clicks (tracking_id, recipient_hash, original_url, clicked_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (tracking_id, recipient_hash, 'https://outlook.office.com/bookwithme/user/f64db056498c433e9493872d4736c509@gradientmit.com?anonymous&ismsaljsauthenabled&ep=plink', datetime.now(), ip_address, user_agent))
            
            # Check if already opened via pixel
            c.execute('SELECT COUNT(*) FROM email_opens WHERE tracking_id = ? AND recipient_hash = ?', (tracking_id, recipient_hash))
            existing_opens = c.fetchone()[0]
            
            if existing_opens == 0:
                # Record the open (first time)
                c.execute('''
                    INSERT INTO email_opens (tracking_id, recipient_hash, opened_at, ip_address, user_agent)
                    VALUES (?, ?, ?, ?, ?)
                ''', (tracking_id, recipient_hash, datetime.now(), ip_address, user_agent))
                
                print(f"\n✨ EMAIL OPENED VIA CLICK: {recipient_email} at {datetime.now().strftime('%H:%M:%S')} ✨")
            
            print(f"\n🖱️ LINK CLICKED: {recipient_email} clicked booking link at {datetime.now().strftime('%H:%M:%S')} 🖱️")
            
            conn.commit()
        
        conn.close()
        
        # Redirect to booking page
        return redirect('/book-direct')
        
    except Exception as e:
        print(f"Click tracking error: {e}")
        # Fallback redirect
        return redirect('/book-direct')

@app.route("/debug_env")
def debug_env():
    """Debug environment variables"""
    return jsonify({
        "smtp_server": SMTP_SERVER,
        "smtp_port": SMTP_PORT,
        "sender_email": SENDER_EMAIL,
        "password_length": len(SENDER_PASSWORD) if SENDER_PASSWORD else 0,
        "password_first_4": SENDER_PASSWORD[:4] if SENDER_PASSWORD else "None",
        "env_file_exists": os.path.exists('.env')
    })

@app.route("/test_email")
def test_email():
    """Test route to verify email functionality"""
    try:
        test_recipient = "info@gradientmit.com"
        test_subject = "Test Email - System Check"
        test_body = "This is a test email to verify the email system is working correctly."
        
        send_email(test_recipient, test_subject, test_body)
        return jsonify({"status": "success", "message": f"Test email sent successfully to {test_recipient}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/check_mx")
def check_mx():
    """Check MX records for the domain"""
    try:
        import dns.resolver
        domain = SENDER_EMAIL.split('@')[1]
        mx_records = dns.resolver.resolve(domain, 'MX')
        mx_list = [str(mx) for mx in mx_records]
        return jsonify({"domain": domain, "mx_records": mx_list})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/check_smtp")
def check_smtp():
    """Check SMTP connection without sending email"""
    configs = [
        {'server': 'smtp-mail.outlook.com', 'port': 587},
        {'server': 'smtp.office365.com', 'port': 587},
        {'server': 'outlook.office365.com', 'port': 587},
        {'server': 'smtp.live.com', 'port': 587},
        {'server': 'gradientmit-com.mail.protection.outlook.com', 'port': 587}
    ]
    
    results = []
    for config in configs:
        try:
            server = smtplib.SMTP(config['server'], config['port'])
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.quit()
            results.append(f"✓ {config['server']}:{config['port']} - SUCCESS")
        except Exception as e:
            results.append(f"✗ {config['server']}:{config['port']} - {str(e)}")
    
    return jsonify({"status": "complete", "results": results})

@app.route("/get_latest_tracking_url")
def get_latest_tracking_url():
    """Get the tracking URL for the most recent email sent"""
    try:
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get the most recent email with tracking
        c.execute('''
            SELECT recipient_email, tracking_id, recipient_hash, sent_at
            FROM email_logs 
            WHERE tracking_id IS NOT NULL 
            ORDER BY sent_at DESC LIMIT 1
        ''')
        result = c.fetchone()
        
        if not result:
            return jsonify({"error": "No tracked emails found"})
        
        email, tracking_id, recipient_hash, sent_at = result
        base_url = get_base_url()
        
        tracking_urls = {
            "test_url": f"{base_url}/test_tracking/{tracking_id}/{recipient_hash}",
            "pixel_url": f"{base_url}/track/{tracking_id}/{recipient_hash}",
            "alt_pixel_url": f"{base_url}/pixel/{tracking_id}/{recipient_hash}",
            "email": email,
            "sent_at": sent_at
        }
        
        conn.close()
        return jsonify(tracking_urls)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/check_opens")
def check_opens():
    """Check email opens in database - API endpoint"""
    try:
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get total emails sent with tracking
        c.execute('SELECT COUNT(*) FROM email_logs WHERE tracking_id IS NOT NULL')
        total_tracked = c.fetchone()[0] or 0
        
        # Get total opens
        c.execute('SELECT COUNT(*) FROM email_opens')
        total_opens = c.fetchone()[0] or 0
        
        # Get recent opens
        c.execute('''
            SELECT el.recipient_email, eo.opened_at, eo.ip_address
            FROM email_opens eo
            JOIN email_logs el ON eo.tracking_id = el.tracking_id
            ORDER BY eo.opened_at DESC LIMIT 5
        ''')
        recent_opens = c.fetchall()
        
        conn.close()
        
        return jsonify({
            "status": "success",
            "total_tracked": total_tracked,
            "total_opens": total_opens,
            "recent_opens": recent_opens,
            "message": f"Tracking: {total_opens}/{total_tracked} emails opened"
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/test_tracking/<tracking_id>/<recipient_hash>")
def test_tracking(tracking_id, recipient_hash):
    """Test tracking URL manually - shows debug info instead of pixel"""
    try:
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get email info
        c.execute('SELECT recipient_email, recipient_name, sent_at FROM email_logs WHERE tracking_id = ?', (tracking_id,))
        email_info = c.fetchone()
        
        if not email_info:
            return f"<h2>❌ Tracking ID not found: {tracking_id}</h2>"
        
        recipient_email, recipient_name, sent_at = email_info
        
        # Check if already opened
        c.execute('SELECT COUNT(*), MAX(opened_at) FROM email_opens WHERE tracking_id = ? AND recipient_hash = ?', (tracking_id, recipient_hash))
        open_info = c.fetchone()
        open_count = open_info[0] or 0
        last_opened = open_info[1]
        
        # Record this test open
        if open_count == 0:
            c.execute('''
                INSERT INTO email_opens (tracking_id, recipient_hash, opened_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
            ''', (tracking_id, recipient_hash, datetime.now(), request.remote_addr, 'TEST-MANUAL-TRACKING'))
            conn.commit()
            status = "✅ FIRST OPEN - Recorded successfully!"
        else:
            status = f"⚠️ Already opened {open_count} times (last: {last_opened})"
        
        conn.close()
        
        return f"""
        <html><body style="font-family: Arial; padding: 20px;">
        <h2>📧 Email Tracking Test</h2>
        <p><strong>Tracking ID:</strong> {tracking_id}</p>
        <p><strong>Recipient Hash:</strong> {recipient_hash}</p>
        <p><strong>Email:</strong> {recipient_email}</p>
        <p><strong>Name:</strong> {recipient_name}</p>
        <p><strong>Sent:</strong> {sent_at}</p>
        <p><strong>Status:</strong> {status}</p>
        <p><strong>Your IP:</strong> {request.remote_addr}</p>
        <hr>
        <p><em>This is a test page. In real emails, this would be an invisible 1x1 pixel.</em></p>
        </body></html>
        """
        
    except Exception as e:
        return f"<h2>❌ Error: {str(e)}</h2>"

@app.route("/test_pixel")
def test_pixel():
    """Test if tracking pixel is accessible"""
    print(f"🖼️  TEST PIXEL ACCESSED from IP: {request.remote_addr}")
    # Return 1x1 transparent pixel
    from flask import Response
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x21\xF9\x04\x01\x00\x00\x00\x00\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x04\x01\x00\x3B'
    response = Response(pixel, mimetype='image/gif')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route("/debug_tracking")
def debug_tracking():
    """Debug tracking system - check recent emails and their tracking status"""
    try:
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get recent emails with tracking info
        c.execute('''
            SELECT el.recipient_email, el.tracking_id, el.recipient_hash, el.sent_at,
                   COUNT(eo.id) as open_count, MAX(eo.opened_at) as last_opened
            FROM email_logs el
            LEFT JOIN email_opens eo ON el.tracking_id = eo.tracking_id
            WHERE el.tracking_id IS NOT NULL
            GROUP BY el.tracking_id
            ORDER BY el.sent_at DESC LIMIT 10
        ''')
        emails = c.fetchall()
        
        base_url = get_base_url()
        
        html = "<html><body style='font-family: Arial; padding: 20px;'>"
        html += "<h2>🔍 Email Tracking Debug</h2>"
        html += f"<p><strong>Base URL:</strong> {base_url}</p>"
        html += "<table border='1' style='border-collapse: collapse; width: 100%;'>"
        html += "<tr><th>Email</th><th>Sent</th><th>Opens</th><th>Last Opened</th><th>Test Links</th></tr>"
        
        for email, tracking_id, recipient_hash, sent_at, open_count, last_opened in emails:
            test_url = f"{base_url}/test_tracking/{tracking_id}/{recipient_hash}"
            pixel_url = f"{base_url}/track/{tracking_id}/{recipient_hash}"
            
            html += f"<tr>"
            html += f"<td>{email}</td>"
            html += f"<td>{sent_at}</td>"
            html += f"<td>{open_count}</td>"
            html += f"<td>{last_opened or 'Never'}</td>"
            html += f"<td><a href='{test_url}' target='_blank'>Test</a> | <a href='{pixel_url}' target='_blank'>Pixel</a></td>"
            html += f"</tr>"
        
        html += "</table>"
        html += "<hr><p><em>Click 'Test' to manually trigger tracking, or 'Pixel' to see the actual tracking pixel.</em></p>"
        html += "</body></html>"
        
        conn.close()
        return html
        
    except Exception as e:
        return f"<h2>❌ Error: {str(e)}</h2>"

@app.route("/force_open/<tracking_id>/<recipient_hash>")
def force_open(tracking_id, recipient_hash):
    """Force record an email open for testing"""
    try:
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get email info
        c.execute('SELECT recipient_email, recipient_name FROM email_logs WHERE tracking_id = ?', (tracking_id,))
        result = c.fetchone()
        
        if not result:
            return f"<h2>❌ Tracking ID not found: {tracking_id}</h2>"
        
        recipient_email, recipient_name = result
        
        # Force record an open
        c.execute('''
            INSERT INTO email_opens (tracking_id, recipient_hash, opened_at, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?)
        ''', (tracking_id, recipient_hash, datetime.now(), request.remote_addr, 'FORCE-TEST-OPEN'))
        
        conn.commit()
        conn.close()
        
        print(f"\n✨ FORCED EMAIL OPEN: {recipient_email} at {datetime.now().strftime('%H:%M:%S')} ✨")
        
        return f"""
        <html><body style="font-family: Arial; padding: 20px;">
        <h2>✅ Email Open Forced Successfully!</h2>
        <p><strong>Email:</strong> {recipient_email}</p>
        <p><strong>Name:</strong> {recipient_name}</p>
        <p><strong>Tracking ID:</strong> {tracking_id}</p>
        <p><strong>Time:</strong> {datetime.now()}</p>
        <hr>
        <p><a href="/debug_tracking">Back to Debug</a> | <a href="/analytics">View Analytics</a></p>
        </body></html>
        """
        
    except Exception as e:
        return f"<h2>❌ Error: {str(e)}</h2>"



@app.route("/test_latest_email")
def test_latest_email():
    """Test the tracking for the most recent email sent"""
    try:
        conn = sqlite3.connect('email_campaigns.db')
        c = conn.cursor()
        
        # Get the most recent email
        c.execute('''
            SELECT recipient_email, tracking_id, recipient_hash, sent_at
            FROM email_logs 
            WHERE tracking_id IS NOT NULL 
            ORDER BY sent_at DESC LIMIT 1
        ''')
        result = c.fetchone()
        
        if not result:
            return "<h2>❌ No tracked emails found</h2>"
        
        email, tracking_id, recipient_hash, sent_at = result
        base_url = get_base_url()
        
        # Check if already opened
        c.execute('SELECT COUNT(*) FROM email_opens WHERE tracking_id = ?', (tracking_id,))
        open_count = c.fetchone()[0]
        
        conn.close()
        
        pixel_url = f"{base_url}/track/{tracking_id}/{recipient_hash}"
        test_url = f"{base_url}/test_tracking/{tracking_id}/{recipient_hash}"
        
        return f"""
        <html><body style="font-family: Arial; padding: 20px;">
        <h2>📧 Latest Email Tracking Test</h2>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Sent:</strong> {sent_at}</p>
        <p><strong>Opens:</strong> {open_count}</p>
        <p><strong>Tracking ID:</strong> {tracking_id}</p>
        <hr>
        <h3>Test Links:</h3>
        <p><a href="{test_url}" target="_blank" class="btn">Manual Test Open</a></p>
        <p><a href="{pixel_url}" target="_blank" class="btn">Direct Pixel URL</a></p>
        <hr>
        <h3>Tracking Pixel Preview:</h3>
        <p>This is what gets added to your emails:</p>
        <div style="border: 1px solid #ccc; padding: 10px; background: #f9f9f9;">
            <code>&lt;img src="{pixel_url}" width="1" height="1"&gt;</code>
        </div>
        <hr>
        <p><strong>Instructions:</strong></p>
        <ol>
            <li>Open the actual email in your email client (Outlook, Gmail, etc.)</li>
            <li>Make sure images are enabled</li>
            <li>The pixel should load automatically when you view the email</li>
            <li>Check the analytics dashboard for the open</li>
        </ol>
        </body></html>
        """
        
    except Exception as e:
        return f"<h2>❌ Error: {str(e)}</h2>"





def log_email_open_to_file(recipient_email, timestamp):
    """Log email open to text file with notification"""
    try:
        log_entry = f"🎉 EMAIL OPENED: {recipient_email} opened the mail at {timestamp}\n"
        with open('email_opens.log', 'a', encoding='utf-8') as f:
            f.write(log_entry)
        print(f"📝 Logged to file: {recipient_email} opened email at {timestamp}")
    except Exception as e:
        print(f"❌ Error writing to log file: {e}")

# --- Run App ---
if __name__ == "__main__":
    try:
        # Debug: Print all registered routes
        print("\n=== REGISTERED ROUTES ===")
        for rule in app.url_map.iter_rules():
            print(f"{rule.endpoint}: {rule.rule}")
        print("========================\n")
        
        # Verify logout route is registered
        logout_routes = [rule for rule in app.url_map.iter_rules() if rule.endpoint == 'logout']
        if logout_routes:
            print(f"SUCCESS: Logout route found: {logout_routes[0].rule}")
        else:
            print("ERROR: Logout route NOT found!")
        
        print(f"\nSUCCESS: Flask app starting at: http://localhost:5001")
        print(f"SUCCESS: External tracking via: https://uncatered-wynter-thoroughgoingly.ngrok-free.dev")
        print(f"SUCCESS: Test latest tracking URL at: http://localhost:5001/get_latest_tracking_url")
        print(f"SUCCESS: Debug tracking system at: http://localhost:5001/debug_tracking")
        print(f"SUCCESS: Test pixel accessibility at: http://localhost:5001/test_pixel")
        print(f"SUCCESS: Force email open test at: http://localhost:5001/debug_tracking")
        print(f"SUCCESS: Test latest email tracking at: http://localhost:5001/test_latest_email\n")
        app.run(debug=True, host="0.0.0.0", port=5001, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\nApp stopped")
    except Exception as e:
        print(f"Error: {e}")