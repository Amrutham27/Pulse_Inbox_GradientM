import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=== ENVIRONMENT VARIABLES ===")
print(f"EMAIL_USER: {os.getenv('EMAIL_USER')}")
print(f"EMAIL_PASSWORD: {'SET' if os.getenv('EMAIL_PASSWORD') else 'NOT SET'}")
print(f"GMAIL_USER_1: {os.getenv('GMAIL_USER_1')}")
print(f"GMAIL_PASS_1: {'SET' if os.getenv('GMAIL_PASS_1') else 'NOT SET'}")
print(f"GMAIL_USER_2: {os.getenv('GMAIL_USER_2')}")
print(f"GMAIL_PASS_2: {'SET' if os.getenv('GMAIL_PASS_2') else 'NOT SET'}")
print("=============================")

# Test email configurations
EMAIL_CONFIGS = {
    'office365': {
        'email': os.getenv('EMAIL_USER', 'info@gradientmit.com'),
        'password': os.getenv('EMAIL_PASSWORD'),
    },
    'gmail1': {
        'email': os.getenv('GMAIL_USER_1'),
        'password': os.getenv('GMAIL_PASS_1'),
    },
    'gmail2': {
        'email': os.getenv('GMAIL_USER_2'),
        'password': os.getenv('GMAIL_PASS_2'),
    }
}

print("\n=== EMAIL CONFIGURATIONS ===")
for key, config in EMAIL_CONFIGS.items():
    email = config.get('email', 'None')
    password = config.get('password')
    password_status = 'SET' if password else 'NOT SET'
    print(f"{key}: {email} - Password: {password_status}")

print("\n=== VALID CONFIGURATIONS ===")
valid_configs = []
for key, config in EMAIL_CONFIGS.items():
    if config.get('email') and config.get('password'):
        valid_configs.append(key)
        print(f"OK {key}: {config['email']}")

print(f"\nTotal valid configurations: {len(valid_configs)}")