from flask import Flask, request, jsonify, send_file
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import requests
import logging
import time
import re
from datetime import datetime, timedelta
from flask_cors import CORS
import csv
import io
import traceback
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ==============================
# CONFIGURATION
# ==============================
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "SINDBADCRUISE")
WHATSAPP_TOKEN = os.environ.get("ACCESS_TOKEN")
WHATSAPP_PHONE_ID = os.environ.get("PHONE_NUMBER_ID", "797371456799734")
GOOGLE_SHEET_ID = "1GoOO4fae7-3MVJ0QTEY4sGKyTi956zL9X_kaOng_0GE"
SHEET_NAME = "Sindbad Ship Cruises"

# Validate required environment variables
missing_vars = []
if not WHATSAPP_TOKEN:
    missing_vars.append("ACCESS_TOKEN")
if not WHATSAPP_PHONE_ID:
    missing_vars.append("PHONE_NUMBER_ID")
if not os.environ.get("GOOGLE_CREDS_JSON"):
    missing_vars.append("GOOGLE_CREDS_JSON")

if missing_vars:
    logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Google Sheets setup
sheet = None
try:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    
    creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # Open spreadsheet and worksheet
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
        logger.info(f"✅ Found existing worksheet: {SHEET_NAME}")
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"📝 Creating new worksheet: {SHEET_NAME}")
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows="1000", cols="25")
        logger.info(f"✅ Created new worksheet: {SHEET_NAME}")
    
    # Setup headers - Updated for payment tracking
    required_headers = [
        'Timestamp', 'Booking ID', 'Customer Name', 'Phone Number', 'WhatsApp ID',
        'Cruise Date', 'Cruise Time', 'Cruise Type', 'Adults Count', 'Children Count', 
        'Infants Count', 'Total Guests', 'Total Amount', 'Payment Status', 
        'Payment Method', 'Transaction ID', 'Payment Timestamp', 'Language', 
        'Booking Status', 'Notes', 'Payment Receipt URL', 'Payment Currency'
    ]
    
    current_headers = sheet.row_values(1)
    if not current_headers or current_headers != required_headers:
        if current_headers:
            sheet.clear()
        sheet.append_row(required_headers)
        logger.info("✅ Updated Google Sheets headers with payment fields")
    
    # Test connection
    test_value = sheet.acell('A1').value
    logger.info(f"✅ Google Sheets connected successfully. First header: {test_value}")
    
except Exception as e:
    logger.error(f"❌ Google Sheets initialization failed: {str(e)}")
    logger.error(traceback.format_exc())
    raise RuntimeError("Google Sheets initialization failed") from e

# Session management with timeout
user_sessions = {}
SESSION_TIMEOUT_MINUTES = 30

# ==============================
# CRUISE CONFIGURATION
# ==============================
CRUISE_CONFIG = {
    "max_capacity": 135,
    "cruise_types": {
        "morning": {
            "name_en": "Morning Cruise",
            "name_ar": "رحلة الصباح",
            "time": "9:00 AM - 10:30 AM",
            "time_ar": "9:00 صباحاً - 10:30 صباحاً",
            "price_adult": 2.500,
            "price_child": 2.500,
            "price_infant": 0.000
        },
        "afternoon": {
            "name_en": "Afternoon Cruise", 
            "name_ar": "رحلة الظهيرة",
            "time": "1:30 PM - 3:00 PM",
            "time_ar": "1:30 ظهراً - 3:00 عصراً",
            "price_adult": 3.500,
            "price_child": 3.500,
            "price_infant": 0.000
        },
        "sunset": {
            "name_en": "Sunset Cruise",
            "name_ar": "رحلة الغروب", 
            "time": "5:00 PM - 6:30 PM",
            "time_ar": "5:00 عصراً - 6:30 مساءً",
            "price_adult": 4.500,
            "price_child": 4.500,
            "price_infant": 0.000
        },
        "evening": {
            "name_en": "Evening Cruise",
            "name_ar": "رحلة المساء",
            "time": "7:30 PM - 9:00 PM", 
            "time_ar": "7:30 مساءً - 9:00 مساءً",
            "price_adult": 3.500,
            "price_child": 3.500,
            "price_infant": 0.000
        }
    },
    "contact": {
        "phone1": "+968 92734448",
        "phone2": "+968 98178444", 
        "location": "https://maps.app.goo.gl/woyVPSaZDSCG6UrWA",
        "email": "alsindbad.muscat@gmail.com",
        "website": "www.alsindbadmuscat.com"
    },
    "reporting_time": "1 hour before cruise",
    "currency": "OMR"  # Oman Omani Rial
}

