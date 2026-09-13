import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
import pytz
import sqlite3
import qrcode
from io import BytesIO
import requests
import json
import os
import shutil
import time
import threading
import re

# ==================== تنظیمات ====================
TOKEN = os.environ.get("TOKEN", "8975159689:AAGt7O3t6Bep3s85pv5NBEpTANmIetmLGnM")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "ab62d763add18fa245f9d8b70241b6a2")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7699447054"))

# مسیر پایدار برای دیتابیس (Railway Volume)
DB_DIR = os.environ.get("DB_DIR", "/app/data")
DB_PATH = os.path.join(DB_DIR, "bot_data.db")

# ساخت پوشه دیتابیس اگر وجود ندارد
os.makedirs(DB_DIR, exist_ok=True)

# بررسی توکن
if not TOKEN or TOKEN == "YOUR_BOT_TOKEN":
    print("❌ لطفا توکن ربات را در متغیرهای محیطی تنظیم کنید!")
    exit()

bot = telebot.TeleBot(TOKEN)

# ==================== دیتابیس اصلی ====================
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY,
                      first_name TEXT,
                      last_name TEXT,
                      username TEXT,
                      join_date TEXT,
                      score INTEGER DEFAULT 0,
                      is_blocked INTEGER DEFAULT 0)''')
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ خطا در ایجاد دیتابیس: {e}")
        return False

# ==================== دیتابیس قیمت‌ها ====================
def init_price_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS price_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      symbol TEXT,
                      price REAL,
                      change_percent REAL,
                      timestamp TEXT,
                      UNIQUE(symbol, timestamp))''')

        c.execute('''CREATE TABLE IF NOT EXISTS price_alerts
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      symbol TEXT,
                      target_price REAL,
                      condition TEXT,
                      is_active INTEGER DEFAULT 1,
                      created_at TEXT)''')
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ خطا در ایجاد دیتابیس قیمت: {e}")
        return False

# ==================== توابع دیتابیس ====================
def save_user(user):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''INSERT OR IGNORE INTO users
                     (user_id, first_name, last_name, username, join_date, score)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (user.id, user.first_name or '', user.last_name or '',
                   user.username or '', datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ خطا در ذخیره کاربر: {e}")
        return False

def update_score(user_id, points=1):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET score = score + ? WHERE user_id = ?', (points, user_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ خطا در به‌روزرسانی امتیاز: {e}")
        return False

def get_user_score(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT score FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as e:
        print(f"❌ خطا در دریافت امتیاز: {e}")
        return 0

def get_user_level(score):
    if score < 10:
        return "🌱 تازه‌کار", "⬜"
    elif score < 50:
        return "⭐ کاربر فعال", "🟩"
    elif score < 200:
        return "🔥 کاربر حرفه‌ای", "🟦"
    else:
        return "👑 کاربر ویژه", "🟪"

def get_total_users():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        result = c.fetchone()[0]
        conn.close()
        return result
    except Exception as e:
        print(f"❌ خطا در دریافت تعداد کاربران: {e}")
        return 0

def get_all_users():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT user_id, first_name, username, score, is_blocked FROM users ORDER BY score DESC')
        users = c.fetchall()
        conn.close()
        return users
    except Exception as e:
        print(f"❌ خطا در دریافت لیست کاربران: {e}")
        return []

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_user_blocked(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result and result[0] == 1
    except Exception as e:
        print(f"❌ خطا در بررسی مسدودیت: {e}")
        return False

# ==================== توابع قیمت (برای آینده) ====================
def format_price(price):
    if price >= 1000000:
        return f"{price:,.0f}".replace(',', '،')
    elif price >= 1:
        return f"{price:,.2f}".replace(',', '،')
    else:
        return f"{price:.8f}"

# ==================== منوها ====================
def main_menu(user_id):
    keyboard = InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        InlineKeyboardButton("👤 پروفایل من", callback_data="info")
    )
    keyboard.add(
        InlineKeyboardButton("🆔 آیدی من", callback_data="id"),
        InlineKeyboardButton("📛 یوزرنیم", callback_data="username")
    )
    keyboard.add(
        InlineKeyboardButton("⏰ زمان فعلی", callback_data="time"),
        InlineKeyboardButton("⭐ امتیاز من", callback_data="score")
    )
    keyboard.add(
        InlineKeyboardButton("🌤️ آب و هوا", callback_data="weather"),
        InlineKeyboardButton("📱 QR Code", callback_data="qr")
    )
    keyboard.add(
        InlineKeyboardButton("💰 قیمت‌های لحظه‌ای", callback_data="price_menu")
    )

    if is_admin(user_id):
        keyboard.add(
            InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")
        )

    keyboard.add(
        InlineKeyboardButton("📱 کانال ما", url="https://t.me/YourChannel"),
        InlineKeyboardButton("💬 پشتیبانی", url="https://t.me/YourSupport")
    )
    keyboard.add(
        InlineKeyboardButton("ℹ️ درباره ربات", callback_data="about")
    )

    return keyboard

def admin_panel():
    keyboard = InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats")
    )
    keyboard.add(
        InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users")
    )
    keyboard.add(
        InlineKeyboardButton("📨 ارسال پیام همگانی", callback_data="admin_broadcast")
    )
    keyboard.add(
        InlineKeyboardButton("⭐ مدیریت امتیاز", callback_data="admin_manage_score")
    )
    keyboard.add(
        InlineKeyboardButton("🚫 مسدود کردن کاربر", callback_data="admin_block")
    )
    keyboard.add(
        InlineKeyboardButton("📋 پشتیبان‌گیری", callback_data="admin_backup")
    )
    keyboard.add(
        InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_to_main")
    )

    return keyboard

def admin_users_menu(page=1, per_page=10):
    keyboard = InlineKeyboardMarkup(row_width=3)

    users = get_all_users()
    total_pages = (len(users) + per_page - 1) // per_page

    start = (page - 1) * per_page
    end = start + per_page
    page_users = users[start:end]

    for user in page_users:
        user_id, first_name, username, score, is_blocked = user
        display_name = first_name if first_name else f"User{user_id}"
        status = "🚫" if is_blocked else "✅"
        keyboard.add(
            InlineKeyboardButton(
                f"{status} {display_name[:12]} ⭐{score}",
                callback_data=f"admin_user_{user_id}"
            )
        )

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"admin_users_page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="admin_users_info"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"admin_users_page_{page+1}"))

    if nav_buttons:
        keyboard.add(*nav_buttons)

    keyboard.add(
        InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin_panel")
    )

    return keyboard

def price_menu():
    keyboard = InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        InlineKeyboardButton("🏅 طلا", callback_data="price_coming_soon"),
        InlineKeyboardButton("🪙 سکه", callback_data="price_coming_soon")
    )
    keyboard.add(
        InlineKeyboardButton("💵 دلار", callback_data="price_coming_soon"),
        InlineKeyboardButton("💶 یورو", callback_data="price_coming_soon")
    )
    keyboard.add(
        InlineKeyboardButton("₿ بیت‌کوین", callback_data="price_coming_soon"),
        InlineKeyboardButton("⟠ اتریوم", callback_data="price_coming_soon")
    )
    keyboard.add(
        InlineKeyboardButton("📊 قیمت‌های لحظه‌ای", callback_data="price_coming_soon"),
        InlineKeyboardButton("🔔 اعلان قیمت", callback_data="price_coming_soon")
    )
    keyboard.add(
        InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_to_main")
    )

    return keyboard

