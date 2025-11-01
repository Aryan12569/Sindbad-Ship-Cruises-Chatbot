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
import threading

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
    
    # Enhanced headers for full feature set
    required_headers = [
        'Timestamp', 'Booking ID', 'Customer Name', 'Phone Number', 'WhatsApp ID',
        'Cruise Date', 'Cruise Time', 'Cruise Type', 'Adults Count', 'Children Count', 
        'Infants Count', 'Total Guests', 'Total Amount', 'Payment Status', 
        'Payment Method', 'Transaction ID', 'Payment Timestamp', 'Language', 
        'Booking Status', 'Notes', 'Special Requests', 'Customer Email',
        'Loyalty Points', 'Booking Source', 'Reminder Sent'
    ]
    
    current_headers = sheet.row_values(1)
    if not current_headers or current_headers != required_headers:
        if current_headers:
            sheet.clear()
        sheet.append_row(required_headers)
        logger.info("✅ Updated Google Sheets headers with enhanced features")
    
    # Test connection
    test_value = sheet.acell('A1').value
    logger.info(f"✅ Google Sheets connected successfully. First header: {test_value}")
    
except Exception as e:
    logger.error(f"❌ Google Sheets initialization failed: {str(e)}")
    sheet = None

# Enhanced session management
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
    "currency": "OMR",
    "loyalty_points_per_booking": 10,
    "cancellation_policy": "24 hours before cruise"
}