# ==============================
# MESSAGES
# ==============================
MESSAGES = {
    "english": {
        "welcome": "🌊 Welcome to Sindbad Ship Cruises!
Choose your preferred language:",
        "main_menu": """🌊 *Sindbad Ship Cruises* 🚢

*Cruise Features:*
• 🛳️ Luxury sea cruise
• ☕ Cafe on board  
• 🌅 Stunning sea views
• 🎵 Music & entertainment

Please choose from the menu:""",
        "booking_start": "📝 *Let's Book Your Cruise!* 🎫
I'll help you book your sea cruise. 🚢
First, please send me your:
👤 *Full Name*
*Example:*
Ahmed Al Harthy",
        "ask_phone": "Perfect, {}! 👋
Now please send me your:
📞 *Phone Number*
*Example:*
91234567",
        "ask_date": "📅 *Cruise Date*
Please send your *preferred date* for the cruise:
📋 *Format Examples:*
• **Tomorrow**
• **October 29**
• **Next Friday**
• **15 November**
• **2024-12-25**",
        "ask_adults": "👥 *Number of Adults*
How many *adults* (12 years and above) will be joining?
Please send the number:
*Examples:* 2, 4, 6",
        "ask_children": "👶 *Number of Children*
Adults: {}
How many *children* (2-11 years) will be joining?
Please send the number:
*Examples:* 0, 1, 2",
        "ask_infants": "🍼 *Number of Infants*
Adults: {}
Children: {}
How many *infants* (below 2 years) will be joining?
*Note:* Infants are free
Please send the number:
*Examples:* 0, 1, 2",
        "ask_cruise_type": "🕒 *Choose Cruise Type*
{} total guests:
• {} adults
• {} children
• {} infants
Please choose your cruise:",
        "payment_request": """💳 *Payment Required*

*Total Amount: {} {}*

To complete your booking, please confirm:

Booking ID: {}

Please choose payment method:""",
        "payment_options": """💳 *Payment Options*

You can pay using:
1. 💳 WhatsApp Pay (Recommended - Instant confirmation)
2. 💵 Bank Transfer
3. 💳 Credit/Debit Card (via secure link)

Please select your preferred method:""",
        "payment_method_selected": "You selected: {}
Please wait while we prepare your payment request...",
        "payment_initiated": """✅ *Payment Initiated!*

You'll receive a payment request via WhatsApp within 30 seconds.
Please check your WhatsApp for the payment request from Sindbad Cruises.

💡 *Note:* If you don't see it, please ensure WhatsApp Pay is enabled on your account.

Your Booking ID: {}

You can also pay manually via:
• Bank Transfer: [Bank Details to be provided by agent]
• Card Payment: [Secure payment link]

We'll notify you once payment is confirmed.""",
        "payment_confirmed": """🎉 *Payment Confirmed!* ✅

Thank you {}! Your cruise has been booked successfully. 🚢

📋 *Booking Details:*
🆔 Booking ID: {}
👤 Name: {}
📞 Phone: {}
📅 Date: {}
🕒 Time: {}
🚢 Cruise Type: {}
👥 Guests: {} total
   • {} adults
   • {} children  
   • {} infants
💰 Amount: {} {}

⏰ *Reporting Time:* 1 hour before cruise
📍 *Location:* {}
📞 *For inquiries:* {} | {}

We wish you a wonderful cruise experience! 🌊""",
        "payment_failed": """❌ *Payment Failed*

We couldn't process your payment. Please try again or contact us directly.

📞 Contact: {} | {}

You can also pay via bank transfer:
Bank: [Bank Name]
Account: [Account Number]
IBAN: [IBAN]

Please send us proof of payment and your Booking ID: {}""",
        "booking_cancelled": "❌ Booking cancelled. We welcome you anytime! 🌊",
        "payment_timeout": "⏰ *Payment Timeout* - Your payment request expired. Please restart booking.",
        "invalid_input": "❌ Invalid input. Please try again.",
        "session_expired": "⏳ Your session has expired. Please start over by sending 'Hi'."
    },
    "arabic": {
        "welcome": "🌊 مرحباً بكم في رحلات السندباد البحرية!
اختر لغتك المفضلة:",
        "main_menu": """🌊 *رحلات السندباد البحرية* 🚢

*مميزات الرحلة:*
• 🛳️ رحلة بحرية فاخرة
• ☕ مقهى على متن السفينة
• 🌅 مناظر بحرية خلابة
• 🎵 موسيقى وترفيه

اختر من القائمة:""",
        "booking_start": "📝 *لنحجز رحلتك!* 🎫
سأساعدك في حجز رحلتك البحرية. 🚢
أولاً، الرجاء إرسال:
👤 *الاسم الكامل*
*مثال:*
أحمد الحارثي",
        "ask_phone": "ممتاز، {}! 👋
الآن الرجاء إرسال:
📞 *رقم الهاتف*
*مثال:*
91234567",
        "ask_date": "📅 *تاريخ الرحلة*
الرجاء إرسال *التاريخ المفضل* للرحلة:
📋 *أمثلة على التنسيق:*
• **غداً**
• **29 أكتوبر**
• **الجمعة القادمة**
• **15 نوفمبر**
• **2024-12-25**",
        "ask_adults": "👥 *عدد البالغين*
كم عدد *البالغين* (12 سنة فما فوق) الذين سينضمون؟
الرجاء إرسال الرقم:
*أمثلة:* 2, 4, 6",
        "ask_children": "👶 *عدد الأطفال*
البالغين: {}
كم عدد *الأطفال* (2-11 سنة) الذين سينضمون؟
الرجاء إرسال الرقم:
*أمثلة:* 0, 1, 2",
        "ask_infants": "🍼 *عدد الرضع*
البالغين: {}
الأطفال: {}
كم عدد *الرضع* (أقل من سنتين) الذين سينضمون؟
*ملاحظة:* الرضع مجاناً
الرجاء إرسال الرقم:
*أمثلة:* 0, 1, 2",
        "ask_cruise_type": "🕒 *اختر نوع الرحلة*
{} ضيوف إجمالاً:
• {} بالغين
• {} أطفال
• {} رضع
الرجاء اختيار الرحلة:",
        "payment_request": """💳 *طلب الدفع*

*المبلغ الإجمالي: {} {}*

لإكمال الحجز، الرجاء التأكيد:

رقم الحجز: {}

الرجاء اختيار طريقة الدفع:""",
        "payment_options": """💳 *خيارات الدفع*

يمكنك الدفع باستخدام:
1. 💳 دفع واتساب (مُوصى به - تأكيد فوري)
2. 💵 التحويل البنكي
3. 💳 بطاقة ائتمان/خصم (عبر رابط آمن)

الرجاء اختيار الطريقة المفضلة:""",
        "payment_method_selected": "لقد اخترت: {}
يرجى الانتظار بينما نجهز طلب الدفع الخاص بك...",
        "payment_initiated": """✅ *تم بدء الدفع!*

ستتلقى طلب دفع عبر واتساب خلال 30 ثانية.
الرجاء التحقق من واتساب الخاص بك لطلب الدفع من رحلات السندباد.

💡 *ملاحظة:* إذا لم تره، تأكد من تفعيل دفع واتساب على حسابك.

رقم حجزك: {}

يمكنك أيضًا الدفع يدويًا عبر:
• التحويل البنكي: [تفاصيل البنك لتُقدّم من قبل الموظف]
• الدفع بالبطاقة: [رابط دفع آمن]

سنُبلغك بمجرد تأكيد الدفع.""",
        "payment_confirmed": """🎉 *تم تأكيد الدفع!* ✅

شكراً {}! تم حجز رحلتك بنجاح. 🚢

📋 *تفاصيل الحجز:*
🆔 رقم الحجز: {}
👤 الاسم: {}
📞 الهاتف: {}
📅 التاريخ: {}
🕒 الوقت: {}
🚢 نوع الرحلة: {}
👥 الضيوف: {} إجمالاً
   • {} بالغين
   • {} أطفال
   • {} رضع
💰 المبلغ: {} {}

⏰ *وقت الحضور:* ساعة قبل الرحلة
📍 *موقعنا:* {}
📞 *للاستفسار:* {} | {}

نتمنى لكم رحلة بحرية ممتعة! 🌊""",
        "payment_failed": """❌ *فشل الدفع*

لم نتمكن من معالجة دفعك. يرجى المحاولة مرة أخرى أو التواصل معنا مباشرة.

📞 للتواصل: {} | {}

يمكنك أيضًا الدفع عبر التحويل البنكي:
البنك: [اسم البنك]
الحساب: [رقم الحساب]
IBAN: [IBAN]

يرجى إرسال إثبات الدفع ورقم حجزك: {}""",
        "booking_cancelled": "❌ تم إلغاء الحجز. نرحب بك في أي وقت! 🌊",
        "payment_timeout": "⏰ *انتهت مدة صلاحية الدفع* - انتهت مدة طلب الدفع الخاص بك. يرجى إعادة بدء الحجز.",
        "invalid_input": "❌ إدخال غير صالح. يرجى المحاولة مرة أخرى.",
        "session_expired": "⏳ انتهت جلستك. يرجى البدء من جديد بإرسال 'مرحبا'."
    }
}

