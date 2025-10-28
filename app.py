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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ==============================
# CONFIGURATION - SINDABAD SHIP CRUISES
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
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")

# Google Sheets setup
sheet = None
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # Try to open the specific worksheet, create if it doesn't exist
    try:
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        sheet = spreadsheet.worksheet(SHEET_NAME)
        logger.info(f"✅ Found existing worksheet: {SHEET_NAME}")
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"📝 Worksheet '{SHEET_NAME}' not found, creating new one...")
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows="1000", cols="20")
        logger.info(f"✅ Created new worksheet: {SHEET_NAME}")
    except Exception as e:
        logger.error(f"❌ Error accessing worksheet: {str(e)}")
        sheet = None
    
    # Ensure the sheet has the right columns
    if sheet:
        try:
            current_headers = sheet.row_values(1)
            required_headers = [
                'Timestamp', 'Booking ID', 'Customer Name', 'Phone Number', 'WhatsApp ID',
                'Cruise Date', 'Cruise Time', 'Cruise Type', 'Adults Count', 'Children Count', 
                'Infants Count', 'Total Guests', 'Total Amount', 'Payment Status', 
                'Payment Method', 'Transaction ID', 'Language', 'Booking Status', 'Notes'
            ]
            
            if not current_headers or current_headers != required_headers:
                if current_headers:
                    sheet.clear()
                sheet.append_row(required_headers)
                logger.info("✅ Updated Google Sheets headers")
        except Exception as e:
            logger.error(f"❌ Error setting up headers: {str(e)}")
    
    logger.info("✅ Google Sheets initialized successfully")
    
except Exception as e:
    logger.error(f"❌ Google Sheets initialization failed: {str(e)}")
    sheet = None

# Simple session management
booking_sessions = {}
payment_sessions = {}

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
# ARABIC LANGUAGE SUPPORT
# ==============================
ARABIC_MESSAGES = {
    "welcome": "🌊 مرحباً بكم في رحلات السندباد البحرية!\n\nاختر لغتك المفضلة / Choose your preferred language:",
    
    "main_menu": "🌊 *رحلات السندباد البحرية* 🚢\n\n*مميزات الرحلة:*\n• 🛳️ رحلة بحرية فاخرة\n• ☕ مقهى على متن السفينة\n• 🌅 مناظر بحرية خلابة\n• 🎵 موسيقى وترفيه\n\n*معلومات الاتصال:*\n📞 {} | {}\n📍 {}\n📧 {}\n🌐 {}\n\nاختر من القائمة:",
    
    "booking_start": "📝 *لنحجز رحلتك!* 🎫\n\nسأساعدك في حجز رحلتك البحرية. 🚢\n\nأولاً، الرجاء إرسال:\n\n👤 *الاسم الكامل*\n\n*مثال:*\nأحمد الحارثي",
    
    "ask_phone": "ممتاز، {}! 👋\n\nالآن الرجاء إرسال:\n\n📞 *رقم الهاتف*\n\n*مثال:*\n91234567",
    
    "ask_date": "📅 *تاريخ الرحلة*\n\nالرجاء إرسال *التاريخ المفضل* للرحلة:\n\n📋 *أمثلة على التنسيق:*\n• **غداً**\n• **29 أكتوبر**\n• **الجمعة القادمة**\n• **15 نوفمبر**\n• **2024-12-25**",
    
    "ask_adults": "👥 *عدد البالغين*\n\nكم عدد *البالغين* (12 سنة فما فوق) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 2, 4, 6",
    
    "ask_children": "👶 *عدد الأطفال*\n\nالبالغين: {}\n\nكم عدد *الأطفال* (2-11 سنة) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 0, 1, 2",
    
    "ask_infants": "🍼 *عدد الرضع*\n\nالبالغين: {}\nالأطفال: {}\n\nكم عدد *الرضع* (أقل من سنتين) الذين سينضمون؟\n\n*ملاحظة:* الرضع مجاناً\n\nالرجاء إرسال الرقم:\n*أمثلة:* 0, 1, 2",
    
    "ask_cruise_type": "🕒 *نوع الرحلة*\n\n{} ضيوف إجمالاً:\n• {} بالغين\n• {} أطفال\n• {} رضع\n\nالرجاء اختيار نوع الرحلة:",
    
    "payment_instructions": "💳 *تعليمات الدفع*\n\n*المبلغ الإجمالي: {} ريال عماني*\n\nلإكمال الحجز، يرجى الدفع عبر:\n\n1. افتح تطبيق WhatsApp\n2. اضغط على أيقونة الدفع 💳\n3. اختر الدفع عبر WhatsApp\n4. أدخل المبلغ: {}\n5. أكمل عملية الدفع\n\nبعد الدفع، ستصلك تأكيدية الحجز تلقائياً.",
    
    "booking_complete": "🎉 *تم تأكيد الحجز!* ✅\n\nشكراً {}! تم حجز رحلتك بنجاح. 🚢\n\n📋 *تفاصيل الحجز:*\n🆔 رقم الحجز: {}\n👤 الاسم: {}\n📞 الهاتف: {}\n📅 التاريخ: {}\n🕒 الوقت: {}\n🚢 نوع الرحلة: {}\n👥 الضيوف: {} إجمالاً\n   • {} بالغين\n   • {} أطفال\n   • {} رضع\n💰 المبلغ: {} ريال عماني\n\n⏰ *وقت الحضور:* ساعة قبل الرحلة\n📍 *موقعنا:* {}\n📞 *للاستفسار:* {} | {}\n\nنتمنى لكم رحلة بحرية ممتعة! 🌊",
    
    "capacity_full": "❌ *عفواً، لا توجد أماكن متاحة*\n\nرحلة {} بتاريخ {} ممتلئة بالكامل ({} شخص).\n\nيرجى اختيار تاريخ آخر أو نوع رحلة مختلف."
}