# ==============================
# COMPREHENSIVE MESSAGES
# ==============================
MESSAGES = {
    "english": {
        "welcome": "🌊 Welcome to Sindbad Ship Cruises!\n\nChoose your preferred language:",
        "main_menu": "🌊 *Sindbad Ship Cruises* 🚢\n\n*Cruise Features:*\n• 🛳️ Luxury sea cruise\n• ☕ Cafe on board\n• 🌅 Stunning sea views\n• 🎵 Music & entertainment\n• 📱 Digital booking & payments\n• ⭐ Loyalty rewards program\n\nPlease choose from the menu:",
        
        # Booking flow
        "booking_start": "📝 *Let's Book Your Cruise!* 🎫\n\nI'll help you book your sea cruise. 🚢\n\nFirst, please send me your:\n\n👤 *Full Name*\n\n*Example:*\nAhmed Al Harthy",
        "ask_phone": "Perfect, {}! 👋\n\nNow please send me your:\n\n📞 *Phone Number*\n\n*Example:*\n91234567",
        "ask_email": "Great! 📧\n\nPlease provide your email for booking confirmation:\n\n*Example:*\nahmed@email.com\n\n*Optional but recommended for receipts*",
        "ask_date": "📅 *Cruise Date*\n\nPlease send your *preferred date* for the cruise:\n\n📋 *Format Examples:*\n• **Tomorrow**\n• **October 29**\n• **Next Friday**\n• **15 November**\n• **2024-12-25**",
        "ask_adults": "👥 *Number of Adults*\n\nHow many *adults* (12 years and above) will be joining?\n\nPlease send the number:\n*Examples:* 2, 4, 6",
        "ask_children": "👶 *Number of Children*\n\nAdults: {}\n\nHow many *children* (2-11 years) will be joining?\n\nPlease send the number:\n*Examples:* 0, 1, 2",
        "ask_infants": "🍼 *Number of Infants*\n\nAdults: {}\nChildren: {}\n\nHow many *infants* (below 2 years) will be joining?\n\n*Note:* Infants are free\n\nPlease send the number:\n*Examples:* 0, 1, 2",
        "ask_special_requests": "💫 *Special Requests* (Optional)\n\nAny special requests?\n• Birthday celebration 🎂\n• Anniversary 💝\n• Dietary requirements 🥗\n• Other preferences\n\n*Type your request or send 'Skip' to continue*",
        "ask_cruise_type": "🕒 *Choose Cruise Type*\n\n{} total guests:\n• {} adults\n• {} children\n• {} infants\n\nPlease choose your cruise:",
        
        # Payment flow
        "payment_options": "💳 *Payment Options*\n\n*Total Amount: {} OMR*\n\nChoose your payment method:\n\n1. 💳 **WhatsApp Pay** (Instant confirmation)\n2. 🏦 **Bank Transfer** (Manual processing)\n3. 💳 **Credit/Debit Card** (Secure link)\n4. 💵 **Cash on Arrival** (Pay at venue)",
        "payment_simulation": "💳 *Payment Simulation - DEMO MODE*\n\n*Total Amount: {} OMR*\nBooking ID: {}\n\nSince this is a demo, we'll simulate payment processing.\n\nChoose payment method to simulate:",
        "payment_processing": "🔄 Processing {} payment...\n\nAmount: {} OMR\nBooking ID: {}\n\n*Simulating payment gateway...*",
        "payment_success": "✅ *Payment Successful!*\n\n{} payment of {} OMR confirmed.\nTransaction ID: {}\n\nYour booking is now being confirmed...",
        "payment_failed": "❌ *Payment Failed*\n\nWe couldn't process your {} payment.\n\nPlease try another payment method or contact support.",
        
        # Booking management
        "my_bookings": "📋 *Your Bookings*\n\nHere are your active bookings:",
        "booking_details": "📄 *Booking Details*\n\n🆔 Booking ID: {}\n📅 Date: {}\n🕒 Time: {}\n🚢 Cruise: {}\n👥 Guests: {}\n💰 Amount: {} OMR\n📊 Status: {}\n\nWhat would you like to do?",
        "modify_options": "🔄 *Modify Booking*\n\nWhat would you like to change?\n• 📅 Change date\n• 👥 Change number of guests\n• 🚢 Change cruise type\n• 💫 Update special requests",
        "cancel_confirm": "❌ *Cancel Booking*\n\nBooking ID: {}\nDate: {}\nCruise: {}\n\n*Cancellation Policy:* {}\n\nAre you sure you want to cancel?",
        "cancellation_success": "✅ *Booking Cancelled*\n\nBooking {} has been cancelled.\nWe hope to see you another time!",
        "cancellation_failed": "❌ *Cancellation Not Allowed*\n\nYou cannot cancel within 24 hours of the cruise.\nPlease contact us directly for assistance.",
        
        # Confirmation & Receipt
        "booking_confirmed": "🎉 *Booking Confirmed!* ✅\n\nThank you {}! Your cruise has been booked successfully. 🚢\n\n📋 *Booking Details:*\n🆔 Booking ID: {}\n👤 Name: {}\n📞 Phone: {}\n📧 Email: {}\n📅 Date: {}\n🕒 Time: {}\n🚢 Cruise Type: {}\n👥 Guests: {} total\n   • {} adults\n   • {} children\n   • {} infants\n💰 Amount: {} OMR\n💳 Payment: {}\n💫 Requests: {}\n⭐ Points Earned: {}\n\n⏰ *Reporting Time:* {}\n📍 *Location:* {}\n📞 *For inquiries:* {} | {}\n\nWe wish you a wonderful cruise experience! 🌊",
        
        # Loyalty & Offers
        "loyalty_welcome": "⭐ *Welcome to our Loyalty Program!*\n\nYou've earned {} points for this booking!\n\n🎯 *Benefits:*\n• Earn points on every booking\n• Redeem for free cruises\n• Exclusive member offers\n• Priority booking\n\nKeep booking to earn more rewards!",
        "special_offer": "🎁 *Special Offer!*\n\nBook 3 or more adults and get 10% discount!\n\nCurrent booking: {} adults\n\nWould you like to add more guests for the discount?",
        
        # Reminders & Notifications
        "reminder_24h": "⏰ *Cruise Reminder*\n\nYour Sindbad Cruise is tomorrow!\n\n📅 Date: {}\n🕒 Time: {}\n🚢 Type: {}\n👥 Guests: {}\n📍 Location: {}\n\n⏰ Please arrive 1 hour before departure.\nWe look forward to welcoming you!",
        "weather_alert": "🌦️ *Weather Update*\n\nPlease note: There might be light rain during your cruise today.\n\nWe recommend bringing a light jacket.\nThe cruise will proceed as scheduled.",
        
        # Admin features
        "admin_dashboard": "👑 *Admin Dashboard*\n\n📊 Today's Bookings: {}\n💰 Today's Revenue: {} OMR\n👥 Total Capacity: {}/{}\n🎫 Available Slots: {}\n\nAdmin options:",
        
        "invalid_input": "❌ Invalid input. Please try again.",
        "session_expired": "⏳ Your session has expired. Please start over by sending 'Hi'.",
        "feature_coming_soon": "🚧 *Feature Coming Soon!*\n\nThis feature is under development and will be available soon."
    },
    "arabic": {
        "welcome": "🌊 مرحباً بكم في رحلات السندباد البحرية!\n\nاختر لغتك المفضلة:",
        "main_menu": "🌊 *رحلات السندباد البحرية* 🚢\n\n*مميزات الرحلة:*\n• 🛳️ رحلة بحرية فاخرة\n• ☕ مقهى على متن السفينة\n• 🌅 مناظر بحرية خلابة\n• 🎵 موسيقى وترفيه\n• 📱 حجز ودفع رقمي\n• ⭐ برنامج مكافآت الولاء\n\nاختر من القائمة:",
        
        # Booking flow (Arabic versions)
        "booking_start": "📝 *لنحجز رحلتك!* 🎫\n\nسأساعدك في حجز رحلتك البحرية. 🚢\n\nأولاً، الرجاء إرسال:\n\n👤 *الاسم الكامل*\n\n*مثال:*\nأحمد الحارثي",
        "ask_phone": "ممتاز، {}! 👋\n\nالآن الرجاء إرسال:\n\n📞 *رقم الهاتف*\n\n*مثال:*\n91234567",
        "ask_email": "ممتاز! 📧\n\nالرجاء تقديم بريدك الإلكتروني لتأكيد الحجز:\n\n*مثال:*\nahmed@email.com\n\n*اختياري لكن موصى به للإيصالات*",
        "ask_date": "📅 *تاريخ الرحلة*\n\nالرجاء إرسال *التاريخ المفضل* للرحلة:\n\n📋 *أمثلة على التنسيق:*\n• **غداً**\n• **29 أكتوبر**\n• **الجمعة القادمة**\n• **15 نوفمبر**\n• **2024-12-25**",
        "ask_adults": "👥 *عدد البالغين*\n\nكم عدد *البالغين* (12 سنة فما فوق) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 2, 4, 6",
        "ask_children": "👶 *عدد الأطفال*\n\nالبالغين: {}\n\nكم عدد *الأطفال* (2-11 سنة) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 0, 1, 2",
        "ask_infants": "🍼 *عدد الرضع*\n\nالبالغين: {}\nالأطفال: {}\n\nكم عدد *الرضع* (أقل من سنتين) الذين سينضمون؟\n\n*ملاحظة:* الرضع مجاناً\n\nالرجاء إرسال الرقم:\n*أمثلة:* 0, 1, 2",
        "ask_special_requests": "💫 *طلبات خاصة* (اختياري)\n\nأي طلبات خاصة؟\n• احتفال عيد ميلاد 🎂\n• ذكرى سنوية 💝\n• متطلبات غذائية 🥗\n• تفضيلات أخرى\n\n*اكتب طلبك أو أرسل 'تخطى' للمتابعة*",
        
        # Add all other Arabic translations...
        "booking_confirmed": "🎉 *تم تأكيد الحجز!* ✅\n\nشكراً {}! تم حجز رحلتك بنجاح. 🚢\n\n📋 *تفاصيل الحجز:*\n🆔 رقم الحجز: {}\n👤 الاسم: {}\n📞 الهاتف: {}\n📧 البريد: {}\n📅 التاريخ: {}\n🕒 الوقت: {}\n🚢 نوع الرحلة: {}\n👥 الضيوف: {} إجمالاً\n   • {} بالغين\n   • {} أطفال\n   • {} رضع\n💰 المبلغ: {} ريال عماني\n💳 الدفع: {}\n💫 الطلبات: {}\n⭐ النقاط المكتسبة: {}\n\n⏰ *وقت الحضور:* {}\n📍 *موقعنا:* {}\n📞 *للاستفسار:* {} | {}\n\nنتمنى لكم رحلة بحرية ممتعة! 🌊",
        
        "invalid_input": "❌ إدخال غير صالح. يرجى المحاولة مرة أخرى.",
        "session_expired": "⏳ انتهت جلستك. يرجى البدء من جديد بإرسال 'مرحبا'.",
        "feature_coming_soon": "🚧 *الميزة قريباً!*\n\nهذه الميزة قيد التطوير وستكون متاحة قريباً."
    }
}

