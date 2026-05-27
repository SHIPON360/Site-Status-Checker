import requests
import time
import datetime
from flask import Flask
import threading

# ================= CONFIG =================
TOKEN = "8529553766:AAGbCA43c868iHOFqoemoGITsXrugF-xx8A"
CHAT_ID = "@cookieslinkserver"
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

# ================= BOT LOGIC (তোমার অরিজিনাল কোড) =================
last_status = None
last_ping_time = 0

def get_current_time():
    """Return formatted current time"""
    return datetime.datetime.now().strftime("%H:%M:%S")

def send_message(text):
    """Send message to Telegram safely"""
    try:
        requests.get(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            params={
                "chat_id": CHAT_ID,
                "text": text
            },
            timeout=REQUEST_TIMEOUT
        )
    except Exception as e:
        print("❌ Telegram Error:", e)

def detect_status(page_text):
    """Determine current site status"""
    text = page_text.lower()

    if any(x in text for x in [
        "buyer api offline",
        "submissions are locked",
        "submission locked",
        "买家 api已离线",
        "提交已锁定"
    ]):
        return "offline", "🔴 Buyer OFFLINE"

    elif any(x in text for x in [
        "input (one per line)",
        "output (copyable)",
        "click convert",
        "convert",
        "push"
    ]):
        return "online", "🟢 Buyer ONLINE"

    elif any(x in text for x in [
        "502",
        "bad gateway",
        "host error"
    ]):
        return "error", "⚠️ Site Error 502 / Host Error"

    else:
        return "unknown", "❓ Unknown Status"

def check_website():
    """Fetch website and return status"""
    try:
        response = requests.get(URL, timeout=REQUEST_TIMEOUT)
        return detect_status(response.text)
    except Exception:
        return "down", "❌ Site Down / Network Error"

def start_bot():
    global last_status, last_ping_time
    # ================= MAIN LOOP =================
    while True:
        current_status, message = check_website()
        current_time = get_current_time()

        # 🔥 Status Change Alert
        if current_status != last_status:
            print(f"[{current_time}] CHANGE → {message}")
            send_message(f"{message} - {current_time}")
            last_status = current_status

        # 💚 Alive Ping
        now = time.time()
        if now - last_ping_time > ALIVE_INTERVAL:
            send_message(f"💚 Alive: {current_time}")
            last_ping_time = now

        # 🚫 Bot Owner Offline (every time if down)
        if current_status == "down":
            send_message(f"⚠️ Bot Owner Offline - {current_time}")

        # ⏱ Interval Control
        time.sleep(CHECK_INTERVAL)

# ================= MAIN EXECUTION =================
if __name__ == "__main__":
    # তোমার বট ব্যাকগ্রাউন্ডে চলবে
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.start()
    
    # Render-কে সজাগ রাখার জন্য ওয়েব সার্ভার
    run_web_server()
    
