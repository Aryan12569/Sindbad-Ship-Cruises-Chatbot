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
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows="1000", cols="20")
        logger.info(f"✅ Created new worksheet: {SHEET_NAME}")
    
    # Setup headers
    required_headers = [
        'Timestamp', 'Booking ID', 'Customer Name', 'Phone Number', 'WhatsApp ID',
        'Cruise Date', 'Cruise Time', 'Cruise Type', 'Adults Count', 'Children Count', 
        'Infants Count', 'Total Guests', 'Total Amount', 'Payment Status', 
        'Payment Method', 'Transaction ID', 'Language', 'Booking Status', 'Notes'
    ]
    
    current_headers = sheet.row_values(1)
    if not current_headers or current_headers != required_headers:
        if current_headers:
            sheet.clear()
        sheet.append_row(required_headers)
        logger.info("✅ Updated Google Sheets headers")
    
    # Test connection
    test_value = sheet.acell('A1').value
    logger.info(f"✅ Google Sheets connected successfully. First header: {test_value}")
    
except Exception as e:
    logger.error(f"❌ Google Sheets initialization failed: {str(e)}")
    sheet = None

# Session management
user_sessions = {}

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
    "reporting_time": "1 hour before cruise"
}

# ==============================
# MESSAGES
# ==============================
MESSAGES = {
    "english": {
        "welcome": "🌊 Welcome to Sindbad Ship Cruises!\n\nChoose your preferred language:",
        "main_menu": "🌊 *Sindbad Ship Cruises* 🚢\n\n*Cruise Features:*\n• 🛳️ Luxury sea cruise\n• ☕ Cafe on board\n• 🌅 Stunning sea views\n• 🎵 Music & entertainment\n\nPlease choose from the menu:",
        "booking_start": "📝 *Let's Book Your Cruise!* 🎫\n\nI'll help you book your sea cruise. 🚢\n\nFirst, please send me your:\n\n👤 *Full Name*\n\n*Example:*\nAhmed Al Harthy",
        "ask_phone": "Perfect, {}! 👋\n\nNow please send me your:\n\n📞 *Phone Number*\n\n*Example:*\n91234567",
        "ask_date": "📅 *Cruise Date*\n\nPlease send your *preferred date* for the cruise:\n\n📋 *Format Examples:*\n• **Tomorrow**\n• **October 29**\n• **Next Friday**\n• **15 November**\n• **2024-12-25**",
        "ask_adults": "👥 *Number of Adults*\n\nHow many *adults* (12 years and above) will be joining?\n\nPlease send the number:\n*Examples:* 2, 4, 6",
        "ask_children": "👶 *Number of Children*\n\nAdults: {}\n\nHow many *children* (2-11 years) will be joining?\n\nPlease send the number:\n*Examples:* 0, 1, 2",
        "ask_infants": "🍼 *Number of Infants*\n\nAdults: {}\nChildren: {}\n\nHow many *infants* (below 2 years) will be joining?\n\n*Note:* Infants are free\n\nPlease send the number:\n*Examples:* 0, 1, 2",
        "ask_cruise_type": "🕒 *Choose Cruise Type*\n\n{} total guests:\n• {} adults\n• {} children\n• {} infants\n\nPlease choose your cruise:",
        "payment_request": "💳 *Payment Required*\n\n*Total Amount: {} OMR*\n\nBooking ID: {}\n\nTo complete booking, please confirm payment:",
        "payment_simulation": "💳 *Payment Simulation - TEST MODE*\n\nSince this is a test bot, we'll simulate payment.\n\n*Total Amount: {} OMR*\nBooking ID: {}\n\nClick 'Simulate Payment' to complete booking:",
        "payment_confirmed": "🎉 *Booking Confirmed!* ✅\n\nThank you {}! Your cruise has been booked successfully. 🚢\n\n📋 *Booking Details:*\n🆔 Booking ID: {}\n👤 Name: {}\n📞 Phone: {}\n📅 Date: {}\n🕒 Time: {}\n🚢 Cruise Type: {}\n👥 Guests: {} total\n   • {} adults\n   • {} children\n   • {} infants\n💰 Amount: {} OMR\n💳 Payment: Simulated (Test Mode)\n\n⏰ *Reporting Time:* 1 hour before cruise\n📍 *Location:* {}\n📞 *For inquiries:* {} | {}\n\nWe wish you a wonderful cruise experience! 🌊",
        "booking_cancelled": "❌ Booking cancelled. We welcome you anytime! 🌊",
        "invalid_input": "❌ Invalid input. Please try again."
    },
    "arabic": {
        "welcome": "🌊 مرحباً بكم في رحلات السندباد البحرية!\n\nاختر لغتك المفضلة:",
        "main_menu": "🌊 *رحلات السندباد البحرية* 🚢\n\n*مميزات الرحلة:*\n• 🛳️ رحلة بحرية فاخرة\n• ☕ مقهى على متن السفينة\n• 🌅 مناظر بحرية خلابة\n• 🎵 موسيقى وترفيه\n\nاختر من القائمة:",
        "booking_start": "📝 *لنحجز رحلتك!* 🎫\n\nسأساعدك في حجز رحلتك البحرية. 🚢\n\nأولاً، الرجاء إرسال:\n\n👤 *الاسم الكامل*\n\n*مثال:*\nأحمد الحارثي",
        "ask_phone": "ممتاز، {}! 👋\n\nالآن الرجاء إرسال:\n\n📞 *رقم الهاتف*\n\n*مثال:*\n91234567",
        "ask_date": "📅 *تاريخ الرحلة*\n\nالرجاء إرسال *التاريخ المفضل* للرحلة:\n\n📋 *أمثلة على التنسيق:*\n• **غداً**\n• **29 أكتوبر**\n• **الجمعة القادمة**\n• **15 نوفمبر**\n• **2024-12-25**",
        "ask_adults": "👥 *عدد البالغين*\n\nكم عدد *البالغين* (12 سنة فما فوق) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 2, 4, 6",
        "ask_children": "👶 *عدد الأطفال*\n\nالبالغين: {}\n\nكم عدد *الأطفال* (2-11 سنة) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 0, 1, 2",
        "ask_infants": "🍼 *عدد الرضع*\n\nالبالغين: {}\nالأطفال: {}\n\nكم عدد *الرضع* (أقل من سنتين) الذين سينضمون؟\n\n*ملاحظة:* الرضع مجاناً\n\nالرجاء إرسال الرقم:\n*أمثلة:* 0, 1, 2",
        "ask_cruise_type": "🕒 *اختر نوع الرحلة*\n\n{} ضيوف إجمالاً:\n• {} بالغين\n• {} أطفال\n• {} رضع\n\nالرجاء اختيار الرحلة:",
        "payment_request": "💳 *طلب الدفع*\n\n*المبلغ الإجمالي: {} ريال عماني*\n\nرقم الحجز: {}\n\nلإكمال الحجز، الرجاء تأكيد الدفع:",
        "payment_simulation": "💳 *محاكاة الدفع - وضع الاختبار*\n\nنظراً لأن هذا بوت اختبار، سنقوم بمحاكاة الدفع.\n\n*المبلغ الإجمالي: {} ريال عماني*\nرقم الحجز: {}\n\nانقر 'محاكاة الدفع' لإكمال الحجز:",
        "payment_confirmed": "🎉 *تم تأكيد الحجز!* ✅\n\nشكراً {}! تم حجز رحلتك بنجاح. 🚢\n\n📋 *تفاصيل الحجز:*\n🆔 رقم الحجز: {}\n👤 الاسم: {}\n📞 الهاتف: {}\n📅 التاريخ: {}\n🕒 الوقت: {}\n🚢 نوع الرحلة: {}\n👥 الضيوف: {} إجمالاً\n   • {} بالغين\n   • {} أطفال\n   • {} رضع\n💰 المبلغ: {} ريال عماني\n💳 الدفع: محاكاة (وضع الاختبار)\n\n⏰ *وقت الحضور:* ساعة قبل الرحلة\n📍 *موقعنا:* {}\n📞 *للاستفسار:* {} | {}\n\nنتمنى لكم رحلة بحرية ممتعة! 🌊",
        "booking_cancelled": "❌ تم إلغاء الحجز. نرحب بك في أي وقت! 🌊",
        "invalid_input": "❌ إدخال غير صالح. يرجى المحاولة مرة أخرى."
    }
}

