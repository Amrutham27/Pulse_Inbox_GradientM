import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime

# Connect to database
conn = sqlite3.connect('email_campaigns.db')
c = conn.cursor()

# Delete existing admin user
c.execute('DELETE FROM users WHERE username = ?', ('admin',))

# Create new admin user with hashed password
admin_password = 'GradientMIT@2024!'
hashed_password = generate_password_hash(admin_password)

c.execute('''
    INSERT INTO users (username, password, role, status, approved_at)
    VALUES (?, ?, ?, ?, ?)
''', ('admin', hashed_password, 'admin', 'approved', datetime.now()))

conn.commit()
conn.close()

print("Admin user reset successfully!")
print("Username: admin")
print("Password: GradientMIT@2024!")