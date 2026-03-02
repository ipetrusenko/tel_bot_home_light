import telebot
from telebot import types
import serial
import time
import os
import signal
import sys
import sqlite3
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
users_str = os.getenv('ALLOWED_USERS', '')
ALLOWED_USERS = [int(u) for u in users_str.split(',') if u.strip().isdigit()]

SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
BAUD_RATE = 9600
DB_PATH = "/home/pi/smart_home.db"

led_states = {13: 0, 12: 0, 8: 0, 9: 0}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS light_states 
                      (pin INTEGER PRIMARY KEY, state INTEGER)''')
    for pin in led_states.keys():
        cursor.execute('INSERT OR IGNORE INTO light_states VALUES (?, ?)', (pin, 0))
    conn.commit()
    conn.close()
    print("🗄️ База даних готова")

def save_state_to_db(pin, state):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE light_states SET state = ? WHERE pin = ?', (state, pin))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Помилка запису в БД: {e}")

def restore_states():
    print("🔄 Відновлення стану світла з бази...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT pin, state FROM light_states')
        rows = cursor.fetchall()
        for pin, state in rows:
            if state == 1:
                execute_command(pin, 1, source="System Restore")
                time.sleep(0.1)
        conn.close()
    except Exception as e:
        print(f"❌ Помилка відновлення станів: {e}")

def execute_command(pin, state, source="Unknown"):
    try:
        state = int(state)
        led_states[pin] = state
        
        save_state_to_db(pin, state)
        
        if ser and ser.is_open:
            command = f"{pin} {state}"
            ser.write(command.encode('utf-8'))
            print(f"🔌 [{source}] Пін {pin} -> {state}")
            return True
        else:
            print(f"⚠️ Arduino недоступна для команди {pin}:{state}")
            return False
    except Exception as e:
        print(f"❌ Помилка виконання: {e}")
        return False

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    print("✅ Arduino підключено!")
except Exception as e:
    print(f"❌ Помилка Arduino: {e}")
    ser = None

bot = telebot.TeleBot(TOKEN)

def main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [types.KeyboardButton(x) for x in ['🍳 Кухня', '🛁 Ванна', '🚽 Туалет', '🛏 Кімната']]
    markup.add(*buttons)
    return markup

@bot.message_handler(commands=['start'])
def start_command(message):
    if message.from_user.id in ALLOWED_USERS:
        bot.reply_to(message, "🏠 Розумний дім активний. Керуй світлом:", reply_markup=main_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    if message.from_user.id not in ALLOWED_USERS: return
    
    mapping = {'🍳 Кухня': 13, '🛁 Ванна': 12, '🚽 Туалет': 8, '🛏 Кімната': 9}
    msg_text = message.text
    
    if msg_text in mapping:
        pin = mapping[msg_text]
        new_state = 1 if led_states[pin] == 0 else 0
        if execute_command(pin, new_state, source="Telegram"):
            status = "УВІМКНЕНО 💡" if new_state else "ВИМКНЕНО 🌑"
            bot.reply_to(message, f"{msg_text}: {status}")

def signal_handler(sig, frame):
    print('\n🛑 Завершення роботи...')
    if ser: ser.close()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    init_db()

    restore_states()

    print("🤖 Бот активований і слухає...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)