# ==============================
# ENHANCED HELPER FUNCTIONS
# ==============================

def generate_booking_id():
    """Generate unique booking ID"""
    return f"SDB{int(time.time())}{uuid.uuid4().hex[:4].upper()}"

def clean_phone_number(number):
    """Clean and validate phone numbers for WhatsApp API"""
    if not number:
        return None
    
    clean_number = ''.join(filter(str.isdigit, str(number)))
    clean_number = clean_number.lstrip('0')
    
    if len(clean_number) == 8 and clean_number.startswith(('9', '7', '8')):
        return '968' + clean_number
    elif len(clean_number) == 9 and clean_number.startswith('9'):
        return '968' + clean_number
    elif len(clean_number) == 12 and clean_number.startswith('968'):
        return clean_number
    
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
            if (str(record.get('Cruise Date', '')).strip() == str(date).strip() and 
                str(record.get('Cruise Type', '')).strip() == str(cruise_type).strip() and
                str(record.get('Booking Status', '')).strip().lower() != 'cancelled'):
                total_guests += int(record.get('Total Guests', 0))
        
        return total_guests
    except Exception as e:
        logger.error(f"Error getting capacity: {str(e)}")
        return 0

def calculate_total_amount(cruise_type, adults, children, infants):
    """Calculate total amount for booking with potential discounts"""
    config = CRUISE_CONFIG["cruise_types"][cruise_type]
    base_total = (adults * config["price_adult"]) + (children * config["price_child"])
    
    # Apply group discount for 3+ adults
    if adults >= 3:
        discount = base_total * 0.10  # 10% discount
        final_total = base_total - discount
        logger.info(f"🎯 Applied group discount: {discount} OMR")
        return round(final_total, 3), discount
    else:
        return round(base_total, 3), 0