# ==================== هدر و فوتر ====================
def create_header(title, icon="✨"):
    border = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    return f"""
{icon} <b>{title}</b> {icon}
{border}"""

def create_footer():
    return """
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
👨‍💻 <b>سازنده:</b> <a href="https://t.me/MrNobody_Ir">Reza Yousefi</a>
❤️ <b>با عشق از ایران</b> ❤️"""

# ==================== توابع کمکی ====================
def get_weather_data(city_name):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=fa"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return f"❌ <b>خطا در اتصال به سرویس آب و هوا!</b>\nکد خطا: {response.status_code}"

        data = response.json()

        if data.get('cod') == 200:
            temp = data['main']['temp']
            feels_like = data['main']['feels_like']
            desc = data['weather'][0]['description']
            humidity = data['main']['humidity']
            wind = data['wind']['speed']
            pressure = data['main']['pressure']
            emoji = get_weather_emoji(desc)

            text = f"""
🌤️ <b>آب و هوای {city_name}</b>
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🌡️ <b>دما:</b> {temp}°C
🤔 <b>احساس می‌شود:</b> {feels_like}°C
📝 <b>وضعیت:</b> {desc} {emoji}
💧 <b>رطوبت:</b> {humidity}%
💨 <b>باد:</b> {wind} m/s
📊 <b>فشار هوا:</b> {pressure} hPa

🕐 <b>به‌روزرسانی:</b> {datetime.now().strftime('%H:%M')}
"""
            return text
        else:
            return f"❌ <b>شهر '{city_name}' پیدا نشد!</b>"
    except requests.exceptions.Timeout:
        return "❌ <b>زمان اتصال به سرویس آب و هوا به پایان رسید!</b>"
    except requests.exceptions.ConnectionError:
        return "❌ <b>خطا در اتصال به اینترنت!</b>"
    except Exception as e:
        return f"❌ خطا: {str(e)}"