# ==============================
# HELPER FUNCTIONS
# ==============================

def generate_booking_id():
    """Generate unique booking ID with timestamp"""
    return f"SDB{int(time.time())}{uuid.uuid4().hex[:6].upper()}"

def clean_phone_number(number):
    """Clean and validate phone numbers for WhatsApp API"""
    if not number:
        return None
    
    # Remove all non-digit characters
    clean_number = ''.join(filter(str.isdigit, str(number)))
    
    # Handle Oman numbers (968)
    if len(clean_number) == 8 and clean_number.startswith(('9', '7', '8')):
        return '968' + clean_number
    elif len(clean_number) == 9 and clean_number.startswith('9'):
        return '968' + clean_number
    elif len(clean_number) == 12 and clean_number.startswith('968'):
        return clean_number
    elif len(clean_number) == 11 and clean_number.startswith('0968'):
        return '968' + clean_number[1:]
    elif len(clean_number) == 10 and clean_number.startswith('968'):
        return '968' + clean_number[3:]
    
    logger.warning(f"⚠️ Unrecognized phone format: {number}")
    return None

def get_cruise_capacity(date, cruise_type):
    """Get current capacity for a specific cruise"""
    try:
        if not sheet:
            return 0
            
        records = sheet.get_all_records()
        total_guests = 0
        
        for record in records:
            # Ensure we're comparing strings correctly
            record_date = str(record.get('Cruise Date', '')).strip()
            record_cruise = str(record.get('Cruise Type', '')).strip()
            booking_status = str(record.get('Booking Status', '')).strip()
            
            if (record_date == date and 
                record_cruise == cruise_type and
                booking_status.lower() != 'cancelled'):
                total_guests += int(record.get('Total Guests', 0))
        
        return total_guests
    except Exception as e:
        logger.error(f"Error getting capacity: {str(e)}")
        logger.error(traceback.format_exc())
        return 0

def calculate_total_amount(cruise_type, adults, children, infants):
    """Calculate total amount for booking"""
    config = CRUISE_CONFIG["cruise_types"][cruise_type]
    total = (adults * config["price_adult"]) + (children * config["price_child"])
    return round(total, 3)