# ==============================
# HELPER FUNCTIONS
# ==============================

def generate_booking_id():
    """Generate unique booking ID"""
    return f"SDB{int(time.time())}"

def clean_oman_number(number):
    """Clean and validate Oman phone numbers for WhatsApp API"""
    if not number:
        return None
    
    # Remove all non-digit characters and any leading zeros
    clean_number = ''.join(filter(str.isdigit, str(number)))
    
    if not clean_number:
        return None
    
    # Remove any leading zeros
    clean_number = clean_number.lstrip('0')
    
    # Handle Oman numbers specifically for WhatsApp API
    # WhatsApp requires international format without + or 00
    if len(clean_number) == 8 and clean_number.startswith(('9', '7', '8')):
        # For 8-digit Oman numbers, add country code (968)
        return '968' + clean_number
    elif len(clean_number) == 9 and clean_number.startswith('9'):
        # For 9-digit numbers starting with 9
        return '968' + clean_number
    elif len(clean_number) == 12 and clean_number.startswith('968'):
        # Already in correct format
        return clean_number
    elif len(clean_number) == 11 and clean_number.startswith('968'):
        # Already in correct format
        return clean_number
    elif len(clean_number) == 10 and clean_number.startswith('79'):
        # Handle numbers like 79XXXXXXX
        return '968' + clean_number[1:]
    elif len(clean_number) == 10 and clean_number.startswith('9'):
        # Handle 10-digit numbers starting with 9
        return '968' + clean_number
    
    logger.warning(f"⚠️ Unrecognized phone number format: {number} (cleaned: {clean_number})")
    return None

def get_cruise_capacity(cruise_date, cruise_type):
    """Get current capacity for a specific cruise"""
    try:
        if not sheet:
            return 0
            
        all_records = sheet.get_all_records()
        total_guests = 0
        
        for record in all_records:
            if (record.get('Cruise Date') == cruise_date and 
                record.get('Cruise Type') == cruise_type and
                record.get('Booking Status') != 'Cancelled'):
                total_guests += int(record.get('Total Guests', 0))
        
        return total_guests
    except Exception as e:
        logger.error(f"Error getting cruise capacity: {str(e)}")
        return 0

def calculate_total_amount(cruise_type, adults, children, infants):
    """Calculate total amount for booking"""
    config = CRUISE_CONFIG["cruise_types"][cruise_type]
    total = (adults * config["price_adult"]) + (children * config["price_child"])
    return round(total, 3)