def get_weather_emoji(description):
    weather_map = {
        'clear': '☀️', 'sun': '☀️', 'cloud': '☁️', 'rain': '🌧️',
        'drizzle': '🌦️', 'thunder': '⛈️', 'storm': '⛈️', 'snow': '❄️',
        'mist': '🌫️', 'fog': '🌫️', 'haze': '🌫️', 'smoke': '💨', 'wind': '💨'
    }
    for key, emoji in weather_map.items():
        if key in description.lower():
            return emoji
    return '🌤️'

def generate_and_send_qr(chat_id, qr_data, user_id):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        bio = BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)

        bot.send_photo(
            chat_id, bio,
            caption=f"✅ <b>QR Code تولید شد!</b>\n\n📝 <b>محتوا:</b>\n<code>{qr_data}</code>",
            parse_mode='HTML'
        )
        update_score(user_id, 2)
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطا در تولید QR Code: {str(e)}")

# ==================== دستورات ====================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user

    if is_user_blocked(user.id):
        bot.reply_to(message, "🚫 شما توسط ادمین مسدود شده‌اید!")
        return

    save_user(user)
    update_score(user.id, 5)

    welcome_msg = f"""
🌟 <b>به ربات حرفه‌ای خوش آمدید!</b> 🌟

▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

👋 سلام <b>{user.first_name}</b> عزیز!

🎯 این ربات امکانات زیر دارد:
✅ نمایش اطلاعات کاربری
✅ نمایش زمان و تاریخ
✅ سیستم امتیازدهی
✅ پیش‌بینی آب و هوا
✅ تولید QR Code
✅ قیمت‌های لحظه‌ای (به زودی)
{"✅ پنل مدیریت" if is_admin(user.id) else ""}

🎁 <b>امتیاز شروع:</b> 5 امتیاز

{create_footer()}
"""
    bot.reply_to(message, welcome_msg, parse_mode='HTML', reply_markup=main_menu(user.id))

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if is_admin(message.from_user.id):
        bot.reply_to(message, "⚙️ <b>به پنل مدیریت خوش آمدید!</b>",
                    parse_mode='HTML', reply_markup=admin_panel())
    else:
        bot.reply_to(message, "❌ شما دسترسی به پنل مدیریت ندارید!")

@bot.message_handler(commands=['weather'])
def get_weather_command(message):
    if is_user_blocked(message.from_user.id):
        bot.reply_to(message, "🚫 شما مسدود شده‌اید!")
        return

    city = message.text.split(maxsplit=1)
    if len(city) > 1:
        city_name = city[1]
    else:
        city_name = "Tehran"

    weather_info = get_weather_data(city_name)
    bot.reply_to(message, weather_info, parse_mode='HTML', reply_markup=main_menu(message.from_user.id))
    update_score(message.from_user.id, 3)

@bot.message_handler(commands=['qr'])
def generate_qr_command(message):
    if is_user_blocked(message.from_user.id):
        bot.reply_to(message, "🚫 شما مسدود شده‌اید!")
        return

    text = message.text.split(maxsplit=1)
    if len(text) > 1:
        qr_data = text[1]
    else:
        qr_data = f"https://t.me/{bot.get_me().username}"

    generate_and_send_qr(message.chat.id, qr_data, message.from_user.id)

@bot.message_handler(commands=['score'])
def show_score_command(message):
    if is_user_blocked(message.from_user.id):
        bot.reply_to(message, "🚫 شما مسدود شده‌اید!")
        return

    user_id = message.from_user.id
    score = get_user_score(user_id)
    level, emoji = get_user_level(score)

    text = f"""
⭐ <b>امتیاز شما</b> ⭐
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🏅 <b>امتیاز:</b> {score}
📊 <b>سطح:</b> {level}
{emoji} <b>وضعیت:</b> {'فعال' if score > 10 else 'تازه وارد'}

💡 <i>با استفاده از ربات امتیاز بگیرید!</i>
"""
    bot.reply_to(message, text, parse_mode='HTML', reply_markup=main_menu(user_id))

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    bot.reply_to(message, "❌ عملیات لغو شد!", reply_markup=main_menu(message.from_user.id))