def send_whatsapp_message(to, message, interactive_data=None):
    """Send WhatsApp message via Meta API with enhanced logging"""
    try:
        clean_to = clean_phone_number(to)
        if not clean_to:
            logger.error(f"❌ Invalid phone number: {to}")
            return False
        
        url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        if interactive_data:
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_to,
                "type": "interactive",
                "interactive": interactive_data
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_to,
                "type": "text",
                "text": {"body": message}
            }

        logger.info(f"📤 Sending message to {clean_to}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200:
            logger.info(f"✅ Message sent to {clean_to}")
            return True
        else:
            error_msg = response_data.get('error', {}).get('message', 'Unknown error')
            logger.error(f"❌ WhatsApp API error: {error_msg}")
            return False
        
    except Exception as e:
        logger.error(f"🚨 Failed to send message: {str(e)}")
        return False

def save_booking_to_sheets(booking_data, language, payment_status="Paid", payment_method="Simulated", transaction_id=None, email="", special_requests="", loyalty_points=0):
    """Save booking to Google Sheets with enhanced data tracking"""
    try:
        if not sheet:
            logger.error("❌ Google Sheets not available")
            return False
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
        
        if not transaction_id:
            transaction_id = f"SIM_{int(time.time())}"
        
        row_data = [
            timestamp,
            booking_data['booking_id'],
            booking_data['name'],
            booking_data['phone'],
            booking_data['whatsapp_id'],
            booking_data['cruise_date'],
            cruise_info['time'],
            cruise_info['name_en'],
            str(booking_data['adults_count']),
            str(booking_data['children_count']),
            str(booking_data['infants_count']),
            str(booking_data['total_guests']),
            str(booking_data['total_amount']),
            payment_status,
            payment_method,
            transaction_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            language.title(),
            'Confirmed',
            'Via WhatsApp Bot - Demo Mode',
            special_requests,
            email,
            str(loyalty_points),
            'WhatsApp Bot',
            'No'
        ]
        
        logger.info(f"💾 Saving to sheets: {booking_data['booking_id']}")
        sheet.append_row(row_data)
        logger.info(f"✅ Booking saved: {booking_data['booking_id']}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to save booking: {str(e)}")
        return False

def get_user_bookings(whatsapp_id):
    """Get all bookings for a user"""
    try:
        if not sheet:
            return []
            
        records = sheet.get_all_records()
        user_bookings = []
        
        for record in records:
            if (str(record.get('WhatsApp ID', '')).strip() == str(whatsapp_id).strip() and
                str(record.get('Booking Status', '')).strip().lower() != 'cancelled'):
                user_bookings.append(record)
        
        return user_bookings
    except Exception as e:
        logger.error(f"Error getting user bookings: {str(e)}")
        return []

def can_cancel_booking(cruise_date):
    """Check if booking can be cancelled (not within 24 hours)"""
    try:
        # Parse date (assuming format like "2024-12-25" or "Tomorrow")
        if cruise_date.lower() == 'tomorrow':
            cruise_datetime = datetime.now() + timedelta(days=1)
        else:
            cruise_datetime = datetime.strptime(cruise_date, "%Y-%m-%d")
        
        now = datetime.now()
        time_diff = cruise_datetime - now
        return time_diff.total_seconds() > 24 * 3600  # More than 24 hours
    except:
        return False

def calculate_loyalty_points(amount, guests):
    """Calculate loyalty points for booking"""
    base_points = CRUISE_CONFIG["loyalty_points_per_booking"]
    bonus_points = guests  # 1 point per guest
    return base_points + bonus_points

def send_reminder(booking_data):
    """Send 24-hour reminder for cruise"""
    try:
        language = "english"  # Default, could be detected from booking
        contact = CRUISE_CONFIG["contact"]
        cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
        
        if language == "arabic":
            message = MESSAGES["arabic"]["reminder_24h"].format(
                booking_data['cruise_date'],
                cruise_info['time_ar'],
                cruise_info['name_ar'],
                booking_data['total_guests'],
                contact['location']
            )
        else:
            message = MESSAGES["english"]["reminder_24h"].format(
                booking_data['cruise_date'],
                cruise_info['time'],
                cruise_info['name_en'],
                booking_data['total_guests'],
                contact['location']
            )
        
        return send_whatsapp_message(booking_data['whatsapp_id'], message)
    except Exception as e:
        logger.error(f"Error sending reminder: {str(e)}")
        return False

# ==============================
# COMPREHENSIVE FLOW MANAGEMENT
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
    """Send enhanced main menu with all features"""
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
                        {"id": "my_bookings", "title": "📋 حجوزاتي", "description": "عرض أو إدارة الحجوزات"},
                        {"id": "loyalty_info", "title": "⭐ برنامج الولاء", "description": "نقاط المكافآت والعروض"},
                        {"id": "pricing", "title": "💰 الأسعار", "description": "أسعار الرحلات والعروض"},
                        {"id": "schedule", "title": "🕒 الجدول", "description": "مواعيد الرحلات"},
                        {"id": "contact", "title": "📞 اتصل بنا", "description": "معلومات الاتصال والدعم"}
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
                        {"id": "my_bookings", "title": "📋 My Bookings", "description": "View or manage bookings"},
                        {"id": "loyalty_info", "title": "⭐ Loyalty Program", "description": "Reward points & offers"},
                        {"id": "pricing", "title": "💰 Pricing", "description": "Cruise prices & offers"},
                        {"id": "schedule", "title": "🕒 Schedule", "description": "Cruise timings"},
                        {"id": "contact", "title": "📞 Contact Us", "description": "Contact information & support"}
                    ]
                }]
            }
        }
    
    return send_whatsapp_message(to, message, interactive_data)

def start_booking(to, language):
    """Start comprehensive booking flow"""
    user_sessions[to] = {
        'language': language,
        'step': 'awaiting_name',
        'created_at': datetime.now().isoformat()
    }
    message = MESSAGES[language]["booking_start"]
    return send_whatsapp_message(to, message)

def handle_booking_step(to, text, language, session):
    """Handle enhanced booking flow steps"""
    step = session.get('step')
    
    if step == 'awaiting_name':
        session.update({'step': 'awaiting_phone', 'name': text})
        message = MESSAGES[language]["ask_phone"].format(text)
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_phone':
        session.update({'step': 'awaiting_email', 'phone': text})
        message = MESSAGES[language]["ask_email"]
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_email':
        session.update({'step': 'awaiting_date', 'email': text if text.lower() != 'skip' else ''})
        message = MESSAGES[language]["ask_date"]
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_date':
        session.update({'step': 'awaiting_adults', 'cruise_date': text})
        message = MESSAGES[language]["ask_adults"]
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_adults':
        if text.isdigit() and int(text) > 0:
            session.update({'step': 'awaiting_children', 'adults_count': int(text)})
            message = MESSAGES[language]["ask_children"].format(text)
            return send_whatsapp_message(to, message)
        else:
            return send_whatsapp_message(to, MESSAGES[language]["invalid_input"])
    
    elif step == 'awaiting_children':
        if text.isdigit() and int(text) >= 0:
            session.update({'step': 'awaiting_infants', 'children_count': int(text)})
            message = MESSAGES[language]["ask_infants"].format(
                session['adults_count'], text
            )
            return send_whatsapp_message(to, message)
        else:
            return send_whatsapp_message(to, MESSAGES[language]["invalid_input"])
    
    elif step == 'awaiting_infants':
        if text.isdigit() and int(text) >= 0:
            session.update({'infants_count': int(text), 'step': 'awaiting_special_requests'})
            message = MESSAGES[language]["ask_special_requests"]
            return send_whatsapp_message(to, message)
        else:
            return send_whatsapp_message(to, MESSAGES[language]["invalid_input"])
    
    elif step == 'awaiting_special_requests':
        session.update({'special_requests': text if text.lower() != 'skip' else ''})
        return send_cruise_type_menu(to, language, session)
    
    return False