def send_whatsapp_message(to, message, interactive_data=None, media=None):
    """Send WhatsApp message via Meta API with retry logic"""
    try:
        clean_to = clean_phone_number(to)
        if not clean_to:
            logger.error(f"❌ Invalid phone number: {to}")
            return False
        
        url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_to
        }
        
        if media:
            payload.update({
                "type": "image",
                "image": media
            })
        elif interactive_data:
            payload.update({
                "type": "interactive",
                "interactive": interactive_data
            })
        else:
            payload.update({
                "type": "text",
                "text": {"body": message}
            })

        logger.info(f"📤 Sending message to {clean_to} | Type: {payload.get('type')}")

        # Retry logic for network issues
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                response_data = response.json()
                
                if response.status_code == 200:
                    logger.info(f"✅ Message sent to {clean_to} (Attempt {attempt + 1})")
                    return True
                else:
                    error_msg = response_data.get('error', {}).get('message', 'Unknown error')
                    error_code = response_data.get('error', {}).get('code', 'Unknown')
                    logger.error(f"❌ WhatsApp API error (Attempt {attempt + 1}): {error_code} - {error_msg}")
                    
                    if response.status_code == 429:  # Rate limited
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)
                        continue
                    else:
                        break
                        
            except requests.exceptions.Timeout:
                logger.warning(f"⏰ Timeout on attempt {attempt + 1} for {clean_to}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return False
            except Exception as e:
                logger.error(f"🚨 Unexpected error sending message: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return False
        
        return False
        
    except Exception as e:
        logger.error(f"🚨 Failed to send message: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def save_booking_to_sheets(booking_data, language, payment_status="Pending", payment_method="Not Selected", transaction_id="N/A", payment_timestamp="", receipt_url="", currency="OMR"):
    """Save booking to Google Sheets with comprehensive fields"""
    try:
        if not sheet:
            logger.error("❌ Google Sheets not available")
            return False
            
        timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
        
        row_data = [
            timestamp,
            booking_data['booking_id'],
            booking_data['name'],
            booking_data['phone'],
            booking_data['whatsapp_id'],
            booking_data['cruise_date'],
            cruise_info['time'],
            cruise_info['name_en'],
            booking_data['adults_count'],
            booking_data['children_count'], 
            booking_data['infants_count'],
            booking_data['total_guests'],
            booking_data['total_amount'],
            payment_status,
            payment_method,
            transaction_id,
            payment_timestamp,
            language.title(),
            'Confirmed',
            'Via WhatsApp Bot',
            receipt_url,
            currency
        ]
        
        logger.info(f"💾 Saving to sheets: {booking_data['booking_id']}")
        sheet.append_row(row_data)
        logger.info(f"✅ Booking saved: {booking_data['booking_id']}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to save booking: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def update_payment_in_sheets(booking_id, payment_status, payment_method, transaction_id, payment_timestamp, receipt_url):
    """Update payment details in existing booking record"""
    try:
        if not sheet:
            logger.error("❌ Google Sheets not available")
            return False
        
        # Get all records
        records = sheet.get_all_records()
        
        # Find the row with matching booking_id
        for i, record in enumerate(records, start=2):  # Start at 2 because row 1 is headers
            if str(record.get('Booking ID', '')).strip() == str(booking_id).strip():
                # Update the specific row
                cell_range = f"O{i}:U{i}"  # Payment Status to Receipt URL
                values = [
                    payment_status,
                    payment_method,
                    transaction_id,
                    payment_timestamp,
                    receipt_url
                ]
                
                sheet.update(f"O{i}", [values])
                logger.info(f"✅ Updated payment for booking {booking_id}: {payment_status}")
                return True
        
        logger.warning(f"⚠️ Booking ID {booking_id} not found for payment update")
        return False
        
    except Exception as e:
        logger.error(f"❌ Failed to update payment in sheets: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def initiate_whatsapp_payment(phone_number, booking_id, amount, currency="OMR"):
    """
    Initiate WhatsApp Business Payment request
    Note: WhatsApp Payments API requires business verification and is only available in supported countries.
    This implementation follows the documented API structure.
    """
    try:
        clean_to = clean_phone_number(phone_number)
        if not clean_to:
            return False, "Invalid phone number"
        
        # WhatsApp Payments API endpoint
        url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/payments"
        
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Generate unique payment request ID
        payment_request_id = f"PR_{booking_id}_{int(time.time())}"
        
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_to,
            "type": "payment",
            "payment": {
                "currency": currency,
                "amount": int(amount * 1000),  # Convert to smallest unit (e.g., OMR 2.500 → 2500)
                "request_id": payment_request_id,
                "note": f"Booking ID: {booking_id} - Sindbad Ship Cruise",
                "label": "Pay for Cruise Booking"
            }
        }
        
        logger.info(f"🔄 Initiating WhatsApp payment for {clean_to} | Amount: {amount} {currency} | Request ID: {payment_request_id}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200:
            logger.info(f"✅ WhatsApp payment initiated successfully for {clean_to}")
            return True, payment_request_id
        else:
            error_msg = response_data.get('error', {}).get('message', 'Unknown error')
            error_code = response_data.get('error', {}).get('code', 'Unknown')
            logger.error(f"❌ WhatsApp payment initiation failed: {error_code} - {error_msg}")
            return False, error_msg
            
    except Exception as e:
        logger.error(f"🚨 Failed to initiate WhatsApp payment: {str(e)}")
        logger.error(traceback.format_exc())
        return False, str(e)

def check_payment_status(payment_request_id):
    """
    Check payment status (for webhook handling)
    This function would be called by a webhook endpoint when WhatsApp sends payment status updates
    """
    # Note: WhatsApp Payments API doesn't have a direct status check endpoint.
    # Instead, we rely on the payment_status webhook callback.
    # This function is kept for future implementation if Meta provides a direct API.
    return None

def cleanup_expired_sessions():
    """Remove sessions older than SESSION_TIMEOUT_MINUTES"""
    now = datetime.now()
    expired_sessions = []
    
    for phone, session in user_sessions.items():
        created_at = datetime.fromisoformat(session['created_at'])
        if (now - created_at).total_seconds() > (SESSION_TIMEOUT_MINUTES * 60):
            expired_sessions.append(phone)
            logger.info(f"⏳ Cleaning up expired session for {phone}")
    
    for phone in expired_sessions:
        del user_sessions[phone]

# ==============================
# FLOW MANAGEMENT
# ==============================

def send_language_menu(to):
    """Send language selection menu"""
    interactive_data = {
        "type": "list",
        "header": {"type": "text", "text": "🌊 Sindbad Cruises"},
        "body": {"text": MESSAGES["english"]["welcome"]},
        "action": {
            "button": "🌐 Select Language",
            "sections": [{
                "title": "Language",
                "rows": [
                    {"id": "lang_english", "title": "🇺🇸 English", "description": "Continue in English"},
                    {"id": "lang_arabic", "title": "🇴🇲 العربية", "description": "المتابعة باللغة العربية"}
                ]
            }]
        }
    }
    return send_whatsapp_message(to, "", interactive_data)

def send_main_menu(to, language):
    """Send main menu"""
    contact = CRUISE_CONFIG["contact"]
    
    if language == "arabic":
        message = MESSAGES["arabic"]["main_menu"]
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "🌊 رحلات السندباد"},
            "body": {"text": "اختر من الخيارات:"},
            "action": {
                "button": "عرض الخيارات",
                "sections": [{
                    "title": "الخدمات",
                    "rows": [
                        {"id": "book_cruise", "title": "📅 حجز رحلة", "description": "احجز رحلتك البحرية"},
                        {"id": "pricing", "title": "💰 الأسعار", "description": "أسعار الرحلات"},
                        {"id": "schedule", "title": "🕒 الجدول", "description": "مواعيد الرحلات"},
                        {"id": "contact", "title": "📞 اتصل بنا", "description": "معلومات الاتصال"}
                    ]
                }]
            }
        }
    else:
        message = MESSAGES["english"]["main_menu"]
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "🌊 Sindbad Cruises"},
            "body": {"text": "Choose from options:"},
            "action": {
                "button": "View Options",
                "sections": [{
                    "title": "Services",
                    "rows": [
                        {"id": "book_cruise", "title": "📅 Book Cruise", "description": "Book your sea cruise"},
                        {"id": "pricing", "title": "💰 Pricing", "description": "Cruise prices"},
                        {"id": "schedule", "title": "🕒 Schedule", "description": "Cruise timings"},
                        {"id": "contact", "title": "📞 Contact Us", "description": "Contact information"}
                    ]
                }]
            }
        }
    
    return send_whatsapp_message(to, message, interactive_data)

def start_booking(to, language):
    """Start booking flow"""
    user_sessions[to] = {
        'language': language,
        'step': 'awaiting_name',
        'created_at': datetime.now().isoformat()
    }
    message = MESSAGES[language]["booking_start"]
    return send_whatsapp_message(to, message)

def handle_booking_step(to, text, language, session):
    """Handle booking flow steps with validation"""
    step = session.get('step')
    
    if step == 'awaiting_name':
        if not text.strip():
            return send_whatsapp_message(to, MESSAGES[language]["invalid_input"])
        
        session.update({'step': 'awaiting_phone', 'name': text.strip()})
        message = MESSAGES[language]["ask_phone"].format(text.strip())
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_phone':
        if not text.strip():
            return send_whatsapp_message(to, MESSAGES[language]["invalid_input"])
        
        # Validate phone number format
        clean_phone = clean_phone_number(text)
        if not clean_phone:
            return send_whatsapp_message(to, "❌ Please enter a valid Omani phone number (e.g., 91234567)")
        
        session.update({'step': 'awaiting_date', 'phone': text.strip(), 'whatsapp_id': clean_phone})
        message = MESSAGES[language]["ask_date"]
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_date':
        if not text.strip():
            return send_whatsapp_message(to, MESSAGES[language]["invalid_input"])
        
        # Basic date validation - allow any text for now (handled by user)
        session.update({'step': 'awaiting_adults', 'cruise_date': text.strip()})
        message = MESSAGES[language]["ask_adults"]
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_adults':
        if not text.strip().isdigit() or int(text.strip()) <= 0:
            return send_whatsapp_message(to, "❌ Please enter a valid number of adults (1 or more)")
        
        session.update({'step': 'awaiting_children', 'adults_count': int(text.strip())})
        message = MESSAGES[language]["ask_children"].format(text.strip())
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_children':
        if not text.strip().isdigit() or int(text.strip()) < 0:
            return send_whatsapp_message(to, "❌ Please enter a valid number of children (0 or more)")
        
        session.update({'step': 'awaiting_infants', 'children_count': int(text.strip())})
        message = MESSAGES[language]["ask_infants"].format(
            session['adults_count'], text.strip()
        )
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_infants':
        if not text.strip().isdigit() or int(text.strip()) < 0:
            return send_whatsapp_message(to, "❌ Please enter a valid number of infants (0 or more)")
        
        session.update({'infants_count': int(text.strip())})
        return send_cruise_type_menu(to, language, session)
    
    return False

def send_cruise_type_menu(to, language, session):
    """Send cruise type selection menu with capacity check"""
    adults = session['adults_count']
    children = session['children_count']
    infants = session['infants_count']
    total_guests = adults + children + infants
    date = session['cruise_date']
    
    # Check capacity for each cruise type
    available_cruises = []
    for cruise_key, cruise_info in CRUISE_CONFIG["cruise_types"].items():
        current_capacity = get_cruise_capacity(date, cruise_info["name_en"])
        available_seats = CRUISE_CONFIG["max_capacity"] - current_capacity
        
        if available_seats >= total_guests:
            available_cruises.append((cruise_key, cruise_info, available_seats))
    
    if not available_cruises:
        message = f"❌ Sorry, no available seats on {date}.
Please choose another date."
        send_whatsapp_message(to, message)
        # Restart booking flow
        start_booking(to, language)
        return False
    
    if language == "arabic":
        body_text = MESSAGES["arabic"]["ask_cruise_type"].format(
            total_guests, adults, children, infants
        )
        rows = []
        for cruise_key, cruise_info, available_seats in available_cruises:
            rows.append({
                "id": f"cruise_{cruise_key}",
                "title": f"🕒 {cruise_info['name_ar']}",
                "description": f"{cruise_info['time_ar']} - {available_seats} مقاعد"
            })
        
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "اختر الرحلة"},
            "body": {"text": body_text},
            "action": {
                "button": "اختر الرحلة",
                "sections": [{"title": "الرحلات", "rows": rows}]
            }
        }
    else:
        body_text = MESSAGES["english"]["ask_cruise_type"].format(
            total_guests, adults, children, infants
        )
        rows = []
        for cruise_key, cruise_info, available_seats in available_cruises:
            rows.append({
                "id": f"cruise_{cruise_key}",
                "title": f"🕒 {cruise_info['name_en']}",
                "description": f"{cruise_info['time']} - {available_seats} seats"
            })
        
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "Choose Cruise"},
            "body": {"text": body_text},
            "action": {
                "button": "Select Cruise",
                "sections": [{"title": "Cruises", "rows": rows}]
            }
        }
    
    session['step'] = 'awaiting_cruise_type'
    return send_whatsapp_message(to, "", interactive_data)