# ==============================
# HELPER FUNCTIONS
# ==============================

def generate_booking_id():
    """Generate unique booking ID"""
    return f"SDB{int(time.time())}"

def clean_phone_number(number):
    """Clean and validate phone numbers for WhatsApp API"""
    if not number:
        return None
    
    # Remove all non-digit characters
    clean_number = ''.join(filter(str.isdigit, str(number)))
    
    if not clean_number:
        return None
    
    # Remove any leading zeros
    clean_number = clean_number.lstrip('0')
    
    logger.info(f"🔍 Cleaning phone number: {number} -> {clean_number} (length: {len(clean_number)})")
    
    # Case 1: Already in correct format (968XXXXXXXXX)
    if len(clean_number) == 12 and clean_number.startswith('968'):
        logger.info(f"✅ Already in correct format: {clean_number}")
        return clean_number
    
    # Case 2: 8-digit Oman number (e.g., 78505509, 91234567)
    elif len(clean_number) == 8 and clean_number.startswith(('7', '9', '8')):
        formatted = '968' + clean_number
        logger.info(f"✅ Converted 8-digit Oman number: {clean_number} -> {formatted}")
        return formatted
    
    # Case 3: 9-digit number starting with 9
    elif len(clean_number) == 9 and clean_number.startswith('9'):
        formatted = '968' + clean_number
        logger.info(f"✅ Converted 9-digit number: {clean_number} -> {formatted}")
        return formatted
    
    # Case 4: Number already starts with 968 but has different length
    elif clean_number.startswith('968'):
        if len(clean_number) > 12:
            formatted = clean_number[:12]
            logger.info(f"✅ Trimmed long number: {clean_number} -> {formatted}")
            return formatted
        else:
            logger.info(f"✅ Using as-is with 968 prefix: {clean_number}")
            return clean_number
    
    # Case 5: Handle numbers that might have country code but wrong format
    elif len(clean_number) == 11 and clean_number.startswith('968'):
        if len(clean_number[3:]) == 8:
            formatted = '968' + clean_number[3:]
            logger.info(f"✅ Fixed 11-digit number: {clean_number} -> {formatted}")
            return formatted
    
    logger.warning(f"⚠️ Unrecognized phone format: {number} (cleaned: {clean_number}, length: {len(clean_number)})")
    
    # Final fallback: if it's a number that looks like it could work, try it
    if len(clean_number) >= 8 and len(clean_number) <= 15:
        logger.info(f"🔄 Using fallback for: {clean_number}")
        return clean_number
    
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
    """Calculate total amount for booking"""
    config = CRUISE_CONFIG["cruise_types"][cruise_type]
    total = (adults * config["price_adult"]) + (children * config["price_child"])
    return round(total, 3)