def send_whatsapp_message(to, message, interactive_data=None):
    """Send WhatsApp message via Meta API"""
    try:
        clean_to = clean_oman_number(to)
        if not clean_to:
            logger.error(f"❌ Invalid phone number format: {to}")
            return False
        
        # WhatsApp Business API URL
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

        logger.info(f"📤 Sending WhatsApp message to {clean_to}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200:
            logger.info(f"✅ WhatsApp message sent successfully to {clean_to}")
            return True
        else:
            error_message = response_data.get('error', {}).get('message', 'Unknown error')
            error_code = response_data.get('error', {}).get('code', 'Unknown code')
            logger.error(f"❌ WhatsApp API error {response.status_code} (Code: {error_code}): {error_message}")
            
            # Log the full error details for debugging
            logger.error(f"🔍 Full error details: {response_data}")
            
            return False
        
    except Exception as e:
        logger.error(f"🚨 Failed to send WhatsApp message: {str(e)}")
        return False

def send_language_selection(to):
    """Send language selection menu"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🌊 Sindbad Ship Cruises"
        },
        "body": {
            "text": ARABIC_MESSAGES["welcome"]
        },
        "action": {
            "button": "🌐 Select Language",
            "sections": [
                {
                    "title": "Choose Language / اختر اللغة",
                    "rows": [
                        {
                            "id": "lang_english",
                            "title": "🇺🇸 English",
                            "description": "Continue in English"
                        },
                        {
                            "id": "lang_arabic", 
                            "title": "🇴🇲 العربية",
                            "description": "المتابعة باللغة العربية"
                        }
                    ]
                }
            ]
        }
    }
    
    return send_whatsapp_message(to, "", interactive_data)

def send_main_menu(to, language='english'):
    """Send main menu based on language"""
    contact = CRUISE_CONFIG["contact"]
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["main_menu"].format(
            contact["phone1"], contact["phone2"], 
            contact["location"], contact["email"], contact["website"]
        )
        
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "🌊 رحلات السندباد"
            },
            "body": {
                "text": "اختر من الخيارات:"
            },
            "action": {
                "button": "عرض الخيارات",
                "sections": [
                    {
                        "title": "الخدمات الرئيسية",
                        "rows": [
                            {
                                "id": "book_cruise_ar",
                                "title": "📅 حجز رحلة",
                                "description": "احجز رحلتك البحرية"
                            },
                            {
                                "id": "pricing_ar", 
                                "title": "💰 الأسعار",
                                "description": "أسعار الرحلات"
                            },
                            {
                                "id": "schedule_ar",
                                "title": "🕒 الجدول", 
                                "description": "مواعيد الرحلات"
                            },
                            {
                                "id": "contact_ar",
                                "title": "📞 اتصل بنا",
                                "description": "معلومات الاتصال"
                            }
                        ]
                    }
                ]
            }
        }
    else:
        message = f"""🌊 *Sindbad Ship Cruises* 🚢

*Cruise Features:*
• 🛳️ Luxury sea cruise
• ☕ Cafe on board  
• 🌅 Stunning sea views
• 🎵 Music & entertainment

*Contact Information:*
📞 {contact["phone1"]} | {contact["phone2"]}
📍 {contact["location"]}
📧 {contact["email"]}
🌐 {contact["website"]}

Please choose from the menu:"""
        
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "🌊 Sindbad Cruises"
            },
            "body": {
                "text": "Choose from options:"
            },
            "action": {
                "button": "View Options",
                "sections": [
                    {
                        "title": "Main Services",
                        "rows": [
                            {
                                "id": "book_cruise",
                                "title": "📅 Book Cruise",
                                "description": "Book your sea cruise"
                            },
                            {
                                "id": "pricing", 
                                "title": "💰 Pricing",
                                "description": "Cruise prices"
                            },
                            {
                                "id": "schedule",
                                "title": "🕒 Schedule", 
                                "description": "Cruise timings"
                            },
                            {
                                "id": "contact",
                                "title": "📞 Contact Us",
                                "description": "Contact information"
                            }
                        ]
                    }
                ]
            }
        }
    
    return send_whatsapp_message(to, message, interactive_data)

def start_booking_flow(to, language='english'):
    """Start the booking flow"""
    booking_sessions[to] = {
        'step': 'awaiting_name',
        'language': language,
        'created_at': datetime.now().isoformat()
    }
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["booking_start"]
    else:
        message = "📝 *Let's Book Your Cruise!* 🎫\n\nI'll help you book your sea cruise. 🚢\n\nFirst, please send me your:\n\n👤 *Full Name*\n\n*Example:*\nAhmed Al Harthy"
    
    return send_whatsapp_message(to, message)

def ask_for_phone(to, name, language='english'):
    """Ask for phone number"""
    booking_sessions[to].update({
        'step': 'awaiting_phone',
        'name': name
    })
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_phone"].format(name)
    else:
        message = f"Perfect, {name}! 👋\n\nNow please send me your:\n\n📞 *Phone Number*\n\n*Example:*\n91234567"
    
    return send_whatsapp_message(to, message)

def ask_for_date(to, name, phone, language='english'):
    """Ask for cruise date"""
    booking_sessions[to].update({
        'step': 'awaiting_date',
        'name': name,
        'phone': phone
    })
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_date"]
    else:
        message = "📅 *Cruise Date*\n\nPlease send your *preferred date* for the cruise:\n\n📋 *Format Examples:*\n• **Tomorrow**\n• **October 29**\n• **Next Friday**\n• **15 November**\n• **2024-12-25**"
    
    return send_whatsapp_message(to, message)

def ask_for_adults(to, name, phone, cruise_date, language='english'):
    """Ask for number of adults"""
    booking_sessions[to].update({
        'step': 'awaiting_adults',
        'name': name,
        'phone': phone,
        'cruise_date': cruise_date
    })
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_adults"]
    else:
        message = "👥 *Number of Adults*\n\nHow many *adults* (12 years and above) will be joining?\n\nPlease send the number:\n*Examples:* 2, 4, 6"
    
    return send_whatsapp_message(to, message)

def ask_for_children(to, name, phone, cruise_date, adults_count, language='english'):
    """Ask for number of children"""
    booking_sessions[to].update({
        'step': 'awaiting_children',
        'name': name,
        'phone': phone,
        'cruise_date': cruise_date,
        'adults_count': adults_count
    })
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_children"].format(adults_count)
    else:
        message = f"👶 *Number of Children*\n\nAdults: {adults_count}\n\nHow many *children* (2-11 years) will be joining?\n\nPlease send the number:\n*Examples:* 0, 1, 2"
    
    return send_whatsapp_message(to, message)

def ask_for_infants(to, name, phone, cruise_date, adults_count, children_count, language='english'):
    """Ask for number of infants"""
    booking_sessions[to].update({
        'step': 'awaiting_infants',
        'name': name,
        'phone': phone,
        'cruise_date': cruise_date,
        'adults_count': adults_count,
        'children_count': children_count
    })
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_infants"].format(adults_count, children_count)
    else:
        message = f"🍼 *Number of Infants*\n\nAdults: {adults_count}\nChildren: {children_count}\n\nHow many *infants* (below 2 years) will be joining?\n\n*Note:* Infants are free\n\nPlease send the number:\n*Examples:* 0, 1, 2"
    
    return send_whatsapp_message(to, message)

def ask_for_cruise_type(to, name, phone, cruise_date, adults_count, children_count, infants_count, language='english'):
    """Ask for cruise type with capacity check"""
    total_guests = int(adults_count) + int(children_count) + int(infants_count)
    
    booking_sessions[to].update({
        'step': 'awaiting_cruise_type',
        'name': name,
        'phone': phone,
        'cruise_date': cruise_date,
        'adults_count': adults_count,
        'children_count': children_count,
        'infants_count': infants_count,
        'total_guests': total_guests
    })
    
    # Check capacity for each cruise type
    available_cruises = []
    for cruise_key, cruise_info in CRUISE_CONFIG["cruise_types"].items():
        current_capacity = get_cruise_capacity(cruise_date, cruise_info["name_en"])
        available_seats = CRUISE_CONFIG["max_capacity"] - current_capacity
        
        if available_seats >= total_guests:
            available_cruises.append((cruise_key, cruise_info, available_seats))
    
    if not available_cruises:
        # No available cruises
        if language == 'arabic':
            message = f"❌ *عفواً، لا توجد أماكن متاحة*\n\nجميع الرحلات بتاريخ {cruise_date} ممتلئة بالكامل.\n\nيرجى اختيار تاريخ آخر."
        else:
            message = f"❌ *Sorry, no available seats*\n\nAll cruises on {cruise_date} are fully booked.\n\nPlease choose another date."
        
        send_whatsapp_message(to, message)
        # Restart booking flow
        start_booking_flow(to, language)
        return False
    
    if language == 'arabic':
        body_text = ARABIC_MESSAGES["ask_cruise_type"].format(total_guests, adults_count, children_count, infants_count)
        
        rows = []
        for cruise_key, cruise_info, available_seats in available_cruises:
            rows.append({
                "id": f"cruise_{cruise_key}",
                "title": f"🕒 {cruise_info['name_ar']}",
                "description": f"{cruise_info['time_ar']} - {available_seats} مقعد"
            })
        
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "اختر نوع الرحلة"
            },
            "body": {
                "text": body_text
            },
            "action": {
                "button": "اختر الرحلة",
                "sections": [{
                    "title": "الرحلات المتاحة",
                    "rows": rows
                }]
            }
        }
    else:
        body_text = f"📊 *Booking Summary*\n\nTotal Guests: {total_guests}\n• {adults_count} adults\n• {children_count} children\n• {infants_count} infants\n\nPlease choose your cruise type:"
        
        rows = []
        for cruise_key, cruise_info, available_seats in available_cruises:
            rows.append({
                "id": f"cruise_{cruise_key}",
                "title": f"🕒 {cruise_info['name_en']}",
                "description": f"{cruise_info['time']} - {available_seats} seats"
            })
        
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "Choose Cruise Type"
            },
            "body": {
                "text": body_text
            },
            "action": {
                "button": "Select Cruise",
                "sections": [{
                    "title": "Available Cruises",
                    "rows": rows
                }]
            }
        }
    
    return send_whatsapp_message(to, "", interactive_data)

def request_payment(to, booking_data, language='english'):
    """Request payment via WhatsApp Business"""
    cruise_type = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
    total_amount = calculate_total_amount(
        booking_data['cruise_type'],
        int(booking_data['adults_count']),
        int(booking_data['children_count']),
        int(booking_data['infants_count'])
    )
    
    # Store payment session
    payment_sessions[to] = {
        **booking_data,
        'total_amount': total_amount,
        'booking_id': generate_booking_id(),
        'created_at': datetime.now().isoformat()
    }
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["payment_instructions"].format(total_amount, total_amount)
    else:
        message = f"""💳 *Payment Instructions*

*Total Amount: {total_amount} OMR*

To complete your booking, please pay via:

1. Open WhatsApp
2. Tap the payment icon 💳  
3. Choose WhatsApp Pay
4. Enter amount: {total_amount}
5. Complete payment

After payment, you'll receive booking confirmation automatically."""

    # For now, we'll simulate payment completion
    # In production, you'd integrate with WhatsApp Business Payment API
    return complete_booking(to, language)

def complete_booking(to, language='english'):
    """Complete booking and save to sheet"""
    if to not in payment_sessions:
        return False
    
    booking_data = payment_sessions[to]
    
    # Save to Google Sheets
    try:
        if not sheet:
            logger.error("❌ Cannot save booking - Google Sheets not available")
            return False
            
        timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
        
        row_data = [
            timestamp,
            booking_data['booking_id'],
            booking_data['name'],
            booking_data['phone'],
            to,
            booking_data['cruise_date'],
            cruise_info['time'],
            cruise_info['name_en'],
            booking_data['adults_count'],
            booking_data['children_count'], 
            booking_data['infants_count'],
            booking_data['total_guests'],
            booking_data['total_amount'],
            'Paid',  # Payment Status
            'WhatsApp Pay',  # Payment Method
            f"WA_{int(time.time())}",  # Transaction ID
            language.title(),
            'Confirmed',
            'Auto-generated via WhatsApp Bot'
        ]
        
        sheet.append_row(row_data)
        logger.info(f"✅ Booking saved: {booking_data['booking_id']}")
        
    except Exception as e:
        logger.error(f"❌ Failed to save booking: {str(e)}")
        return False
    
    # Send confirmation message
    contact = CRUISE_CONFIG["contact"]
    cruise_info = CRUISE_CONFIG["cruise_types"][booking_data['cruise_type']]
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["booking_complete"].format(
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
        message = f"""🎉 *Booking Confirmed!* ✅

Thank you {booking_data['name']}! Your cruise has been booked successfully. 🚢

📋 *Booking Details:*
🆔 Booking ID: {booking_data['booking_id']}
👤 Name: {booking_data['name']}
📞 Phone: {booking_data['phone']}
📅 Date: {booking_data['cruise_date']}
🕒 Time: {cruise_info['time']}
🚢 Cruise Type: {cruise_info['name_en']}
👥 Guests: {booking_data['total_guests']} total
   • {booking_data['adults_count']} adults
   • {booking_data['children_count']} children  
   • {booking_data['infants_count']} infants
💰 Amount: {booking_data['total_amount']} OMR

⏰ *Reporting Time:* 1 hour before cruise
📍 *Location:* {contact['location']}
📞 *For inquiries:* {contact['phone1']} | {contact['phone2']}

We wish you a wonderful cruise experience! 🌊"""
    
    success = send_whatsapp_message(to, message)
    
    # Clear sessions
    if to in booking_sessions:
        del booking_sessions[to]
    if to in payment_sessions:
        del payment_sessions[to]
    
    return success

def handle_interaction(interaction_id, phone_number):
    """Handle list interactions"""
    language = get_user_language(phone_number)
    
    # Language selection
    if interaction_id == "lang_english":
        booking_sessions[phone_number] = {'language': 'english'}
        return send_main_menu(phone_number, 'english')
    elif interaction_id == "lang_arabic":
        booking_sessions[phone_number] = {'language': 'arabic'}  
        return send_main_menu(phone_number, 'arabic')
    
    # Main menu interactions
    if interaction_id == "book_cruise" or interaction_id == "book_cruise_ar":
        return start_booking_flow(phone_number, language)
    
    elif interaction_id.startswith("cruise_"):
        cruise_type = interaction_id.replace("cruise_", "")
        if phone_number in booking_sessions:
            booking_data = booking_sessions[phone_number]
            booking_data['cruise_type'] = cruise_type
            booking_data['step'] = 'payment_pending'
            return request_payment(phone_number, booking_data, language)
        return False
    
    # Info menu interactions
    elif interaction_id in ["pricing", "pricing_ar"]:
        if language == 'arabic':
            message = """💰 *أسعار الرحلات*

*رحلات الصباح:* 2.500 ريال للشخص
(9:00 صباحاً - 10:30 صباحاً)

*رحلات الظهيرة:* 3.500 ريال للشخص  
(1:30 ظهراً - 3:00 عصراً)

*رحلات الغروب:* 4.500 ريال للشخص
(5:00 عصراً - 6:30 مساءً)

*رحلات المساء:* 3.500 ريال للشخص
(7:30 مساءً - 9:00 مساءً)

*ملاحظة:* الرضع تحت سنتين مجاناً"""
        else:
            message = """💰 *Cruise Pricing*

*Morning Cruise:* 2.500 OMR per person
(9:00 AM - 10:30 AM)

*Afternoon Cruise:* 3.500 OMR per person  
(1:30 PM - 3:00 PM) 

*Sunset Cruise:* 4.500 OMR per person
(5:00 PM - 6:30 PM)

*Evening Cruise:* 3.500 OMR per person
(7:30 PM - 9:00 PM)

*Note:* Infants below 2 years are free"""
        
        return send_whatsapp_message(phone_number, message)
    
    elif interaction_id in ["schedule", "schedule_ar"]:
        if language == 'arabic':
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
        
        return send_whatsapp_message(phone_number, message)
    
    elif interaction_id in ["contact", "contact_ar"]:
        contact = CRUISE_CONFIG["contact"]
        if language == 'arabic':
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
        
        return send_whatsapp_message(phone_number, message)
    
    return False

def get_user_language(phone_number):
    """Get user's preferred language"""
    session = booking_sessions.get(phone_number, {})
    return session.get('language', 'english')

# ==============================
# DASHBOARD API ENDPOINTS  
# ==============================

@app.route("/api/bookings", methods=["GET"])
def get_bookings():
    """Get all bookings for dashboard"""
    try:
        if not sheet:
            return jsonify({"error": "Google Sheets not configured"}), 500
        
        records = sheet.get_all_records()
        return jsonify(records)
    except Exception as e:
        logger.error(f"Error getting bookings: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/active_sessions", methods=["GET"])
def get_active_sessions():
    """Get active chat sessions"""
    return jsonify({"sessions": booking_sessions})

@app.route("/api/user_session/<phone>", methods=["GET"])
def get_user_session(phone):
    """Get user session info"""
    session = booking_sessions.get(phone, {})
    return jsonify({
        "has_session": bool(session),
        "step": session.get('step', 'no_session'),
        "flow": "booking",
        "name": session.get('name', 'Unknown'),
        "tour_type": session.get('cruise_type', 'Not selected')
    })

@app.route("/api/capacity/<date>/<cruise_type>", methods=["GET"])
def get_capacity(date, cruise_type):
    """Get capacity for specific cruise"""
    try:
        current_capacity = get_cruise_capacity(date, cruise_type)
        available = CRUISE_CONFIG["max_capacity"] - current_capacity
        return jsonify({
            "date": date,
            "cruise_type": cruise_type,
            "current_capacity": current_capacity,
            "available_seats": available,
            "max_capacity": CRUISE_CONFIG["max_capacity"]
        })
    except Exception as e:
        logger.error(f"Error getting capacity: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/report/<date>", methods=["GET"])
def generate_report(date):
    """Generate CSV report for a specific date"""
    try:
        if not sheet:
            return jsonify({"error": "Google Sheets not configured"}), 500
            
        all_records = sheet.get_all_records()
        
        # Filter bookings for the specific date with confirmed status
        daily_bookings = []
        total_guests = 0
        total_revenue = 0
        
        for record in all_records:
            if (record.get('Cruise Date') == date and 
                record.get('Booking Status') == 'Confirmed' and
                record.get('Payment Status') == 'Paid'):
                
                booking_data = {
                    'booking_id': record.get('Booking ID', ''),
                    'name': record.get('Customer Name', ''),
                    'phone': record.get('Phone Number', ''),
                    'cruise_type': record.get('Cruise Type', ''),
                    'cruise_time': record.get('Cruise Time', ''),
                    'adults': record.get('Adults Count', 0),
                    'children': record.get('Children Count', 0),
                    'infants': record.get('Infants Count', 0),
                    'total_guests': record.get('Total Guests', 0),
                    'total_amount': record.get('Total Amount', 0)
                }
                
                daily_bookings.append(booking_data)
                total_guests += int(record.get('Total Guests', 0))
                total_revenue += float(record.get('Total Amount', 0))
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Sindbad Ship Cruises - Daily Report', date])
        writer.writerow(['Generated on:', datetime.now().strftime('%Y-%m-%d %I:%M %p')])
        writer.writerow([])
        writer.writerow(['Report Summary:'])
        writer.writerow(['Total Bookings:', len(daily_bookings)])
        writer.writerow(['Total Guests:', total_guests])
        writer.writerow(['Total Revenue:', f"{total_revenue:.3f} OMR"])
        writer.writerow([])
        writer.writerow(['Booking Details:'])
        writer.writerow(['Booking ID', 'Name', 'Phone', 'Cruise Type', 'Time', 'Adults', 'Children', 'Infants', 'Total Guests', 'Amount'])
        
        # Write booking data
        for booking in daily_bookings:
            writer.writerow([
                booking['booking_id'],
                booking['name'],
                booking['phone'],
                booking['cruise_type'],
                booking['cruise_time'],
                booking['adults'],
                booking['children'],
                booking['infants'],
                booking['total_guests'],
                f"{booking['total_amount']} OMR"
            ])
        
        # Convert to bytes and return as file
        csv_bytes = output.getvalue().encode('utf-8')
        output.close()
        
        return send_file(
            io.BytesIO(csv_bytes),
            as_attachment=True,
            download_name=f"Sindbad_Report_{date}.csv",
            mimetype='text/csv'
        )
        
    except Exception as e:
        logger.error(f"Error generating report: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/broadcast", methods=["POST"])
def send_broadcast():
    """Send broadcast messages to segments"""
    try:
        data = request.get_json()
        segment = data.get('segment', 'all')
        message = data.get('message', '')
        
        if not message:
            return jsonify({"error": "Message is required"}), 400
        
        if not sheet:
            return jsonify({"error": "Google Sheets not configured"}), 500
            
        all_records = sheet.get_all_records()
        recipients = []
        
        # Filter recipients based on segment
        for record in all_records:
            whatsapp_id = record.get('WhatsApp ID')
            if whatsapp_id:
                if segment == 'all':
                    recipients.append(whatsapp_id)
                elif segment == 'book_tour' and record.get('Booking Status') == 'Confirmed':
                    recipients.append(whatsapp_id)
                elif segment == 'pending' and record.get('Booking Status') == 'Pending':
                    recipients.append(whatsapp_id)
        
        # Remove duplicates
        recipients = list(set(recipients))
        
        # Send messages
        sent = 0
        failed = 0
        
        for recipient in recipients[:10]:  # Limit for demo
            if send_whatsapp_message(recipient, message):
                sent += 1
            else:
                failed += 1
        
        return jsonify({
            "status": "success",
            "sent": sent,
            "failed": failed,
            "total_recipients": len(recipients)
        })
        
    except Exception as e:
        logger.error(f"Error in broadcast: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    status = {
        "status": "Sindbad Ship Cruises WhatsApp API Active 🚢",
        "timestamp": str(datetime.now()),
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "sheets_available": sheet is not None,
        "active_sessions": len(booking_sessions),
        "pending_payments": len(payment_sessions),
        "max_capacity": CRUISE_CONFIG["max_capacity"],
        "version": "1.0 - Production Ready"
    }
    return jsonify(status)

# ==============================
# WEBHOOK ENDPOINTS  
# ==============================

@app.route("/webhook", methods=["GET"])
def verify():
    """Webhook verification"""
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if token == VERIFY_TOKEN:
        logger.info("✅ Webhook verified successfully")
        return challenge
    else:
        logger.warning("❌ Webhook verification failed")
        return "Verification token mismatch", 403

@app.route("/webhook", methods=["POST"])
def webhook():
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
            interactive_data = message["interactive"]
            if interactive_data["type"] == "list_reply":
                option_id = interactive_data["list_reply"]["id"]
                logger.info(f"📋 List option selected: {option_id} by {phone_number}")
                handle_interaction(option_id, phone_number)
                return jsonify({"status": "list_handled"})
        
        # Handle text messages
        if "text" in message:
            text = message["text"]["body"].strip()
            logger.info(f"💬 Text message: '{text}' from {phone_number}")
            
            language = get_user_language(phone_number)
            session = booking_sessions.get(phone_number)
            
            # New user - send language selection
            if not session and text.lower() in ["hi", "hello", "hey", "مرحبا", "اهلا", "السلام"]:
                send_language_selection(phone_number)
                return jsonify({"status": "language_selection_sent"})
            
            # Handle booking flow steps
            if session and session.get('step') == 'awaiting_name':
                ask_for_phone(phone_number, text, language)
                return jsonify({"status": "name_received"})
            
            elif session and session.get('step') == 'awaiting_phone':
                ask_for_date(phone_number, session['name'], text, language)
                return jsonify({"status": "phone_received"})
            
            elif session and session.get('step') == 'awaiting_date':
                ask_for_adults(phone_number, session['name'], session['phone'], text, language)
                return jsonify({"status": "date_received"})
            
            elif session and session.get('step') == 'awaiting_adults':
                if text.isdigit() and int(text) > 0:
                    ask_for_children(phone_number, session['name'], session['phone'], session['cruise_date'], text, language)
                    return jsonify({"status": "adults_received"})
                else:
                    send_whatsapp_message(phone_number, "Please enter a valid number of adults.")
            
            elif session and session.get('step') == 'awaiting_children':
                if text.isdigit() and int(text) >= 0:
                    ask_for_infants(phone_number, session['name'], session['phone'], session['cruise_date'], session['adults_count'], text, language)
                    return jsonify({"status": "children_received"})
                else:
                    send_whatsapp_message(phone_number, "Please enter a valid number of children.")
            
            elif session and session.get('step') == 'awaiting_infants':
                if text.isdigit() and int(text) >= 0:
                    ask_for_cruise_type(phone_number, session['name'], session['phone'], session['cruise_date'], session['adults_count'], session['children_count'], text, language)
                    return jsonify({"status": "infants_received"})
                else:
                    send_whatsapp_message(phone_number, "Please enter a valid number of infants.")
            
            # Fallback to main menu
            send_main_menu(phone_number, language)
            return jsonify({"status": "fallback_menu"})
        
        return jsonify({"status": "unhandled_message_type"})
        
    except Exception as e:
        logger.error(f"🚨 Error in webhook: {str(e)}")
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
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)