import requests
import time
import datetime
import threading
from flask import Flask, request, jsonify

# ============== CONFIG ==============
TOKEN = "8529553766:AAGbCA43c868iHOFqoemoGITsXrugF-xx8A"
CHAT_ID = "@cookieslinkserver"
URL = "http://skysysx.net/e/boss"

CHECK_INTERVAL = 2
ALIVE_INTERVAL = 300
RETRY_LIMIT = 3

# ============== STATE ==============
last_status = "starting"
last_check_time = "N/A"
last_alert_time = "N/A"
last_ping_time = time.time()
bot_enabled = True
message_queue = []

# ============== FLASK APP ==============
app = Flask(__name__)

@app.route("/")
def dashboard():
    return f"""
    <h2>🤖 Bot Dashboard</h2>
    <p>Status: {last_status}</p>
    <p>Last Check: {last_check_time}</p>
    <p>Last Alert: {last_alert_time}</p>
    <p>Bot Enabled: {bot_enabled}</p>

    <hr>

    <a href="/toggle">🔁 Toggle Bot ON/OFF</a><br><br>
    <a href="/test">🚨 Send Test Alert</a>
    """

@app.route("/toggle")
def toggle():
    global bot_enabled
    bot_enabled = not bot_enabled
    return f"Bot Enabled: {bot_enabled}"

@app.route("/test")
def test_alert():
    send("🚨 TEST ALERT")
    return "Test message sent to Telegram!"

@app.route("/status")
def api_status():
    return jsonify({
        "status": last_status,
        "last_check": last_check_time,
        "last_alert": last_alert_time,
        "bot_enabled": bot_enabled
    })

# ============== SEND ==============
def send(msg):
    success = False

    for _ in range(RETRY_LIMIT):
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                params={"chat_id": CHAT_ID, "text": msg},
                timeout=5
            )
            if r.status_code == 200:
                success = True
                break
        except:
            pass
        time.sleep(1)

    if not success:
        message_queue.append(msg)

# ============== QUEUE ==============
def process_queue():
    while True:
        if message_queue:
            msg = message_queue.pop(0)
            send(msg)
        time.sleep(2)

# ============== BOT LOOP ==============
def bot_loop():
    global last_status, last_check_time, last_alert_time, last_ping_time

    while True:
        if not bot_enabled:
            time.sleep(2)
            continue

        try:
            text = requests.get(URL, timeout=5).text.lower()
            
            if any(x in text for x in ["buyer api offline", "submissions are locked", "submission locked", "买家 api已离线", "提交已锁定"]):
                current_status = "offline"
                message = "🔴 Buyer OFFLINE"
            elif any(x in text for x in ["input (one per line)", "output (copyable)", "click convert", "convert", "push"]):
                current_status = "online"
                message = "🟢 Buyer ONLINE"
            elif "502" in text or "bad gateway" in text:
                current_status = "error"
                message = "⚠️ Site Error 502"
            else:
                current_status = "unknown"
                message = "❓ Unknown Status"

        except:
            current_status = "down"
            message = "❌ Site Down"

        now_time_str = datetime.datetime.now().strftime("%H:%M:%S")
        last_check_time = now_time_str

        # 🔥 status change alert
        if current_status != last_status:
            send(f"{message} | {now_time_str}")
            last_alert_time = now_time_str
            last_status = current_status

        # 💚 alive ping
        now_time = time.time()
        if now_time - last_ping_time > ALIVE_INTERVAL:
            send(f"💚 Alive: {now_time_str}")
            last_ping_time = now_time

        time.sleep(CHECK_INTERVAL)

# ============== RUN ==============
if __name__ == "__main__":
    threading.Thread(target=process_queue, daemon=True).start()
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
            