def send_payment_options_menu(to, session):
    """Send payment method selection menu"""
    language = session['language']
    total_amount = calculate_total_amount(
        session['cruise_type'],
        session['adults_count'],
        session['children_count'],
        session['infants_count']
    )
    currency = CRUISE_CONFIG["currency"]
    
    if language == "arabic":
        message = MESSAGES["arabic"]["payment_options"]
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "💳 خيارات الدفع"},
            "body": {"text": message},
            "action": {
                "button": "اختر طريقة الدفع",
                "sections": [{
                    "title": "طرق الدفع",
                    "rows": [
                        {"id": "payment_whatsapp", "title": "💳 دفع واتساب", "description": "دفع فوري عبر واتساب"},
                        {"id": "payment_bank", "title": "💵 التحويل البنكي", "description": "تحويل بنكي يدوي"},
                        {"id": "payment_card", "title": "💳 بطاقة ائتمان", "description": "دفع عبر رابط آمن"}
                    ]
                }]
            }
        }
    else:
        message = MESSAGES["english"]["payment_options"]
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "💳 Payment Options"},
            "body": {"text": message},
            "action": {
                "button": "Select Payment Method",
                "sections": [{
                    "title": "Payment Methods",
                    "rows": [
                        {"id": "payment_whatsapp", "title": "💳 WhatsApp Pay", "description": "Instant payment via WhatsApp"},
                        {"id": "payment_bank", "title": "💵 Bank Transfer", "description": "Manual bank transfer"},
                        {"id": "payment_card", "title": "💳 Credit Card", "description": "Secure card payment link"}
                    ]
                }]
            }
        }
    
    session['step'] = 'awaiting_payment_method'
    return send_whatsapp_message(to, "", interactive_data)

def request_payment(to, session):
    """Request payment confirmation with WhatsApp Pay option"""
    language = session['language']
    cruise_type = session['cruise_type']
    cruise_info = CRUISE_CONFIG["cruise_types"][cruise_type]
    
    total_amount = calculate_total_amount(
        cruise_type,
        session['adults_count'],
        session['children_count'],
        session['infants_count']
    )
    
    booking_id = generate_booking_id()
    
    # Prepare booking data
    booking_data = {
        'booking_id': booking_id,
        'name': session['name'],
        'phone': session['phone'],
        'whatsapp_id': to,
        'cruise_date': session['cruise_date'],
        'cruise_type': cruise_type,
        'adults_count': session['adults_count'],
        'children_count': session['children_count'],
        'infants_count': session['infants_count'],
        'total_guests': session['adults_count'] + session['children_count'] + session['infants_count'],
        'total_amount': total_amount,
        'currency': CRUISE_CONFIG["currency"]
    }
    
    session['booking_data'] = booking_data
    session['step'] = 'awaiting_payment_method'
    
    # Send payment options menu instead of direct payment request
    return send_payment_options_menu(to, session)