def send_whatsapp_message(to, message, interactive_data=None):
    """Send WhatsApp message via Meta API"""
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

def save_booking_to_sheets(booking_data, language, payment_status="Paid", payment_method="Simulated"):
    """Save booking to Google Sheets"""
    try:
        if not sheet:
            logger.error("❌ Google Sheets not available")
            return False
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            str(booking_data['adults_count']),
            str(booking_data['children_count']),
            str(booking_data['infants_count']),
            str(booking_data['total_guests']),
            str(booking_data['total_amount']),
            payment_status,
            payment_method,
            f"SIM_{int(time.time())}",
            language.title(),
            'Confirmed',
            'Via WhatsApp Bot - Test Mode'
        ]
        
        logger.info(f"💾 Saving to sheets: {booking_data['booking_id']}")
        sheet.append_row(row_data)
        logger.info(f"✅ Booking saved: {booking_data['booking_id']}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to save booking: {str(e)}")
        return False

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
        'created_at': datetime.now().isoformat(),
        'flow': 'booking'
    }
    message = MESSAGES[language]["booking_start"]
    return send_whatsapp_message(to, message)

def handle_booking_step(to, text, language, session):
    """Handle booking flow steps"""
    step = session.get('step')
    
    if step == 'awaiting_name':
        session.update({'step': 'awaiting_phone', 'name': text})
        message = MESSAGES[language]["ask_phone"].format(text)
        return send_whatsapp_message(to, message)
    
    elif step == 'awaiting_phone':
        # Clean and validate phone number
        clean_phone = clean_phone_number(text)
        
        if not clean_phone:
            if language == "arabic":
                error_msg = "❌ رقم الهاتف غير صالح. يرجى إدخال رقم هاتف عماني صالح (مثال: 78505509 أو 91234567)"
            else:
                error_msg = "❌ Invalid phone number. Please enter a valid Omani phone number (e.g., 78505509 or 91234567)"
            return send_whatsapp_message(to, error_msg)
        
        session.update({
            'step': 'awaiting_date', 
            'phone': text,
            'whatsapp_id': clean_phone
        })
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
            session.update({'infants_count': int(text)})
            return send_cruise_type_menu(to, language, session)
        else:
            return send_whatsapp_message(to, MESSAGES[language]["invalid_input"])
    
    return False