# ==================== کالبک‌ها ====================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user = call.from_user
    user_id = user.id

    if is_user_blocked(user_id) and call.data not in ["admin_panel", "admin_stats", "admin_users", "admin_broadcast", "admin_manage_score", "admin_block", "admin_backup"]:
        bot.answer_callback_query(call.id, "🚫 شما مسدود شده‌اید!", show_alert=True)
        return

    update_score(user_id, 1)

    # ========== منوی اصلی ==========
    if call.data == "info":
        score = get_user_score(user_id)
        level, _ = get_user_level(score)

        text = f"""
{create_header('اطلاعات پروفایل شما', '👤')}

👤 <b>نام:</b> {user.first_name}
🧑 <b>نام خانوادگی:</b> {user.last_name if user.last_name else '❌ مشخص نشده'}
📛 <b>یوزرنیم:</b> @{user.username if user.username else 'ندارد'}
🌐 <b>زبان:</b> {user.language_code if user.language_code else '❌ مشخص نشده'}
⭐ <b>سطح:</b> {level}
🏅 <b>امتیاز:</b> {score}

{create_footer()}
"""
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode='HTML', reply_markup=main_menu(user_id))

    elif call.data == "score":
        score = get_user_score(user_id)
        level, emoji = get_user_level(score)

        text = f"""
⭐ <b>امتیاز شما</b> ⭐
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🏅 <b>امتیاز:</b> {score}
📊 <b>سطح:</b> {level}
{emoji} <b>وضعیت:</b> {'فعال' if score > 10 else 'تازه وارد'}

🎯 <b>چگونه امتیاز بگیریم؟</b>
• استفاده از ربات: +1
• شروع ربات: +5
• آب و هوا: +3
• تولید QR: +2
"""
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode='HTML', reply_markup=main_menu(user_id))

    elif call.data == "time":
        tehran_tz = pytz.timezone('Asia/Tehran')
        now = datetime.now(tehran_tz)

        text = f"""
{create_header('زمان و تاریخ', '⏰')}

📅 <b>تاریخ:</b> {now.strftime("%Y/%m/%d")}
🕐 <b>ساعت:</b> {now.strftime("%H:%M:%S")}
🌍 <b>منطقه زمانی:</b> تهران (IRST)

{create_footer()}
"""
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode='HTML', reply_markup=main_menu(user_id))

    elif call.data == "weather":
        msg = bot.send_message(call.message.chat.id,
                              "🌤️ <b>لطفاً نام شهر را به انگلیسی وارد کنید:</b>",
                              parse_mode='HTML')
        bot.register_next_step_handler(msg, process_weather_city)
        bot.answer_callback_query(call.id)

    elif call.data == "qr":
        msg = bot.send_message(call.message.chat.id,
                              "📱 <b>لطفاً متن یا لینک مورد نظر را وارد کنید:</b>",
                              parse_mode='HTML')
        bot.register_next_step_handler(msg, process_qr_text)
        bot.answer_callback_query(call.id)

    elif call.data == "about":
        text = f"""
{create_header('درباره ربات', '🤖')}

🎯 <b>قابلیت‌ها:</b>
• نمایش پروفایل کاربر
• سیستم امتیازدهی
• پیش‌بینی آب و هوا
• تولید QR Code
• نمایش زمان و تاریخ
• قیمت‌های لحظه‌ای (به زودی)
• پنل مدیریت کامل

🛠 <b>تکنولوژی:</b>
• Python 3
• Telebot Library
• SQLite3
• OpenWeather API

📦 <b>نسخه:</b> 3.2.0

{create_footer()}
"""
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode='HTML', reply_markup=main_menu(user_id))

    elif call.data == "id" or call.data == "username":
        text = f"""
{create_header('اطلاعات شناسایی', '🆔')}

📛 <b>یوزرنیم:</b> @{user.username if user.username else 'ندارد'}
🔢 <b>آیدی عددی:</b> <code>{user.id}</code>

💡 <i>این اطلاعات برای شناسایی شما در تلگرام است.</i>

{create_footer()}
"""
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode='HTML', reply_markup=main_menu(user_id))

    # ========== منوی قیمت‌ها ==========
    elif call.data == "price_menu":
        text = """
🪙 <b>قیمت‌های لحظه‌ای</b>
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🎯 از دکمه‌های زیر برای مشاهده قیمت‌ها استفاده کنید:

🏅 طلا - قیمت طلای ۱۸ عیار
🪙 سکه - قیمت سکه بهار آزادی
💵 دلار - قیمت دلار آمریکا
💶 یورو - قیمت یورو
₿ بیت‌کوین - قیمت بیت‌کوین
⟠ اتریوم - قیمت اتریوم

📊 قیمت‌های لحظه‌ای - مشاهده همه قیمت‌ها
🔔 اعلان قیمت - تنظیم اعلان برای قیمت‌ها
"""
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode='HTML', reply_markup=price_menu())

    # ========== پیام "به زودی" برای قیمت‌ها ==========
    elif call.data == "price_coming_soon":
        text = """
⏳ <b>در حال توسعه...</b>

🪙 بخش قیمت‌های لحظه‌ای به زودی اضافه می‌شود!

🔜 تیم توسعه در حال اتصال به APIهای معتبر برای ارائه قیمت‌های دقیق است.

📌 <b>قابلیت‌های در دست توسعه:</b>
✅ قیمت طلا
✅ قیمت سکه
✅ قیمت ارزهای خارجی
✅ قیمت رمزارزها
✅ اعلان قیمت

🙏 از صبر و شکیبایی شما سپاسگزاریم!

{create_footer()}
"""
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                             parse_mode='HTML', reply_markup=price_menu())

    # ========== پنل مدیریت ==========
    elif call.data == "admin_panel":
        if is_admin(user_id):
            bot.edit_message_text(
                "⚙️ <b>پنل مدیریت</b>\n\n"
                "🔹 از دکمه‌های زیر برای مدیریت ربات استفاده کنید:\n\n"
                "📊 <b>آمار کامل</b> - مشاهده آمار دقیق\n"
                "👥 <b>لیست کاربران</b> - مشاهده و مدیریت کاربران\n"
                "📨 <b>پیام همگانی</b> - ارسال پیام به همه کاربران\n"
                "⭐ <b>مدیریت امتیاز</b> - افزایش/کاهش امتیاز کاربر\n"
                "🚫 <b>مسدود کردن</b> - مسدود کردن کاربران متخلف\n"
                "📋 <b>پشتیبان‌گیری</b> - تهیه نسخه پشتیبان",
                call.message.chat.id, call.message.message_id,
                parse_mode='HTML', reply_markup=admin_panel()
            )

    elif call.data == "back_to_main":
        bot.edit_message_text(
            "🔙 بازگشت به منوی اصلی",
            call.message.chat.id, call.message.message_id,
            reply_markup=main_menu(user_id)
        )

    # ========== مدیریت: آمار کامل ==========
    elif call.data == "admin_stats":
        if is_admin(user_id):
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()

                c.execute('SELECT COUNT(*) FROM users')
                total_users = c.fetchone()[0]

                c.execute('SELECT SUM(score) FROM users')
                total_score = c.fetchone()[0] or 0

                c.execute('SELECT AVG(score) FROM users')
                avg_score = c.fetchone()[0] or 0

                c.execute('SELECT MAX(score) FROM users')
                max_score = c.fetchone()[0] or 0

                c.execute('SELECT COUNT(*) FROM users WHERE score < 10')
                new_users = c.fetchone()[0]

                c.execute('SELECT COUNT(*) FROM users WHERE score >= 200')
                vip_users = c.fetchone()[0]

                c.execute('SELECT COUNT(*) FROM users WHERE is_blocked = 1')
                blocked_users = c.fetchone()[0]

                c.execute('SELECT COUNT(*) FROM users WHERE score >= 10 AND score < 200 AND is_blocked = 0')
                active_users = c.fetchone()[0]

                conn.close()

                text = f"""
📊 <b>آمار کامل ربات</b>
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

👥 <b>کل کاربران:</b> {total_users}
⭐ <b>مجموع امتیاز:</b> {total_score:,}
📊 <b>میانگین امتیاز:</b> {avg_score:.1f}
🏆 <b>بیشترین امتیاز:</b> {max_score}

📈 <b>توزیع کاربران:</b>
🌱 تازه‌کار (<10): {new_users}
⭐ فعال (10-200): {active_users}
👑 ویژه (200+): {vip_users}
🚫 مسدود شده: {blocked_users}

📅 <b>آخرین به‌روزرسانی:</b> {datetime.now().strftime("%Y/%m/%d %H:%M")}
"""
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                     parse_mode='HTML', reply_markup=admin_panel())
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطا: {str(e)}")

    # ========== مدیریت: لیست کاربران ==========
    elif call.data.startswith("admin_users"):
        if is_admin(user_id):
            if call.data == "admin_users" or call.data == "admin_users_info":
                page = 1
            elif call.data.startswith("admin_users_page_"):
                page = int(call.data.split("_")[-1])
            else:
                page = 1

            users = get_all_users()
            text = f"""
👥 <b>لیست کاربران</b>
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

📊 <b>کل کاربران:</b> {len(users)}

<i>برای مشاهده جزئیات هر کاربر کلیک کنید</i>
"""
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                 parse_mode='HTML', reply_markup=admin_users_menu(page))

    elif call.data.startswith("admin_user_"):
        if is_admin(user_id):
            target_id = int(call.data.split("_")[-1])

            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('SELECT * FROM users WHERE user_id = ?', (target_id,))
                user_data = c.fetchone()
                conn.close()
            except:
                user_data = None

            if user_data:
                user_id_db, first_name, last_name, username, join_date, score, is_blocked = user_data

                text = f"""
👤 <b>اطلاعات کاربر</b>
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🆔 <b>آیدی:</b> <code>{user_id_db}</code>
👤 <b>نام:</b> {first_name or '❌'}
🧑 <b>نام خانوادگی:</b> {last_name or '❌'}
📛 <b>یوزرنیم:</b> @{username if username else 'ندارد'}
⭐ <b>امتیاز:</b> {score}
📅 <b>تاریخ عضویت:</b> {join_date or 'نامشخص'}

<b>وضعیت:</b> {'🚫 مسدود شده' if is_blocked else '✅ فعال'}
"""
                keyboard = InlineKeyboardMarkup(row_width=2)

                if is_blocked:
                    keyboard.add(
                        InlineKeyboardButton("✅ رفع مسدودیت", callback_data=f"admin_unblock_{user_id_db}")
                    )
                else:
                    keyboard.add(
                        InlineKeyboardButton("🚫 مسدود کردن", callback_data=f"admin_block_{user_id_db}")
                    )

                keyboard.add(
                    InlineKeyboardButton("⭐ +10 امتیاز", callback_data=f"admin_add_score_{user_id_db}_10"),
                    InlineKeyboardButton("⭐ +50 امتیاز", callback_data=f"admin_add_score_{user_id_db}_50")
                )
                keyboard.add(
                    InlineKeyboardButton("➖ -10 امتیاز", callback_data=f"admin_remove_score_{user_id_db}_10"),
                    InlineKeyboardButton("➖ -50 امتیاز", callback_data=f"admin_remove_score_{user_id_db}_50")
                )
                keyboard.add(
                    InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_users")
                )

                bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                     parse_mode='HTML', reply_markup=keyboard)
            else:
                bot.answer_callback_query(call.id, "❌ کاربر پیدا نشد!")

    # ========== مدیریت: افزایش امتیاز ==========
    elif call.data.startswith("admin_add_score_"):
        if is_admin(user_id):
            parts = call.data.split("_")
            target_id = int(parts[3])
            amount = int(parts[4])

            update_score(target_id, amount)
            bot.answer_callback_query(call.id, f"✅ {amount} امتیاز اضافه شد!")
            show_user_info(call.message.chat.id, call.message.message_id, target_id)

    # ========== مدیریت: کاهش امتیاز ==========
    elif call.data.startswith("admin_remove_score_"):
        if is_admin(user_id):
            parts = call.data.split("_")
            target_id = int(parts[3])
            amount = int(parts[4])

            update_score(target_id, -amount)
            bot.answer_callback_query(call.id, f"✅ {amount} امتیاز کم شد!")
            show_user_info(call.message.chat.id, call.message.message_id, target_id)

    # ========== مدیریت: مسدود کردن ==========
    elif call.data.startswith("admin_block_"):
        if is_admin(user_id):
            target_id = int(call.data.split("_")[-1])

            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('UPDATE users SET is_blocked = 1 WHERE user_id = ?', (target_id,))
                conn.commit()
                conn.close()
                bot.answer_callback_query(call.id, "✅ کاربر مسدود شد!")
                show_user_info(call.message.chat.id, call.message.message_id, target_id)
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطا: {str(e)}")

    # ========== مدیریت: رفع مسدودیت ==========
    elif call.data.startswith("admin_unblock_"):
        if is_admin(user_id):
            target_id = int(call.data.split("_")[-1])

            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('UPDATE users SET is_blocked = 0 WHERE user_id = ?', (target_id,))
                conn.commit()
                conn.close()
                bot.answer_callback_query(call.id, "✅ مسدودیت کاربر رفع شد!")
                show_user_info(call.message.chat.id, call.message.message_id, target_id)
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطا: {str(e)}")

    # ========== مدیریت: ارسال پیام همگانی ==========
    elif call.data == "admin_broadcast":
        if is_admin(user_id):
            msg = bot.send_message(call.message.chat.id,
                                  "📨 <b>پیام خود را برای ارسال همگانی وارد کنید:</b>\n\n"
                                  "💡 <i>می‌توانید از HTML و ایموجی استفاده کنید.</i>\n"
                                  "❌ برای لغو /cancel را وارد کنید.",
                                  parse_mode='HTML')
            bot.register_next_step_handler(msg, process_broadcast)
            bot.answer_callback_query(call.id)

    # ========== مدیریت: مدیریت امتیاز ==========
    elif call.data == "admin_manage_score":
        if is_admin(user_id):
            msg = bot.send_message(call.message.chat.id,
                                  "⭐ <b>مدیریت امتیاز کاربر</b>\n\n"
                                  "لطفاً آیدی کاربر و مقدار امتیاز را وارد کنید:\n\n"
                                  "مثال: <code>123456789 +50</code>\n"
                                  "مثال: <code>123456789 -20</code>\n\n"
                                  "❌ برای لغو /cancel را وارد کنید.",
                                  parse_mode='HTML')
            bot.register_next_step_handler(msg, process_manage_score)
            bot.answer_callback_query(call.id)

    # ========== مدیریت: مسدود کردن کاربر (دکمه ساده) ==========
    elif call.data == "admin_block":
        if is_admin(user_id):
            msg = bot.send_message(call.message.chat.id,
                                  "🚫 <b>مسدود کردن کاربر</b>\n\n"
                                  "لطفاً آیدی عددی کاربر را وارد کنید:\n\n"
                                  "مثال: <code>123456789</code>\n\n"
                                  "❌ برای لغو /cancel را وارد کنید.",
                                  parse_mode='HTML')
            bot.register_next_step_handler(msg, process_block_user)
            bot.answer_callback_query(call.id)

    # ========== مدیریت: پشتیبان‌گیری ==========
    elif call.data == "admin_backup":
        if is_admin(user_id):
            try:
                if not os.path.exists(DB_PATH):
                    bot.answer_callback_query(call.id, "❌ فایل دیتابیس وجود ندارد!")
                    return

                backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                shutil.copy2(DB_PATH, backup_file)

                with open(backup_file, 'rb') as f:
                    bot.send_document(call.message.chat.id, f,
                                     caption=f"✅ پشتیبان‌گیری انجام شد!\n📅 تاریخ: {datetime.now().strftime('%Y/%m/%d %H:%M')}")

                os.remove(backup_file)
                bot.answer_callback_query(call.id, "✅ پشتیبان‌گیری انجام شد!")
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطا: {str(e)}")

    try:
        bot.answer_callback_query(call.id)
    except:
        pass