def initiate_payment_via_whatsapp(to, session):
    """Initiate WhatsApp Pay payment"""
    language = session['language']
    booking_data = session['booking_data']
    amount = booking_data['total_amount']
    currency = booking_data['currency']
    booking_id = booking_data['booking_id']
    
    success, result = initiate_whatsapp_payment(to, booking_id, amount, currency)
    
    if success:
        # Save pending payment record
        save_booking_to_sheets(
            booking_data, 
            language, 
            payment_status="Pending (WhatsApp Pay)",
            payment_method="WhatsApp Pay",
            transaction_id=result,
            payment_timestamp=datetime.now().strftime("%Y-%m-%d %I:%M %p")
        )
        
        message = MESSAGES[language]["payment_initiated"].format(booking_id)
        send_whatsapp_message(to, message)
        
        # Set step to wait for payment confirmation
        session['step'] = 'awaiting_payment_confirmation'
        session['payment_request_id'] = result
        session['payment_initiated_at'] = datetime.now().isoformat()
        
        logger.info(f"✅ WhatsApp payment initiated for {to} | Request ID: {result}")
        
    else:
        # Fallback to manual payment options
        message = MESSAGES[language]["payment_failed"].format(
            CRUISE_CONFIG["contact"]["phone1"], 
            CRUISE_CONFIG["contact"]["phone2"], 
            booking_id
        )
        send_whatsapp_message(to, message)
        send_main_menu(to, language)

def handle_payment_method_selection(to, selection, session):
    """Handle payment method selection"""
    language = session['language']
    booking_data = session['booking_data']
    amount = booking_data['total_amount']
    currency = booking_data['currency']
    booking_id = booking_data['booking_id']
    
    if selection == "payment_whatsapp":
        message = MESSAGES[language]["payment_method_selected"].format("WhatsApp Pay")
        send_whatsapp_message(to, message)
        
        # Initiate WhatsApp Pay
        initiate_payment_via_whatsapp(to, session)
        
    elif selection == "payment_bank":
        message = MESSAGES[language]["payment_method_selected"].format("Bank Transfer")
        send_whatsapp_message(to, message)
        
        # Save booking with bank transfer status
        save_booking_to_sheets(
            booking_data, 
            language, 
            payment_status="Pending (Bank Transfer)",
            payment_method="Bank Transfer",
            transaction_id="Manual"
        )
        
        # Provide bank details
        if language == "arabic":
            bank_message = f"""🏦 *تفاصيل التحويل البنكي*

لإتمام الدفع، يرجى التحويل إلى:
- البنك: [اسم البنك]
- الحساب: [رقم الحساب]
- IBAN: [رقم IBAN]

بعد التحويل، أرسل إثبات الدفع مع رقم الحجز: {booking_id}

ملاحظة: سيتم تأكيد الحجز بعد التحقق من التحويل (قد يستغرق حتى 24 ساعة)."""
        else:
            bank_message = f"""🏦 *Bank Transfer Details*

To complete payment, please transfer to:
- Bank: [Bank Name]
- Account: [Account Number]
- IBAN: [IBAN]

After transfer, send proof of payment with your Booking ID: {booking_id}

Note: Booking will be confirmed after verification (may take up to 24 hours)."""
        
        send_whatsapp_message(to, bank_message)
        send_main_menu(to, language)
        
        # Clear session
        if to in user_sessions:
            del user_sessions[to]
            
    elif selection == "payment_card":
        message = MESSAGES[language]["payment_method_selected"].format("Credit Card")
        send_whatsapp_message(to, message)
        
        # Save booking with card payment status
        save_booking_to_sheets(
            booking_data, 
            language, 
            payment_status="Pending (Card)",
            payment_method="Credit Card",
            transaction_id="Link Generated"
        )
        
        # Provide secure payment link (you'll need to implement this)
        if language == "arabic":
            card_message = f"""💳 *رابط الدفع الآمن*

لإتمام الدفع، يرجى النقر على الرابط أدناه واتباع التعليمات:

[رابط الدفع الآمن - سيتم توليد تلقائيًا عند التفعيل]

بعد الدفع، سيتم تأكيد حجزك تلقائيًا.

رقم الحجز: {booking_id}"""
        else:
            card_message = f"""💳 *Secure Payment Link*

To complete payment, click the link below and follow instructions:

[Secure Payment Link - will be generated upon activation]

After payment, your booking will be automatically confirmed.

Booking ID: {booking_id}"""
        
        send_whatsapp_message(to, card_message)
        send_main_menu(to, language)
        
        # Clear session
        if to in user_sessions:
            del user_sessions[to]
    else:
        send_whatsapp_message(to, MESSAGES[language]["invalid_input"])

def confirm_booking(to, session):
    """Confirm and save booking after payment is confirmed"""
    language = session['language']
    booking_data = session['booking_data']
    contact = CRUISE_CONFIG["contact"]
    cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
    
    # Update payment status to confirmed
    update_payment_in_sheets(
        booking_data['booking_id'],
        "Confirmed",
        session.get('payment_method', 'Unknown'),
        session.get('transaction_id', 'N/A'),
        datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        ""  # Receipt URL - can be populated later if needed
    )
    
    # Send confirmation message
    if language == "arabic":
        message = MESSAGES["arabic"]["payment_confirmed"].format(
            booking_data['name'],
            booking_data['booking_id'],
            booking_data['name'],
            booking_data['phone'],
            booking_data['cruise_date'],
            cruise_info['time_ar'],
            cruise_info['name_ar'],
            booking_data['total_guests'],
            booking_data['adults_count'],
            booking_data['children_count'],
            booking_data['infants_count'],
            booking_data['total_amount'],
            CRUISE_CONFIG["currency"],
            contact['location'],
            contact['phone1'],
            contact['phone2']
        )
    else:
        message = MESSAGES["english"]["payment_confirmed"].format(
            booking_data['name'],
            booking_data['booking_id'],
            booking_data['name'],
            booking_data['phone'],
            booking_data['cruise_date'],
            cruise_info['time'],
            cruise_info['name_en'],
            booking_data['total_guests'],
            booking_data['adults_count'],
            booking_data['children_count'],
            booking_data['infants_count'],
            booking_data['total_amount'],
            CRUISE_CONFIG["currency"],
            contact['location'],
            contact['phone1'],
            contact['phone2']
        )
    
    # Clear session
    if to in user_sessions:
        del user_sessions[to]
    
    return send_whatsapp_message(to, message)

def cancel_booking(to, language):
    """Cancel booking"""
    if to in user_sessions:
        del user_sessions[to]
    
    message = MESSAGES[language]["booking_cancelled"]
    return send_whatsapp_message(to, message)