def send_cruise_type_menu(to, language, session):
    """Send cruise type selection menu"""
    adults = session['adults_count']
    children = session['children_count']
    infants = session['infants_count']
    total_guests = adults + children + infants
    date = session['cruise_date']
    
    # Check capacity
    available_cruises = []
    for cruise_key, cruise_info in CRUISE_CONFIG["cruise_types"].items():
        current_capacity = get_cruise_capacity(date, cruise_info["name_en"])
        available_seats = CRUISE_CONFIG["max_capacity"] - current_capacity
        
        if available_seats >= total_guests:
            available_cruises.append((cruise_key, cruise_info, available_seats))
    
    if not available_cruises:
        if language == "arabic":
            message = f"❌ عذراً، لا توجد أماكن متاحة بتاريخ {date}.\nيرجى اختيار تاريخ آخر."
        else:
            message = f"❌ Sorry, no available seats on {date}.\nPlease choose another date."
        send_whatsapp_message(to, message)
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

def request_payment(to, session):
    """Request payment with SIMULATION"""
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
        'total_amount': total_amount
    }
    
    session['booking_data'] = booking_data
    session['step'] = 'awaiting_payment'
    
    if language == "arabic":
        message = MESSAGES["arabic"]["payment_simulation"].format(total_amount, booking_id)
        interactive_data = {
            "type": "button",
            "body": {"text": message},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "simulate_payment", "title": "💳 محاكاة الدفع"}},
                    {"type": "reply", "reply": {"id": "cancel_booking", "title": "❌ إلغاء الحجز"}}
                ]
            }
        }
    else:
        message = MESSAGES["english"]["payment_simulation"].format(total_amount, booking_id)
        interactive_data = {
            "type": "button",
            "body": {"text": message},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "simulate_payment", "title": "💳 Simulate Payment"}},
                    {"type": "reply", "reply": {"id": "cancel_booking", "title": "❌ Cancel Booking"}}
                ]
            }
        }
    
    return send_whatsapp_message(to, "", interactive_data)

def confirm_booking(to, session):
    """Confirm and save booking after SIMULATED payment"""
    language = session['language']
    booking_data = session['booking_data']
    contact = CRUISE_CONFIG["contact"]
    cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
    
    # Save to Google Sheets with SIMULATED payment
    if not save_booking_to_sheets(booking_data, language, "Paid", "Simulated Payment"):
        error_msg = "Failed to save booking. Please contact support." if language == "english" else "فشل في حفظ الحجز. يرجى الاتصال بالدعم."
        send_whatsapp_message(to, error_msg)
        return False
    
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

# ==============================
# DASHBOARD API ENDPOINTS
# ==============================

@app.route("/api/active_sessions", methods=["GET"])
def get_active_sessions():
    """Get active user sessions"""
    try:
        # Clean up old sessions (older than 1 hour)
        current_time = datetime.now()
        expired_sessions = []
        
        for phone, session in user_sessions.items():
            created_at = datetime.fromisoformat(session.get('created_at', current_time.isoformat()))
            if (current_time - created_at) > timedelta(hours=1):
                expired_sessions.append(phone)
        
        for phone in expired_sessions:
            del user_sessions[phone]
        
        return jsonify({"sessions": user_sessions})
    except Exception as e:
        logger.error(f"Error getting sessions: {str(e)}")
        return jsonify({"sessions": {}})

@app.route("/api/user_session/<phone_number>", methods=["GET"])
def get_user_session(phone_number):
    """Get specific user session"""
    try:
        session = user_sessions.get(phone_number, {})
        return jsonify({
            "has_session": phone_number in user_sessions,
            "step": session.get('step', 'no_session'),
            "flow": session.get('flow', 'no_flow'),
            "name": session.get('name', 'Unknown'),
            "tour_type": session.get('cruise_type', 'Not selected')
        })
    except Exception as e:
        logger.error(f"Error getting user session: {str(e)}")
        return jsonify({"has_session": False})

