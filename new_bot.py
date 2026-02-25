import telebot
from telebot import types
import serial
import time
import paho.mqtt.client as mqtt
import os
import signal
import sys
from dotenv import load_dotenv

# Configuration
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
users_str = os.getenv('ALLOWED_USERS', '')
ALLOWED_USERS = [int(u) for u in users_str.split(',') if u.strip().isdigit()]

# MQTT connection
MQTT_BROKER = os.getenv('MQTT_BROKER')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
MQTT_USER = os.getenv('MQTT_USER')
MQTT_PASS = os.getenv('MQTT_PASS')
# Топік для команд: home/light/13, home/light/12 і т.д.
MQTT_COMMAND_TOPIC = "home/light/+" 

# Arduino connection
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
BAUD_RATE = 9600

led_states = {13: 0, 12: 0, 8: 0, 9: 0}

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    print("✅ Arduino підключено!")
    for pin in led_states:
        ser.write(f"{pin} 0".encode('utf-8'))
        time.sleep(0.05)
except Exception as e:
    print(f"❌ Помилка Arduino: {e}")
    ser = None

bot = telebot.TeleBot(TOKEN)
# Використовуємо CallbackAPIVersion.VERSION2 для сумісності з новим paho-mqtt
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def execute_command(pin, state, source="Unknown"):
    try:
        led_states[pin] = int(state)
        if ser and ser.is_open:
            command = f"{pin} {state}"
            ser.write(command.encode('utf-8'))
            print(f"🔌 [{source}] Виконано: {command}")
            
            # Відправляємо статус назад в MQTT (це бачитиме n8n)
            status_topic = f"home/light/{pin}/status"
            mqtt_client.publish(status_topic, state, retain=True)
            return True
        else:
            print("⚠️ Arduino недоступна")
            return False
    except Exception as e:
        print(f"❌ Помилка виконання: {e}")
        return False

# --- MQTT Logic ---
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✅ Підключено до MQTT Брокера ({MQTT_BROKER})")
        # Підписуємось саме тут, щоб при розриві зв'язку підписка поновилася
        client.subscribe(MQTT_COMMAND_TOPIC)
        print(f"📡 Підписано на топік: {MQTT_COMMAND_TOPIC}")
    else:
        print(f"❌ Помилка підключення, код: {rc}")

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = msg.payload.decode().strip()
        
        # Ігноруємо топіки статусів, щоб не було нескінченного циклу
        if "status" in topic:
            return

        print(f"📩 Отримано MQTT: {topic} -> {payload}")

        if payload in ['0', '1']:
            # Витягуємо номер піна з топіка (останнє число)
            try:
                pin = int(topic.split("/")[-1])
                if pin in led_states:
                    # Виконуємо команду, якщо стан змінився
                    if led_states[pin] != int(payload):
                        execute_command(pin, payload, source="MQTT/n8n")
            except ValueError:
                pass
    except Exception as e:
        print(f"❌ Помилка обробки MQTT повідомлення: {e}")

mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# --- Graceful Shutdown ---
def signal_handler(sig, frame):
    print('\n🛑 Зупинка системи...')
    if ser: ser.close()
    mqtt_client.loop_stop()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# --- Telegram Logic ---
# (Твій блок меню та обробники повідомлень залишаються без змін)
def main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1, btn2, btn3, btn4 = [types.KeyboardButton(x) for x in ['🍳 Кухня', '🛁 Ванна', '🚽 Туалет', '🛏 Кімната']]
    markup.add(btn1, btn2, btn3, btn4)
    return markup

@bot.message_handler(commands=['start'])
def start_command(message):
    if message.from_user.id in ALLOWED_USERS:
        bot.reply_to(message, "Система готова. Керуй світлом:", reply_markup=main_menu())

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

if __name__ == "__main__":
    print("🚀 Запуск систем...")
    
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        # loop_start запускає фоновий потік для MQTT, що дозволяє боту працювати паралельно
        mqtt_client.loop_start() 
    except Exception as e:
        print(f"⚠️ Помилка старту MQTT: {e}")

    print("🤖 Бот активований...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