# ==================== توابع نمایش اطلاعات کاربر ====================
def show_user_info(chat_id, message_id, target_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (target_id,))
        user_data = c.fetchone()
        conn.close()
    except:
        user_data = None

    if user_data:
        user_id_db, first_name, last_name, username, join_date, score, is_blocked = user_data

        text = f"""
👤 <b>اطلاعات کاربر</b>
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

🆔 <b>آیدی:</b> <code>{user_id_db}</code>
👤 <b>نام:</b> {first_name or '❌'}
🧑 <b>نام خانوادگی:</b> {last_name or '❌'}
📛 <b>یوزرنیم:</b> @{username if username else 'ندارد'}
⭐ <b>امتیاز:</b> {score}
📅 <b>تاریخ عضویت:</b> {join_date or 'نامشخص'}

<b>وضعیت:</b> {'🚫 مسدود شده' if is_blocked else '✅ فعال'}
"""
        keyboard = InlineKeyboardMarkup(row_width=2)

        if is_blocked:
            keyboard.add(
                InlineKeyboardButton("✅ رفع مسدودیت", callback_data=f"admin_unblock_{user_id_db}")
            )
        else:
            keyboard.add(
                InlineKeyboardButton("🚫 مسدود کردن", callback_data=f"admin_block_{user_id_db}")
            )

        keyboard.add(
            InlineKeyboardButton("⭐ +10 امتیاز", callback_data=f"admin_add_score_{user_id_db}_10"),
            InlineKeyboardButton("⭐ +50 امتیاز", callback_data=f"admin_add_score_{user_id_db}_50")
        )
        keyboard.add(
            InlineKeyboardButton("➖ -10 امتیاز", callback_data=f"admin_remove_score_{user_id_db}_10"),
            InlineKeyboardButton("➖ -50 امتیاز", callback_data=f"admin_remove_score_{user_id_db}_50")
        )
        keyboard.add(
            InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_users")
        )

        try:
            bot.edit_message_text(text, chat_id, message_id, parse_mode='HTML', reply_markup=keyboard)
        except Exception as e:
            print(f"❌ خطا در ویرایش پیام: {e}")

