import telebot
from telebot import types
import serial
import time
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

# 1. Завантажуємо секрети з .env
load_dotenv()

# --- КОНФІГУРАЦІЯ ---
TOKEN = os.getenv('BOT_TOKEN')

# Хитрість: беремо рядок "123,456" і робимо з нього список чисел
users_str = os.getenv('ALLOWED_USERS', '')
ALLOWED_USERS = [int(u) for u in users_str.split(',') if u.strip().isdigit()]

# MQTT (VPS)
MQTT_BROKER = os.getenv('MQTT_BROKER')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
MQTT_USER = os.getenv('MQTT_USER')
MQTT_PASS = os.getenv('MQTT_PASS')
MQTT_TOPIC = "home/light/+"

# Arduino
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
BAUD_RATE = 9600

# --- СТАН СИСТЕМИ (ВИПРАВЛЕНО) ---
# Тут ми просто зберігаємо стани пінів
led_states = {
    13: 0,  # Кухня
    12: 0,  # Ванна
    8: 0,   # Туалет
    9: 0    # Кімната
}

# --- ПІДКЛЮЧЕННЯ ДО ARDUINO ---
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    print("✅ Arduino підключено!")
    # Скидаємо в 0 при старті
    for pin in led_states:
        ser.write(f"{pin} 0".encode('utf-8'))
        time.sleep(0.05)
except Exception as e:
    print(f"❌ Помилка Arduino: {e}")
    ser = None

# Ініціалізація бота
bot = telebot.TeleBot(TOKEN)
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

# --- ФУНКЦІЯ ВИКОНАННЯ КОМАНДИ ---
def execute_command(pin, state, source="Unknown", mqtt_sender=None):
    try:
        led_states[pin] = int(state)
        if ser and ser.is_open:
            command = f"{pin} {state}"
            ser.write(command.encode('utf-8'))
            print(f"🔌 [{source}] Виконано: {command}")
            status_topic = f"home/light/{pin}/status"
            client_to_use = mqtt_sender if mqtt_sender else mqtt_client
            try:
                client_to_use.publish(status_topic, state, retain=True)
                print(f"📡 Статус відправлено в: {status_topic}")
            except Exception as ex:
                print(f"⚠️ Не вдалося відправити статус: {ex}")

            return True
        else:
            print("⚠️ Arduino недоступна")
            return False
    except Exception as e:
        print(f"❌ Помилка виконання: {e}")
        return False

# --- MQTT ЛОГІКА ---
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ Підключено до MQTT (VPS)")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"❌ MQTT помилка: {rc}")

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode().strip()
        topic = msg.topic
        if "status" in topic: return
        if payload not in ['0', '1']: return

        state = int(payload)
        try:
            pin = int(topic.split("/")[-1])
        except: return

        if pin in led_states:
            execute_command(pin, state, source="MQTT/n8n", mqtt_sender=client)

    except Exception as e:
        print(f"❌ MQTT Error: {e}")

mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# --- TELEGRAM ЛОГІКА ---
def main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('🍳 Кухня')
    btn2 = types.KeyboardButton('🛁 Ванна')
    btn3 = types.KeyboardButton('🚽 Туалет')
    btn4 = types.KeyboardButton('🛏 Кімната')
    markup.add(btn1, btn2, btn3, btn4)
    return markup

@bot.message_handler(commands=['start'])
def start_command(message):
    if message.from_user.id in ALLOWED_USERS:
        bot.reply_to(message, "Піни перепризначено! Керуй.", reply_markup=main_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    if user_id not in ALLOWED_USERS:
        return

    msg = message.text
    pin = None
    name = ""

    # --- ТУТ МИ ВИПРАВИЛИ ЛОГІКУ ---
    if msg == '🍳 Кухня':
        pin = 13  # Тепер це 13
        name = "Кухня"
    elif msg == '🛁 Ванна':
        pin = 12  # Залишилось 12
        name = "Ванна"
    elif msg == '🚽 Туалет':
        pin = 8   # Тепер це 8
        name = "Туалет"
    elif msg == '🛏 Кімната':
        pin = 9   # Тепер це 9
        name = "Кімната"

    if pin:
        current_state = led_states[pin]
        new_state = 1 if current_state == 0 else 0
        success = execute_command(pin, new_state, source="Telegram")
        status_text = "УВІМКНЕНО 💡" if new_state else "ВИМКНЕНО 🌑"
        if success:
            bot.reply_to(message, f"{name}: {status_text}")
        else:
            bot.reply_to(message, "Помилка зв'язку")

# --- ЗАПУСК ---
if __name__ == "__main__":
    print("🚀 Запускаю систему...")

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start() 
    except Exception as e:
        print(f"⚠️ MQTT помилка: {e}")

    print("🤖 Бот слухає...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