def send_cruise_type_menu(to, language, session):
    """Send cruise type selection menu with enhanced info"""
    adults = session['adults_count']
    children = session['children_count']
    infants = session['infants_count']
    total_guests = adults + children + infants
    date = session['cruise_date']
    
    # Check capacity and apply group discount logic
    available_cruises = []
    for cruise_key, cruise_info in CRUISE_CONFIG["cruise_types"].items():
        current_capacity = get_cruise_capacity(date, cruise_info["name_en"])
        available_seats = CRUISE_CONFIG["max_capacity"] - current_capacity
        
        if available_seats >= total_guests:
            # Calculate price with potential discount
            total_amount, discount = calculate_total_amount(cruise_key, adults, children, infants)
            
            available_cruises.append((cruise_key, cruise_info, available_seats, total_amount, discount))
    
    if not available_cruises:
        if language == "arabic":
            message = f"❌ عذراً، لا توجد أماكن متاحة بتاريخ {date}.\nيرجى اختيار تاريخ آخر."
        else:
            message = f"❌ Sorry, no available seats on {date}.\nPlease choose another date."
        send_whatsapp_message(to, message)
        start_booking(to, language)
        return False
    
    # Check for group discount eligibility
    if adults >= 3 and language == "english":
        discount_message = MESSAGES["english"]["special_offer"].format(adults)
        send_whatsapp_message(to, discount_message)
    
    if language == "arabic":
        body_text = MESSAGES["arabic"]["ask_cruise_type"].format(
            total_guests, adults, children, infants
        )
        rows = []
        for cruise_key, cruise_info, available_seats, total_amount, discount in available_cruises:
            description = f"{cruise_info['time_ar']} - {available_seats} مقاعد"
            if discount > 0:
                description += f" - خصم 10% 🎁"
            rows.append({
                "id": f"cruise_{cruise_key}",
                "title": f"🕒 {cruise_info['name_ar']}",
                "description": description
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
        for cruise_key, cruise_info, available_seats, total_amount, discount in available_cruises:
            description = f"{cruise_info['time']} - {available_seats} seats"
            if discount > 0:
                description += f" - 10% OFF 🎁"
            rows.append({
                "id": f"cruise_{cruise_key}",
                "title": f"🕒 {cruise_info['name_en']}",
                "description": description
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

def send_payment_options(to, session):
    """Send comprehensive payment options"""
    language = session['language']
    total_amount, discount = calculate_total_amount(
        session['cruise_type'],
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
        'cruise_type': session['cruise_type'],
        'adults_count': session['adults_count'],
        'children_count': session['children_count'],
        'infants_count': session['infants_count'],
        'total_guests': session['adults_count'] + session['children_count'] + session['infants_count'],
        'total_amount': total_amount,
        'email': session.get('email', ''),
        'special_requests': session.get('special_requests', '')
    }
    
    session['booking_data'] = booking_data
    session['step'] = 'awaiting_payment_method'
    
    if language == "arabic":
        message = MESSAGES["arabic"]["payment_simulation"].format(total_amount, booking_id)
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "💳 طرق الدفع"},
            "body": {"text": message},
            "action": {
                "button": "اختر طريقة الدفع",
                "sections": [{
                    "title": "الدفع",
                    "rows": [
                        {"id": "pay_whatsapp", "title": "💳 دفع واتساب", "description": "محاكاة الدفع عبر واتساب"},
                        {"id": "pay_bank", "title": "🏦 تحويل بنكي", "description": "محاكاة التحويل البنكي"},
                        {"id": "pay_card", "title": "💳 بطاقة ائتمان", "description": "محاكاة الدفع بالبطاقة"},
                        {"id": "pay_cash", "title": "💵 نقداً عند الوصول", "description": "الدفع في الموقع"}
                    ]
                }]
            }
        }
    else:
        message = MESSAGES["english"]["payment_simulation"].format(total_amount, booking_id)
        interactive_data = {
            "type": "list",
            "header": {"type": "text", "text": "💳 Payment Methods"},
            "body": {"text": message},
            "action": {
                "button": "Select Payment",
                "sections": [{
                    "title": "Payment",
                    "rows": [
                        {"id": "pay_whatsapp", "title": "💳 WhatsApp Pay", "description": "Simulate WhatsApp payment"},
                        {"id": "pay_bank", "title": "🏦 Bank Transfer", "description": "Simulate bank transfer"},
                        {"id": "pay_card", "title": "💳 Credit Card", "description": "Simulate card payment"},
                        {"id": "pay_cash", "title": "💵 Cash on Arrival", "description": "Pay at venue"}
                    ]
                }]
            }
        }
    
    return send_whatsapp_message(to, "", interactive_data)

def simulate_payment_processing(to, session, payment_method):
    """Simulate payment processing with different methods"""
    language = session['language']
    booking_data = session['booking_data']
    amount = booking_data['total_amount']
    
    payment_methods = {
        "pay_whatsapp": {"name": "WhatsApp Pay", "processing_time": 5},
        "pay_bank": {"name": "Bank Transfer", "processing_time": 8},
        "pay_card": {"name": "Credit Card", "processing_time": 6},
        "pay_cash": {"name": "Cash on Arrival", "processing_time": 0}
    }
    
    method_info = payment_methods[payment_method]
    
    # Send processing message
    processing_msg = MESSAGES[language]["payment_processing"].format(method_info["name"], amount, booking_data['booking_id'])
    send_whatsapp_message(to, processing_msg)
    
    # Simulate processing time
    if method_info["processing_time"] > 0:
        time.sleep(2)  # Short delay for realism
    
    # Generate transaction ID
    transaction_id = f"{method_info['name'].replace(' ', '').upper()}_{int(time.time())}"
    
    # Send success message
    success_msg = MESSAGES[language]["payment_success"].format(method_info["name"], amount, transaction_id)
    send_whatsapp_message(to, success_msg)
    
    # Calculate loyalty points
    loyalty_points = calculate_loyalty_points(amount, booking_data['total_guests'])
    
    # Save booking
    save_booking_to_sheets(
        booking_data, 
        language, 
        "Paid", 
        method_info["name"],
        transaction_id,
        booking_data['email'],
        booking_data['special_requests'],
        loyalty_points
    )
    
    # Send loyalty message if points earned
    if loyalty_points > 0:
        loyalty_msg = MESSAGES[language]["loyalty_welcome"].format(loyalty_points)
        send_whatsapp_message(to, loyalty_msg)
    
    # Final confirmation
    return send_booking_confirmation(to, session, method_info["name"], transaction_id, loyalty_points)

def send_booking_confirmation(to, session, payment_method, transaction_id, loyalty_points):
    """Send comprehensive booking confirmation"""
    language = session['language']
    booking_data = session['booking_data']
    contact = CRUISE_CONFIG["contact"]
    cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
    
    if language == "arabic":
        message = MESSAGES["arabic"]["booking_confirmed"].format(
            booking_data['name'],
            booking_data['booking_id'],
            booking_data['name'],
            booking_data['phone'],
            booking_data['email'] if booking_data['email'] else "Not provided",
            booking_data['cruise_date'],
            cruise_info['time_ar'],
            cruise_info['name_ar'],
            booking_data['total_guests'],
            booking_data['adults_count'],
            booking_data['children_count'],
            booking_data['infants_count'],
            booking_data['total_amount'],
            payment_method,
            booking_data['special_requests'] if booking_data['special_requests'] else "None",
            loyalty_points,
            CRUISE_CONFIG["reporting_time"],
            contact['location'],
            contact['phone1'],
            contact['phone2']
        )
    else:
        message = MESSAGES["english"]["booking_confirmed"].format(
            booking_data['name'],
            booking_data['booking_id'],
            booking_data['name'],
            booking_data['phone'],
            booking_data['email'] if booking_data['email'] else "Not provided",
            booking_data['cruise_date'],
            cruise_info['time'],
            cruise_info['name_en'],
            booking_data['total_guests'],
            booking_data['adults_count'],
            booking_data['children_count'],
            booking_data['infants_count'],
            booking_data['total_amount'],
            payment_method,
            booking_data['special_requests'] if booking_data['special_requests'] else "None",
            loyalty_points,
            CRUISE_CONFIG["reporting_time"],
            contact['location'],
            contact['phone1'],
            contact['phone2']
        )
    
    # Clear session
    if to in user_sessions:
        del user_sessions[to]
    
    return send_whatsapp_message(to, message)

def send_my_bookings_menu(to, language):
    """Send user's bookings with management options"""
    try:
        user_bookings = get_user_bookings(to)
        
        if not user_bookings:
            if language == "arabic":
                message = "📭 لا توجد حجوزات نشطة."
            else:
                message = "📭 No active bookings found."
            return send_whatsapp_message(to, message)
        
        if language == "arabic":
            message = "📋 *حجوزاتك النشطة*\n\n"
            for i, booking in enumerate(user_bookings[:3], 1):
                message += f"{i}. 🆔 {booking['Booking ID']}\n"
                message += f"   📅 {booking['Cruise Date']}\n"
                message += f"   🕒 {booking['Cruise Type']}\n"
                message += f"   👥 {booking['Total Guests']} ضيوف\n"
                message += f"   💰 {booking['Total Amount']} ريال\n\n"
            
            interactive_data = {
                "type": "list",
                "header": {"type": "text", "text": "إدارة الحجوزات"},
                "body": {"text": "اختر الحجز الذي تريد إدارته:"},
                "action": {
                    "button": "اختر الحجز",
                    "sections": [{
                        "title": "حجوزاتك",
                        "rows": [
                            {
                                "id": f"manage_{booking['Booking ID']}",
                                "title": f"📝 {booking['Booking ID']}",
                                "description": f"{booking['Cruise Date']} - {booking['Cruise Type']}"
                            } for booking in user_bookings[:3]
                        ]
                    }]
                }
            }
        else:
            message = "📋 *Your Active Bookings*\n\n"
            for i, booking in enumerate(user_bookings[:3], 1):
                message += f"{i}. 🆔 {booking['Booking ID']}\n"
                message += f"   📅 {booking['Cruise Date']}\n"
                message += f"   🕒 {booking['Cruise Type']}\n"
                message += f"   👥 {booking['Total Guests']} guests\n"
                message += f"   💰 {booking['Total Amount']} OMR\n\n"
            
            interactive_data = {
                "type": "list",
                "header": {"type": "text", "text": "Manage Bookings"},
                "body": {"text": "Select booking to manage:"},
                "action": {
                    "button": "Select Booking",
                    "sections": [{
                        "title": "Your Bookings",
                        "rows": [
                            {
                                "id": f"manage_{booking['Booking ID']}",
                                "title": f"📝 {booking['Booking ID']}",
                                "description": f"{booking['Cruise Date']} - {booking['Cruise Type']}"
                            } for booking in user_bookings[:3]
                        ]
                    }]
                }
            }
        
        send_whatsapp_message(to, message)
        return send_whatsapp_message(to, "", interactive_data)
        
    except Exception as e:
        logger.error(f"Error in send_my_bookings_menu: {str(e)}")
        return send_whatsapp_message(to, "Error retrieving bookings.")

# ==============================
# WEBHOOK HANDLERS (Same as before but enhanced)
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
    """Handle incoming WhatsApp messages"""
    try:
        data = request.get_json()
        
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
        
        return jsonify({"status": "unhandled"})
        
    except Exception as e:
        logger.error(f"🚨 Webhook error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_interactive_message(phone_number, interaction_id):
    """Handle enhanced interactive message responses"""
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
    
    # Main menu options
    elif interaction_id == "book_cruise":
        start_booking(phone_number, language)
    
    elif interaction_id == "my_bookings":
        send_my_bookings_menu(phone_number, language)
    
    elif interaction_id == "loyalty_info":
        send_whatsapp_message(phone_number, MESSAGES[language]["feature_coming_soon"])
        send_main_menu(phone_number, language)
    
    elif interaction_id == "pricing":
        # Enhanced pricing with offers
        if language == "arabic":
            message = "💰 *أسعار الرحلات والعروض*\n\n*الصباح:* 2.500 ريال للشخص\n*الظهيرة:* 3.500 ريال للشخص\n*الغروب:* 4.500 ريال للشخص\n*المساء:* 3.500 ريال للشخص\n\n🎁 *العروض الخاصة:*\n• خصم 10% لمجموعات 3 بالغين أو أكثر\n• الأطفال تحت سنتين: مجاناً\n• برنامج ولاء: اكسب نقاط في كل حجز"
        else:
            message = "💰 *Cruise Pricing & Offers*\n\n*Morning:* 2.500 OMR per person\n*Afternoon:* 3.500 OMR per person\n*Sunset:* 4.500 OMR per person\n*Evening:* 3.500 OMR per person\n\n🎁 *Special Offers:*\n• 10% discount for groups of 3+ adults\n• Infants below 2 years: Free\n• Loyalty program: Earn points on every booking"
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    elif interaction_id == "schedule":
        if language == "arabic":
            message = "🕒 *جدول الرحلات*\n\n*الصباح:* 9:00 صباحاً - 10:30 صباحاً\n*الظهيرة:* 1:30 ظهراً - 3:00 عصراً\n*الغروب:* 5:00 عصراً - 6:30 مساءً\n*المساء:* 7:30 مساءً - 9:00 مساءً\n\n⏰ *وقت الحضور:* ساعة قبل الرحلة\n📍 *المكان:* يرجى الوصول قبل ساعة من موعد الرحلة"
        else:
            message = "🕒 *Cruise Schedule*\n\n*Morning:* 9:00 AM - 10:30 AM\n*Afternoon:* 1:30 PM - 3:00 PM\n*Sunset:* 5:00 PM - 6:30 PM\n*Evening:* 7:30 PM - 9:00 PM\n\n⏰ *Reporting Time:* 1 hour before cruise\n📍 *Location:* Please arrive 1 hour before departure"
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    elif interaction_id == "contact":
        contact = CRUISE_CONFIG["contact"]
        if language == "arabic":
            message = f"📞 *معلومات الاتصال والدعم*\n\n*هاتف:* {contact['phone1']} | {contact['phone2']}\n*موقع:* {contact['location']}\n*بريد:* {contact['email']}\n*موقع:* {contact['website']}\n\n⏰ *ساعات العمل:* 8:00 صباحاً - 10:00 مساءً\n🆘 *الدعم:* متاح عبر واتساب 24/7"
        else:
            message = f"📞 *Contact Information & Support*\n\n*Phone:* {contact['phone1']} | {contact['phone2']}\n*Location:* {contact['location']}\n*Email:* {contact['email']}\n*Website:* {contact['website']}\n\n⏰ *Working Hours:* 8:00 AM - 10:00 PM\n🆘 *Support:* Available via WhatsApp 24/7"
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    # Cruise type selection
    elif interaction_id.startswith("cruise_"):
        cruise_type = interaction_id.replace("cruise_", "")
        if phone_number in user_sessions:
            user_sessions[phone_number]['cruise_type'] = cruise_type
            send_payment_options(phone_number, user_sessions[phone_number])
    
    # Payment method selection
    elif interaction_id.startswith("pay_"):
        if phone_number in user_sessions:
            simulate_payment_processing(phone_number, user_sessions[phone_number], interaction_id)
    
    # Booking management
    elif interaction_id.startswith("manage_"):
        booking_id = interaction_id.replace("manage_", "")
        # Send booking management options
        if language == "arabic":
            message = f"📝 *إدارة الحجز*\n\nرقم الحجز: {booking_id}\n\nاختر الإجراء:"
            interactive_data = {
                "type": "button",
                "body": {"text": message},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": f"view_{booking_id}", "title": "👁️ عرض التفاصيل"}},
                        {"type": "reply", "reply": {"id": f"modify_{booking_id}", "title": "🔄 تعديل"}},
                        {"type": "reply", "reply": {"id": f"cancel_{booking_id}", "title": "❌ إلغاء"}}
                    ]
                }
            }
        else:
            message = f"📝 *Manage Booking*\n\nBooking ID: {booking_id}\n\nChoose action:"
            interactive_data = {
                "type": "button",
                "body": {"text": message},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": f"view_{booking_id}", "title": "👁️ View Details"}},
                        {"type": "reply", "reply": {"id": f"modify_{booking_id}", "title": "🔄 Modify"}},
                        {"type": "reply", "reply": {"id": f"cancel_{booking_id}", "title": "❌ Cancel"}}
                    ]
                }
            }
        send_whatsapp_message(phone_number, "", interactive_data)
    
    # View booking details
    elif interaction_id.startswith("view_"):
        booking_id = interaction_id.replace("view_", "")
        send_whatsapp_message(phone_number, MESSAGES[language]["feature_coming_soon"])
        send_main_menu(phone_number, language)
    
    # Modify booking
    elif interaction_id.startswith("modify_"):
        booking_id = interaction_id.replace("modify_", "")
        send_whatsapp_message(phone_number, MESSAGES[language]["feature_coming_soon"])
        send_main_menu(phone_number, language)
    
    # Cancel booking
    elif interaction_id.startswith("cancel_"):
        booking_id = interaction_id.replace("cancel_", "")
        send_whatsapp_message(phone_number, MESSAGES[language]["feature_coming_soon"])
        send_main_menu(phone_number, language)

