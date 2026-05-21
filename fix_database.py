#!/usr/bin/env python3
"""
Database fix script to add missing original_url column to email_clicks table
"""

import sqlite3
import os

def fix_database():
    """Add missing original_url column to email_clicks table"""
    db_path = 'email_campaigns.db'
    
    if not os.path.exists(db_path):
        print(f"Database file {db_path} not found!")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # Check if original_url column exists
        c.execute("PRAGMA table_info(email_clicks)")
        columns = [column[1] for column in c.fetchall()]
        
        if 'original_url' not in columns:
            print("Adding missing original_url column to email_clicks table...")
            c.execute('ALTER TABLE email_clicks ADD COLUMN original_url TEXT')
            conn.commit()
            print("Successfully added original_url column!")
        else:
            print("original_url column already exists!")
        
        # Verify the fix
        c.execute("PRAGMA table_info(email_clicks)")
        columns = [column[1] for column in c.fetchall()]
        print(f"Current email_clicks columns: {columns}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error fixing database: {e}")
        return False

if __name__ == "__main__":
    print("Fixing database schema...")
    if fix_database():
        print("Database fix completed successfully!")
        print("You can now restart your Flask application.")
    else:
        print("Database fix failed!")