def handle_payment_status_update(payment_request_id, status):
    """
    Handle payment status updates from WhatsApp webhook
    This function is called when WhatsApp sends a payment status update
    """
    logger.info(f"🔔 Payment status update: {payment_request_id} -> {status}")
    
    # Find session by payment_request_id
    for phone, session in user_sessions.items():
        if session.get('payment_request_id') == payment_request_id:
            if status == "completed":
                # Payment confirmed
                session['payment_method'] = "WhatsApp Pay"
                session['transaction_id'] = payment_request_id
                session['payment_status'] = "completed"
                session['payment_confirmed_at'] = datetime.now().isoformat()
                
                # Confirm booking
                confirm_booking(phone, session)
                return True
            elif status == "failed":
                # Payment failed
                message = MESSAGES[session['language']]["payment_failed"].format(
                    CRUISE_CONFIG["contact"]["phone1"], 
                    CRUISE_CONFIG["contact"]["phone2"], 
                    session['booking_data']['booking_id']
                )
                send_whatsapp_message(phone, message)
                
                # Update sheet
                update_payment_in_sheets(
                    session['booking_data']['booking_id'],
                    "Failed",
                    "WhatsApp Pay",
                    payment_request_id,
                    datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                    ""
                )
                
                # Clear session
                del user_sessions[phone]
                return True
            elif status == "expired":
                # Payment expired
                message = MESSAGES[session['language']]["payment_timeout"]
                send_whatsapp_message(phone, message)
                
                # Update sheet
                update_payment_in_sheets(
                    session['booking_data']['booking_id'],
                    "Expired",
                    "WhatsApp Pay",
                    payment_request_id,
                    datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                    ""
                )
                
                # Clear session
                del user_sessions[phone]
                return True
    
    logger.warning(f"⚠️ Payment status update for unknown request ID: {payment_request_id}")
    return False

# ==============================
# WEBHOOK HANDLERS
# ==============================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Webhook verification"""
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if token == VERIFY_TOKEN:
        logger.info("✅ Webhook verified")
        return challenge
    else:
        logger.warning("❌ Webhook verification failed")
        return "Verification token mismatch", 403

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Handle incoming WhatsApp messages and payment status updates"""
    try:
        data = request.get_json()
        logger.info(f"📨 Incoming webhook: {json.dumps(data, indent=2)}")
        
        # Handle payment status updates (Webhook from WhatsApp Payments)
        if data.get("object") == "business_management" and data.get("entry"):
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    if change.get("field") == "payments":
                        payment_updates = change.get("value", {}).get("payment_updates", [])
                        for update in payment_updates:
                            payment_request_id = update.get("request_id")
                            status = update.get("status")
                            logger.info(f"🔔 Payment status update: {payment_request_id} -> {status}")
                            handle_payment_status_update(payment_request_id, status)
                        return jsonify({"status": "payment_status_handled"})
        
        # Handle standard WhatsApp messages
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            return jsonify({"status": "no_message"})
        
        message = messages[0]
        phone_number = message["from"]
        
        # Handle interactive messages
        if "interactive" in message:
            interactive = message["interactive"]
            
            if interactive["type"] == "list_reply":
                option_id = interactive["list_reply"]["id"]
                logger.info(f"📋 List selection: {option_id} from {phone_number}")
                handle_interactive_message(phone_number, option_id)
                
            elif interactive["type"] == "button_reply":
                button_id = interactive["button_reply"]["id"]
                logger.info(f"🔘 Button click: {button_id} from {phone_number}")
                handle_interactive_message(phone_number, button_id)
            
            return jsonify({"status": "interactive_handled"})
        
        # Handle text messages
        if "text" in message:
            text = message["text"]["body"].strip()
            logger.info(f"💬 Text message: '{text}' from {phone_number}")
            handle_text_message(phone_number, text)
            return jsonify({"status": "text_handled"})
        
        # Handle location messages (could be used for pickup points)
        if "location" in message:
            logger.info(f"📍 Location received from {phone_number}")
            # Could implement location-based services here
            return jsonify({"status": "location_handled"})
        
        return jsonify({"status": "unhandled"})
        
    except Exception as e:
        logger.error(f"🚨 Webhook error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_interactive_message(phone_number, interaction_id):
    """Handle interactive message responses"""
    session = user_sessions.get(phone_number, {})
    language = session.get('language', 'english')
    
    logger.info(f"🔄 Handling interaction: {interaction_id} for {phone_number}")
    
    # Language selection
    if interaction_id == "lang_english":
        user_sessions[phone_number] = {'language': 'english'}
        send_main_menu(phone_number, 'english')
    
    elif interaction_id == "lang_arabic":
        user_sessions[phone_number] = {'language': 'arabic'}
        send_main_menu(phone_number, 'arabic')
    
    # Main menu
    elif interaction_id == "book_cruise":
        start_booking(phone_number, language)
    
    elif interaction_id == "pricing":
        if language == "arabic":
            message = """💰 *أسعار الرحلات*

*الصباح:* 2.500 ريال للشخص
(9:00 صباحاً - 10:30 صباحاً)

*الظهيرة:* 3.500 ريال للشخص  
(1:30 ظهراً - 3:00 عصراً)

*الغروب:* 4.500 ريال للشخص
(5:00 عصراً - 6:30 مساءً)

*المساء:* 3.500 ريال للشخص
(7:30 مساءً - 9:00 مساءً)

*الرضع:* مجاناً (أقل من سنتين)"""
        else:
            message = """💰 *Cruise Pricing*

*Morning:* 2.500 OMR per person
(9:00 AM - 10:30 AM)

*Afternoon:* 3.500 OMR per person  
(1:30 PM - 3:00 PM) 

*Sunset:* 4.500 OMR per person
(5:00 PM - 6:30 PM)

*Evening:* 3.500 OMR per person
(7:30 PM - 9:00 PM)

*Infants:* Free (below 2 years)"""
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    elif interaction_id == "schedule":
        if language == "arabic":
            message = """🕒 *جدول الرحلات*

*الصباح:* 9:00 صباحاً - 10:30 صباحاً
*الظهيرة:* 1:30 ظهراً - 3:00 عصراً  
*الغروب:* 5:00 عصراً - 6:30 مساءً
*المساء:* 7:30 مساءً - 9:00 مساءً

⏰ *وقت الحضور:* ساعة قبل الرحلة"""
        else:
            message = """🕒 *Cruise Schedule*

*Morning:* 9:00 AM - 10:30 AM
*Afternoon:* 1:30 PM - 3:00 PM  
*Sunset:* 5:00 PM - 6:30 PM
*Evening:* 7:30 PM - 9:00 PM

⏰ *Reporting Time:* 1 hour before cruise"""
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    elif interaction_id == "contact":
        contact = CRUISE_CONFIG["contact"]
        if language == "arabic":
            message = f"""📞 *معلومات الاتصال*

*هاتف:* {contact['phone1']} | {contact['phone2']}
*موقع:* {contact['location']}
*بريد:* {contact['email']}
*موقع:* {contact['website']}