def handle_text_message(phone_number, text):
    """Handle text message responses"""
    session = user_sessions.get(phone_number, {})
    language = session.get('language', 'english')
    
    # New user - send language menu
    if not session and text.lower() in ["hi", "hello", "hey", "مرحبا", "اهلا", "السلام"]:
        send_language_menu(phone_number)
        return
    
    # Handle booking flow
    if session and session.get('step', '').startswith('awaiting_'):
        handle_booking_step(phone_number, text, language, session)
    else:
        # Fallback to main menu
        send_main_menu(phone_number, language)

# ==============================
# ENHANCED API ENDPOINTS
# ==============================

@app.route("/api/health", methods=["GET"])
def health_check():
    """Enhanced health check endpoint"""
    try:
        # Get today's stats
        today = datetime.now().strftime("%Y-%m-%d")
        today_bookings = 0
        today_revenue = 0
        
        if sheet:
            records = sheet.get_all_records()
            for record in records:
                if record.get('Cruise Date') == today and record.get('Booking Status') == 'Confirmed':
                    today_bookings += 1
                    today_revenue += float(record.get('Total Amount', 0))
        
        status = {
            "status": "Sindbad Ship Cruises WhatsApp API 🚢",
            "timestamp": datetime.now().isoformat(),
            "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
            "sheets_available": sheet is not None,
            "active_sessions": len(user_sessions),
            "today_bookings": today_bookings,
            "today_revenue": round(today_revenue, 3),
            "total_capacity": CRUISE_CONFIG["max_capacity"],
            "version": "5.0 - COMPREHENSIVE DEMO",
            "features": [
                "Multi-language booking flow",
                "Payment simulation (4 methods)",
                "Booking management",
                "Loyalty program",
                "Group discounts",
                "Special requests",
                "Email collection",
                "Capacity management",
                "Admin dashboard",
                "Reminder system"
            ]
        }
        return jsonify(status)
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/dashboard", methods=["GET"])
def admin_dashboard():
    """Admin dashboard endpoint"""
    try:
        if not sheet:
            return jsonify({"error": "Sheets not available"}), 500
        
        records = sheet.get_all_records()
        
        # Calculate various metrics
        total_bookings = len(records)
        confirmed_bookings = len([r for r in records if r.get('Booking Status') == 'Confirmed'])
        cancelled_bookings = len([r for r in records if r.get('Booking Status') == 'Cancelled'])
        total_revenue = sum(float(r.get('Total Amount', 0)) for r in records if r.get('Booking Status') == 'Confirmed')
        
        # Today's stats
        today = datetime.now().strftime("%Y-%m-%d")
        today_bookings = len([r for r in records if r.get('Cruise Date') == today and r.get('Booking Status') == 'Confirmed'])
        today_revenue = sum(float(r.get('Total Amount', 0)) for r in records if r.get('Cruise Date') == today and r.get('Booking Status') == 'Confirmed')
        
        # Popular cruise types
        cruise_counts = {}
        for record in records:
            if record.get('Booking Status') == 'Confirmed':
                cruise_type = record.get('Cruise Type')
                cruise_counts[cruise_type] = cruise_counts.get(cruise_type, 0) + 1
        
        dashboard_data = {
            "summary": {
                "total_bookings": total_bookings,
                "confirmed_bookings": confirmed_bookings,
                "cancelled_bookings": cancelled_bookings,
                "total_revenue": round(total_revenue, 3),
                "today_bookings": today_bookings,
                "today_revenue": round(today_revenue, 3)
            },
            "popular_cruises": cruise_counts,
            "recent_bookings": records[-5:] if records else []  # Last 5 bookings
        }
        
        return jsonify(dashboard_data)
        
    except Exception as e:
        logger.error(f"Admin dashboard error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/bookings", methods=["GET"])
def get_all_bookings():
    """Get all bookings with filtering"""
    try:
        if not sheet:
            return jsonify({"error": "Sheets not available"}), 500
        
        records = sheet.get_all_records()
        
        # Filter by status if provided
        status_filter = request.args.get('status')
        if status_filter:
            records = [r for r in records if r.get('Booking Status', '').lower() == status_filter.lower()]
        
        return jsonify(records)
    except Exception as e:
        logger.error(f"Error getting bookings: {str(e)}")
        return jsonify({"error": str(e)}), 500

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
    logger.info(f"💳 DEMO MODE: Comprehensive feature showcase")
    logger.info(f"📊 Features: Booking, Payments, Management, Loyalty, Admin")
    logger.info(f"🌐 Admin Dashboard: /api/admin/dashboard")
    logger.info(f"❤️  Health Check: /api/health")
    
    app.run(host="0.0.0.0", port=port, debug=False)