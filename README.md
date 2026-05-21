# 📧 Smart Email Sender - Advanced Email Marketing System

A powerful Flask-based email marketing system with dual-mode campaigns, advanced analytics, and comprehensive tracking capabilities.

## ✨ Features

- **Dual Campaign Modes**: First Mail  and Follow-up Mai
- **Bulk Email Campaigns**: Send personalized emails to multiple recipients from Excel files
- **Email Templates**: Save and reuse custom email templates
- **Advanced Analytics**: Separate dashboards for first mail and follow-up campaigns
- **Email Tracking**: Open tracking with 1x1 pixel for follow-up emails
- **Smart Validation**: Real-time email validation with DNS checking
- **Export Functionality**: Export campaign data to Excel with detailed metrics
- **Professional Design**: Modern, responsive interface with gradient backgrounds

## 🚀 Quick Start

### Prerequisites

- Python 3.7+
- pip (Python package installer)

### Installation

1. **Clone or download the project**
   ```bash
   cd auto-mail
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure email settings**
   - Update SMTP settings in `app.py`:
   ```python
   SMTP_SERVER = "smtp.office365.com"
   SMTP_PORT = 587
   SENDER_EMAIL = "your-email@domain.com"
   SENDER_PASSWORD = "brvvmdrjtstvtdbz"
   ```

4. **Run the application**
   ```bash
   python app.py
   ```

5. **Access the application**
   - Open your browser and go to `http://localhost:5000`

## 📋 Usage

### Sending Email Campaigns

1. **Prepare Excel File**
   - Create an Excel file with columns: `Name`, `Email`
   - Example:
     ```
     Name        | Email
     John Doe    | john@example.com
     Jane Smith  | jane@example.com
     ```

2. **Create Campaign**
   - Go to the main dashboard
   - Select mail type (CEO or Custom)
   - Choose mail sequence:
     - **First Mail**: Logo included, no tracking
     - **Follow-up Mail**: Logo + open tracking
   - Upload your Excel file
   - Add attachments if needed
   - Click "Send Emails"

3. **Monitor Progress**
   - View real-time sending progress
   - Check separate dashboards for first mail and follow-up analytics

### Email Templates

1. **Create Template**
   - Go to "Template Manager"
   - Enter template name, subject, and body
   - Use `{name}` placeholder for personalization
   - Save template

2. **Use Template**
   - Select saved template from dropdown
   - Template content will auto-populate

### Analytics Dashboards

#### First Mail Dashboard
- **Campaign Metrics**: Campaign name, total emails, sent, failed, success rate
- **No Tracking**: Clean analytics without open tracking
- **Export Data**: Download first mail analytics as Excel

#### Follow-up Mail Dashboard
- **Enhanced Metrics**: Campaign name, status, total emails, sent, failed, opens
- **Open Tracking**: Monitor email opens with tracking pixels
- **Detailed Analytics**: Track engagement and response rates
- **Export Data**: Download follow-up analytics with open data

## 🔧 Configuration

### Email Settings

Update these settings in `app.py`:

```python
# SMTP Configuration
SMTP_SERVER = "smtp.office365.com"  # Your SMTP server
SMTP_PORT = 587                     # SMTP port
SENDER_EMAIL = "talent.aligner@gradientm.com"
SENDER_PASSWORD = "brvvmdrjtstvtdbz"  # Use app-specific password

# Public URL (for tracking pixels)
app.config['PUBLIC_URL'] = 'http://localhost:5000'
```

### Mail Sequence Configuration

- **First Mail**: Logo included, no tracking pixels
- **Follow-up Mail**: Logo + tracking pixels for open tracking
- Users can select sequence type from the dashboard dropdown

### Logo Setup

1. Place your company logo as `logo.png` in the `static/` folder
2. The logo will automatically appear in emails

## 📊 Features Overview

### Email Campaigns
- **Dual Mode System**: First mail (logo only) vs Follow-up (logo + tracking)
- **Bulk Sending**: Excel import with Name/Email columns
- **Smart Validation**: Email format and DNS validation
- **Personalization**: Use {name} placeholder for custom content
- **Attachment Support**: Multiple file attachments
- **Real-time Progress**: Live sending status and progress bar

### Analytics & Tracking
- **Separate Dashboards**: First mail and follow-up analytics
- **Open Tracking**: 1x1 pixel tracking for follow-up emails only
- **Success Rate Calculation**: Automatic success percentage calculation
- **Export Functionality**: Excel export for both campaign types
- **Clean Interface**: Streamlined tables with essential metrics

### Professional Email Design
- **Company Logo**: Automatic logo inclusion in all emails
- **Meeting Integration**: Built-in Outlook booking links
- **Responsive HTML**: Mobile-friendly email templates
- **Professional Signature**: Branded email signatures

### Template Management
- Save reusable email templates
- Subject and body customization
- Template selection dropdown
- Personalization support

## 🗂️ File Structure

```
auto-mail/
├── app.py                          # Main Flask application
├── requirements.txt                # Python dependencies
├── email_campaigns.db              # SQLite database
├── migrate_db.py                   # Database migration script
├── fix_schema.py                   # Schema fix utility
├── static/
│   └── logo.PNG                    # Company logo
├── templates/
│   ├── index.html                  # Main dashboard
│   ├── dashboard_selector.html     # Analytics selector
│   ├── first_mail_analytics.html   # First mail dashboard
│   ├── followup_mail_analytics.html # Follow-up dashboard
│   ├── template_manager.html       # Template management
│   └── email_opens.html           # Email opens tracking
└── README.md                       # Documentation
```

## 🔒 Security Notes

- Never commit email passwords to version control
- Use app-specific passwords for email accounts
- Keep your SMTP credentials secure
- Regularly update dependencies

## 🐛 Troubleshooting

### Common Issues

1. **SMTP Authentication Failed**
   - Check email credentials
   - Use app-specific password for Gmail/Outlook
   - Verify SMTP server settings

2. **Emails Not Sending**
   - Check internet connection
   - Verify Excel file format (Name, Email columns)
   - Check email address validity

3. **Tracking Not Working**
   - Ensure PUBLIC_URL is correctly set
   - Check if images are blocked in email client
   - Tracking only works for follow-up emails, not first emails

4. **Database Errors**
   - Delete `email_campaigns.db` to reset database
   - Restart the application

## 📈 Performance Tips

- **Campaign Strategy**: Use first mail for initial outreach, follow-up for engagement tracking
- **Batch Processing**: System includes 1-second delays between emails
- **Email Validation**: Built-in DNS and format validation reduces bounces
- **Success Tracking**: Monitor success rates in analytics dashboards
- **Clean Lists**: Regularly export and clean your contact databases

## 🤝 Support

For issues or questions:
1. Check the troubleshooting section
2. Review error messages in the console
3. Ensure all dependencies are installed correctly

## 📝 License

This project is for internal use. Please ensure compliance with email marketing regulations (CAN-SPAM, GDPR) when using this system.

---

**Happy Email Marketing! 📧✨**