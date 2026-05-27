import requests
import time
import datetime
from flask import Flask
import threading

# ================= CONFIG =================
TOKEN = "8827942210:AAHXMtVrrcRuMkXuk26Q1JFJqh3q9NhQESM"
CHAT_ID = "1628910342"
URL = "http://skysysx.net/e/boss"

CHECK_INTERVAL = 1          # seconds
ALIVE_INTERVAL = 60         # seconds
REQUEST_TIMEOUT = 5         # seconds
# ==========================================

# ================= FLASK WEB SERVER (For Render) =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running on Render!"

def run_web_server():
    app.run(host='0.0.0.0', port=10000)

# ================= BOT LOGIC =================
def get_current_time():
    return datetime.datetime.now().strftime("%H:%M:%S")

def send_message(text):
    try:
        requests.get(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": text},
            timeout=REQUEST_TIMEOUT
        )
    except Exception as e:
        print("❌ Telegram Error:", e)

def detect_status(page_text):
    text = page_text.lower()
    if any(x in text for x in ["buyer api offline", "submissions are locked", "submission locked", "买家 api已离线", "提交已锁定"]):
        return "offline", "🔴 Buyer OFFLINE"
    elif any(x in text for x in ["input (one per line)", "output (copyable)", "click convert", "convert", "push"]):
        return "online", "🟢 Buyer ONLINE"
    elif any(x in text for x in ["502", "bad gateway", "host error"]):
        return "error", "⚠️ Site Error 502 / Host Error"
    else:
        return "unknown", "❓ Unknown Status"

def check_website():
    try:
        response = requests.get(URL, timeout=REQUEST_TIMEOUT)
        return detect_status(response.text)
    except Exception:
        return "down", "❌ Site Down / Network Error"

def start_bot():
    last_status = None
    last_ping_time = 0
    
    while True:
        current_status, message = check_website()
        current_time = get_current_time()

        if current_status != last_status:
            print(f"[{current_time}] CHANGE → {message}")
            send_message(f"{message} - {current_time}")
            last_status = current_status

        now = time.time()
        if now - last_ping_time > ALIVE_INTERVAL:
            send_message(f"💚 Alive: {current_time}")
            last_ping_time = now

        if current_status == "down":
            send_message(f"⚠️ Bot Owner Offline - {current_time}")

        time.sleep(CHECK_INTERVAL)

# ================= MAIN EXECUTION =================
if __name__ == "__main__":
    # বটকে ব্যাকগ্রাউন্ডে চালানোর জন্য আলাদা থ্রেড
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.start()
    
    # Render-এর জন্য মেইন থ্রেডে ওয়েব সার্ভার রান করা
    run_web_server()
  