@app.route("/api/capacity/<date>/<cruise_type>", methods=["GET"])
def get_capacity_for_date(date, cruise_type):
    """Get capacity for specific date and cruise type"""
    try:
        current_capacity = get_cruise_capacity(date, cruise_type)
        available_seats = CRUISE_CONFIG["max_capacity"] - current_capacity
        
        return jsonify({
            "date": date,
            "cruise_type": cruise_type,
            "current_capacity": current_capacity,
            "available_seats": available_seats,
            "max_capacity": CRUISE_CONFIG["max_capacity"],
            "utilization_percentage": round((current_capacity / CRUISE_CONFIG["max_capacity"]) * 100, 2)
        })
    except Exception as e:
        logger.error(f"Error getting capacity: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/report/<date>", methods=["GET"])
def generate_daily_report(date):
    """Generate CSV report for specific date"""
    try:
        if not sheet:
            return jsonify({"error": "Google Sheets not available"}), 500
        
        records = sheet.get_all_records()
        
        # Filter bookings for the specific date
        daily_bookings = []
        for record in records:
            if str(record.get('Cruise Date', '')).strip() == date:
                daily_bookings.append(record)
        
        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['Sindbad Ship Cruises - Daily Report'])
        writer.writerow([f'Date: {date}'])
        writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        writer.writerow([])
        
        # Write summary
        total_bookings = len(daily_bookings)
        confirmed_bookings = len([b for b in daily_bookings if b.get('Booking Status') == 'Confirmed'])
        total_revenue = sum(float(b.get('Total Amount', 0)) for b in daily_bookings if b.get('Booking Status') == 'Confirmed')
        
        writer.writerow(['Summary'])
        writer.writerow(['Total Bookings', total_bookings])
        writer.writerow(['Confirmed Bookings', confirmed_bookings])
        writer.writerow(['Total Revenue', f"{total_revenue:.3f} OMR"])
        writer.writerow([])
        
        # Write detailed data
        if daily_bookings:
            headers = daily_bookings[0].keys()
            writer.writerow(headers)
            for booking in daily_bookings:
                writer.writerow([booking.get(header, '') for header in headers])
        else:
            writer.writerow(['No bookings found for this date'])
        
        # Prepare response
        output.seek(0)
        response = app.response_class(
            response=output.getvalue(),
            status=200,
            mimetype='text/csv'
        )
        response.headers.set('Content-Disposition', 'attachment', filename=f'Sindbad_Report_{date}.csv')
        return response
        
    except Exception as e:
        logger.error(f"Error generating report: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/broadcast", methods=["POST"])