# ==================== پردازش ورودی‌های کاربر ====================
def process_weather_city(message):
    if message.text and message.text.lower().startswith('/cancel'):
        bot.reply_to(message, "❌ عملیات لغو شد!", reply_markup=main_menu(message.from_user.id))
        return

    city_name = message.text.strip()
    if not city_name:
        bot.reply_to(message, "❌ لطفاً یک شهر معتبر وارد کنید!", reply_markup=main_menu(message.from_user.id))
        return

    weather_info = get_weather_data(city_name)
    bot.reply_to(message, weather_info, parse_mode='HTML', reply_markup=main_menu(message.from_user.id))
    update_score(message.from_user.id, 3)

def process_qr_text(message):
    if message.text and message.text.lower().startswith('/cancel'):
        bot.reply_to(message, "❌ عملیات لغو شد!", reply_markup=main_menu(message.from_user.id))
        return

    qr_data = message.text.strip()
    if not qr_data:
        bot.reply_to(message, "❌ لطفاً متن یا لینک معتبر وارد کنید!", reply_markup=main_menu(message.from_user.id))
        return

    generate_and_send_qr(message.chat.id, qr_data, message.from_user.id)

def process_broadcast(message):
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.lower().startswith('/cancel'):
        bot.reply_to(message, "❌ ارسال پیام همگانی لغو شد!", reply_markup=admin_panel())
        return

    broadcast_text = message.text
    if not broadcast_text:
        bot.reply_to(message, "❌ پیام نمی‌تواند خالی باشد!", reply_markup=admin_panel())
        return

    users = get_all_users()
    success_count = 0
    fail_count = 0

    status_msg = bot.reply_to(message, "📨 در حال ارسال پیام همگانی...")

    for user_id, _, _, _, _ in users:
        try:
            bot.send_message(user_id, broadcast_text, parse_mode='HTML')
            success_count += 1
        except Exception:
            fail_count += 1

    report = f"""
📨 <b>گزارش ارسال پیام همگانی</b>
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

✅ <b>موفق:</b> {success_count}
❌ <b>ناموفق:</b> {fail_count}
📊 <b>کل:</b> {success_count + fail_count}

📝 <b>متن پیام:</b>
{broadcast_text[:200]}{'...' if len(broadcast_text) > 200 else ''}
"""
    try:
        bot.edit_message_text(report, status_msg.chat.id, status_msg.message_id,
                             parse_mode='HTML', reply_markup=admin_panel())
    except:
        bot.send_message(message.chat.id, report, parse_mode='HTML', reply_markup=admin_panel())