⏰ *ساعات العمل:* 8:00 صباحاً - 10:00 مساءً"""
        else:
            message = f"""📞 *Contact Information*

*Phone:* {contact['phone1']} | {contact['phone2']}
*Location:* {contact['location']}
*Email:* {contact['email']}  
*Website:* {contact['website']}

⏰ *Working Hours:* 8:00 AM - 10:00 PM"""
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    # Cruise type selection
    elif interaction_id.startswith("cruise_"):
        cruise_type = interaction_id.replace("cruise_", "")
        if phone_number in user_sessions:
            user_sessions[phone_number]['cruise_type'] = cruise_type
            request_payment(phone_number, user_sessions[phone_number])
    
    # Payment method selection
    elif interaction_id.startswith("payment_"):
        if phone_number in user_sessions:
            handle_payment_method_selection(phone_number, interaction_id, user_sessions[phone_number])
    
    # Payment confirmation
    elif interaction_id == "confirm_booking":
        if phone_number in user_sessions:
            confirm_booking(phone_number, user_sessions[phone_number])
    
    elif interaction_id == "cancel_booking":
        cancel_booking(phone_number, language)

def handle_text_message(phone_number, text):
    """Handle text message responses with session timeout check"""
    # Cleanup expired sessions
    cleanup_expired_sessions()
    
    session = user_sessions.get(phone_number, {})
    language = session.get('language', 'english')
    
    # Check for session expiration
    if session and 'created_at' in session:
        created_at = datetime.fromisoformat(session['created_at'])
        if (datetime.now() - created_at).total_seconds() > (SESSION_TIMEOUT_MINUTES * 60):
            send_whatsapp_message(phone_number, MESSAGES[language]["session_expired"])
            del user_sessions[phone_number]
            return
    
    # New user - send language menu
    if not session and text.lower() in ["hi", "hello", "hey", "مرحبا", "اهلا", "السلام"]:
        send_language_menu(phone_number)
        return
    
    # Handle session expired
    if not session:
        send_language_menu(phone_number)
        return
    
    # Handle booking flow
    if session and session.get('step', '').startswith('awaiting_'):
        handle_booking_step(phone_number, text, language, session)
    elif session.get('step') == 'awaiting_payment_method':
        # Handle direct text input for payment method selection
        if text.lower() in ["whatsapp pay", "واتساب", "واتساب باي", "دفع واتساب"]:
            handle_payment_method_selection(phone_number, "payment_whatsapp", session)
        elif text.lower() in ["bank transfer", "تحويل بنكي", "بنك"]:
            handle_payment_method_selection(phone_number, "payment_bank", session)
        elif text.lower() in ["credit card", "بطاقة ائتمان", "بطاقة"]:
            handle_payment_method_selection(phone_number, "payment_card", session)
        else:
            send_whatsapp_message(phone_number, MESSAGES[language]["invalid_input"])
    else:
        # Fallback to main menu
        send_main_menu(phone_number, language)

# ==============================
# API ENDPOINTS
# ==============================

@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    status = {
        "status": "Sindbad Ship Cruises WhatsApp API 🚢",
        "timestamp": datetime.now().isoformat(),
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "sheets_available": sheet is not None,
        "active_sessions": len(user_sessions),
        "version": "3.0 - Enhanced with WhatsApp Payments",
        "currency": CRUISE_CONFIG["currency"],
        "max_capacity": CRUISE_CONFIG["max_capacity"]
    }
    return jsonify(status)

@app.route("/api/debug/sheets", methods=["GET"])
def debug_sheets():
    """Debug Google Sheets connection"""
    try:
        if not sheet:
            return jsonify({"error": "Sheet not available"}), 500
        
        # Test read
        records = sheet.get_all_records()
        
        # Test write
        test_id = f"TEST_{int(time.time())}"
        test_data = [
            datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            test_id,
            "Test User",
            "91234567",
            "96812345678",
            "2024-12-31",
            "9:00 AM - 10:30 AM",
            "Morning Cruise",
            2, 1, 0, 3, 7.500,
            'Paid', 'Test', 'TEST_123', 
            datetime.now().strftime("%Y-%m-%d %I:%M %p"),
            'English', 'Confirmed', 'Test Record',
            '', 'OMR'
        ]
        
        sheet.append_row(test_data)
        
        return jsonify({
            "status": "success",
            "records_count": len(records),
            "test_id": test_id,
            "sheet_name": SHEET_NAME
        })
        
    except Exception as e:
        logger.error(f"Debug sheets error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/bookings", methods=["GET"])
def get_all_bookings():
    """Get all bookings"""
    try:
        if not sheet:
            return jsonify({"error": "Sheets not available"}), 500
        
        records = sheet.get_all_records()
        return jsonify(records)
    except Exception as e:
        logger.error(f"Error getting bookings: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    """Get active sessions"""
    return jsonify({"sessions": user_sessions})

@app.route("/api/payment/webhook", methods=["POST"])
def payment_webhook():
    """
    Endpoint for WhatsApp Payments webhook (if configured)
    This is an alternative to the main webhook for payment updates
    """
    try:
        data = request.get_json()
        logger.info(f"🔔 Payment webhook received: {json.dumps(data, indent=2)}")
        
        # Handle payment updates
        if data.get("object") == "business_management":
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    if change.get("field") == "payments":
                        payment_updates = change.get("value", {}).get("payment_updates", [])
                        for update in payment_updates:
                            payment_request_id = update.get("request_id")
                            status = update.get("status")
                            logger.info(f"🔔 Payment status update: {payment_request_id} -> {status}")
                            handle_payment_status_update(payment_request_id, status)
        
        return jsonify({"status": "received"})
        
    except Exception as e:
        logger.error(f"🚨 Payment webhook error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================
# CORS SETUP
# ==============================

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# ==============================
# APPLICATION START
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Starting Sindbad Ship Cruises WhatsApp Bot on port {port}")
    logger.info(f"✅ WhatsApp Payments Integration: Enabled")
    logger.info(f"✅ Google Sheets: Connected")
    logger.info(f"✅ Session Timeout: {SESSION_TIMEOUT_MINUTES} minutes")
    
    # Start cleanup timer (run every 10 minutes)
    import threading
    def cleanup_scheduler():
        while True:
            time.sleep(600)  # 10 minutes
            cleanup_expired_sessions()
    
    cleanup_thread = threading.Thread(target=cleanup_scheduler, daemon=True)
    cleanup_thread.start()
    
    app.run(host="0.0.0.0", port=port, debug=False)