def send_broadcast():
    """Send broadcast message to segment"""
    try:
        data = request.get_json()
        segment = data.get('segment', 'all')
        message = data.get('message', '')
        
        if not message:
            return jsonify({"error": "Message is required"}), 400
        
        if not sheet:
            return jsonify({"error": "Google Sheets not available"}), 500
        
        records = sheet.get_all_records()
        
        # Filter recipients based on segment
        recipients = []
        for record in records:
            if segment == 'all':
                recipients.append(record.get('WhatsApp ID'))
            elif segment == 'book_tour' and record.get('Booking Status') == 'Confirmed':
                recipients.append(record.get('WhatsApp ID'))
            elif segment == 'pending' and record.get('Booking Status') == 'Pending':
                recipients.append(record.get('WhatsApp ID'))
        
        # Remove duplicates and None values
        recipients = list(set([r for r in recipients if r]))
        
        # In a real implementation, you would send messages via WhatsApp API
        # For now, we'll simulate the broadcast
        sent_count = 0
        failed_count = 0
        
        for recipient in recipients:
            try:
                # Simulate sending message
                logger.info(f"📤 Broadcast to {recipient}: {message[:50]}...")
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send to {recipient}: {str(e)}")
                failed_count += 1
        
        return jsonify({
            "success": True,
            "sent": sent_count,
            "failed": failed_count,
            "total_recipients": len(recipients),
            "message": f"Broadcast completed: {sent_count} sent, {failed_count} failed"
        })
        
    except Exception as e:
        logger.error(f"Error in broadcast: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ==============================
# EXISTING WEBHOOK HANDLERS
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
    """Handle interactive message responses"""
    session = user_sessions.get(phone_number, {})
    language = session.get('language', 'english')
    
    logger.info(f"🔄 Handling interaction: {interaction_id} for {phone_number}")
    
    # Language selection
    if interaction_id == "lang_english":
        user_sessions[phone_number] = {'language': 'english', 'flow': 'main_menu'}
        send_main_menu(phone_number, 'english')
    
    elif interaction_id == "lang_arabic":
        user_sessions[phone_number] = {'language': 'arabic', 'flow': 'main_menu'}
        send_main_menu(phone_number, 'arabic')
    
    # Main menu
    elif interaction_id == "book_cruise":
        start_booking(phone_number, language)
    
    elif interaction_id == "pricing":
        if language == "arabic":
            message = "💰 *أسعار الرحلات*\n\n*الصباح:* 2.500 ريال للشخص\n(9:00 صباحاً - 10:30 صباحاً)\n\n*الظهيرة:* 3.500 ريال للشخص\n(1:30 ظهراً - 3:00 عصراً)\n\n*الغروب:* 4.500 ريال للشخص\n(5:00 عصراً - 6:30 مساءً)\n\n*المساء:* 3.500 ريال للشخص\n(7:30 مساءً - 9:00 مساءً)\n\n*الرضع:* مجاناً (أقل من سنتين)"
        else:
            message = "💰 *Cruise Pricing*\n\n*Morning:* 2.500 OMR per person\n(9:00 AM - 10:30 AM)\n\n*Afternoon:* 3.500 OMR per person\n(1:30 PM - 3:00 PM)\n\n*Sunset:* 4.500 OMR per person\n(5:00 PM - 6:30 PM)\n\n*Evening:* 3.500 OMR per person\n(7:30 PM - 9:00 PM)\n\n*Infants:* Free (below 2 years)"
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    elif interaction_id == "schedule":
        if language == "arabic":
            message = "🕒 *جدول الرحلات*\n\n*الصباح:* 9:00 صباحاً - 10:30 صباحاً\n*الظهيرة:* 1:30 ظهراً - 3:00 عصراً\n*الغروب:* 5:00 عصراً - 6:30 مساءً\n*المساء:* 7:30 مساءً - 9:00 مساءً\n\n⏰ *وقت الحضور:* ساعة قبل الرحلة"
        else:
            message = "🕒 *Cruise Schedule*\n\n*Morning:* 9:00 AM - 10:30 AM\n*Afternoon:* 1:30 PM - 3:00 PM\n*Sunset:* 5:00 PM - 6:30 PM\n*Evening:* 7:30 PM - 9:00 PM\n\n⏰ *Reporting Time:* 1 hour before cruise"
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    elif interaction_id == "contact":
        contact = CRUISE_CONFIG["contact"]
        if language == "arabic":
            message = f"📞 *معلومات الاتصال*\n\n*هاتف:* {contact['phone1']} | {contact['phone2']}\n*موقع:* {contact['location']}\n*بريد:* {contact['email']}\n*موقع:* {contact['website']}\n\n⏰ *ساعات العمل:* 8:00 صباحاً - 10:00 مساءً"
        else:
            message = f"📞 *Contact Information*\n\n*Phone:* {contact['phone1']} | {contact['phone2']}\n*Location:* {contact['location']}\n*Email:* {contact['email']}\n*Website:* {contact['website']}\n\n⏰ *Working Hours:* 8:00 AM - 10:00 PM"
        
        send_whatsapp_message(phone_number, message)
        send_main_menu(phone_number, language)
    
    # Cruise type selection
    elif interaction_id.startswith("cruise_"):
        cruise_type = interaction_id.replace("cruise_", "")
        if phone_number in user_sessions:
            user_sessions[phone_number]['cruise_type'] = cruise_type
            request_payment(phone_number, user_sessions[phone_number])
    
    # Payment simulation
    elif interaction_id == "simulate_payment":
        if phone_number in user_sessions:
            confirm_booking(phone_number, user_sessions[phone_number])
    
    elif interaction_id == "cancel_booking":
        cancel_booking(phone_number, language)

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
# EXISTING API ENDPOINTS
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
        "version": "4.0 - SIMULATION MODE",
        "payment_mode": "SIMULATION - Test payments only"
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
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            test_id,
            "Test User",
            "91234567",
            "96812345678",
            "2024-12-31",
            "9:00 AM - 10:30 AM",
            "Morning Cruise",
            "2", "1", "0", "3", "7.500",
            'Paid', 'Simulated', 'TEST_123', 'English', 'Confirmed', 'Test Record'
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
    logger.info(f"💳 PAYMENT MODE: SIMULATION")
    logger.info(f"📊 Google Sheets: {'Connected' if sheet else 'Not Available'}")
    
    app.run(host="0.0.0.0", port=port, debug=False)