def process_manage_score(message):
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.lower().startswith('/cancel'):
        bot.reply_to(message, "❌ عملیات لغو شد!", reply_markup=admin_panel())
        return

    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ فرمت اشتباه! مثال: 123456789 +50", reply_markup=admin_panel())
            return

        target_id = int(parts[0])
        amount = int(parts[1])

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET score = score + ? WHERE user_id = ?', (amount, target_id))
        c.execute('SELECT score FROM users WHERE user_id = ?', (target_id,))
        new_score = c.fetchone()
        conn.commit()
        conn.close()

        if new_score:
            bot.reply_to(message, f"✅ امتیاز کاربر {target_id} به {new_score[0]} تغییر یافت!",
                        reply_markup=admin_panel())
        else:
            bot.reply_to(message, f"❌ کاربر با آیدی {target_id} پیدا نشد!",
                        reply_markup=admin_panel())

    except ValueError:
        bot.reply_to(message, "❌ لطفاً اعداد معتبر وارد کنید!", reply_markup=admin_panel())
    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {str(e)}", reply_markup=admin_panel())

def process_block_user(message):
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.lower().startswith('/cancel'):
        bot.reply_to(message, "❌ عملیات لغو شد!", reply_markup=admin_panel())
        return

    try:
        target_id = int(message.text.strip())

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET is_blocked = 1 WHERE user_id = ?', (target_id,))
        c.execute('SELECT first_name FROM users WHERE user_id = ?', (target_id,))
        user = c.fetchone()
        conn.commit()
        conn.close()

        if user:
            bot.reply_to(message, f"✅ کاربر {user[0]} با آیدی <code>{target_id}</code> مسدود شد!",
                        parse_mode='HTML', reply_markup=admin_panel())
        else:
            bot.reply_to(message, f"❌ کاربر با آیدی {target_id} پیدا نشد!",
                        reply_markup=admin_panel())

    except ValueError:
        bot.reply_to(message, "❌ لطفاً یک آیدی عددی معتبر وارد کنید!", reply_markup=admin_panel())
    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {str(e)}", reply_markup=admin_panel())

# ==================== اجرا ====================
if __name__ == '__main__':
    if not init_db():
        print("❌ خطا در راه‌اندازی دیتابیس! برنامه متوقف شد.")
        exit()

    if not init_price_db():
        print("❌ خطا در راه‌اندازی دیتابیس قیمت! برنامه متوقف شد.")
        exit()

    print("""
╔════════════════════════════════════════╗
║                                        ║
║   🚀  ربات حرفه‌ای با پنل مدیریت     ║
║                                        ║
║   👨‍💻  سازنده: Reza Yousefi            ║
║   📅  نسخه: 3.2.0                      ║
║   🎯  قابلیت‌ها: 7+                    ║
║   ⚙️  پنل مدیریت: کامل                ║
║   🪙  قیمت‌ها: به زودی                 ║
║                                        ║
╚════════════════════════════════════════╝
    """)
    print("🔄 ربات در حال اجرا است...")
    print(f"👑 آیدی ادمین: {ADMIN_ID}")
    print(f"📂 مسیر دیتابیس: {DB_PATH}")
    print("📌 دستورات:")
    print("  /start - شروع ربات")
    print("  /admin - پنل مدیریت")
    print("  /weather [city] - آب و هوا")
    print("  /qr [text] - تولید QR Code")
    print("  /score - امتیاز من")
    print("  /cancel - لغو عملیات")
    print("\n💡 نکته: برای لغو هر عملیات، /cancel را وارد کنید")

    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
    except KeyboardInterrupt:
        print("\n⏹️ ربات متوقف شد.")
    except Exception as e:
        print(f"❌ خطا: {e}")
        print("🔄 تلاش مجدد در 5 ثانیه...")
        time.sleep(5)
