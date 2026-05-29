import requests
import time
import datetime
import threading
from flask import Flask, request, jsonify

# ==========================================
#                  CONFIG
# ==========================================
TOKEN = "8529553766:AAGbCA43c868iHOFqoemoGITsXrugF-xx8A"   # WARNING: Put your Telegram Bot Token here
CHAT_ID = "@cookieslinkserver"   # WARNING: Put your Telegram Chat ID here
URL = "http://skysysx.net/e/boss"    # WARNING: Put the Target Website URL here

CHECK_INTERVAL = 3      # Normal delay between each check (in seconds)
ALIVE_INTERVAL = 3600   # Sends an 'Alive' ping every 1 hour (3600 seconds)
RETRY_LIMIT = 3         # Number of times it will try to send a failed message

# ==========================================
#                  STATE
# ==========================================
last_status = "starting"
last_check_time = "N/A"
last_alert_time = "N/A"
last_ping_time = time.time()
bot_enabled = True
message_queue = []

# ==========================================
#                FLASK APP
# ==========================================
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

# ==========================================
#              SEND MESSAGE
# ==========================================
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
        except Exception as e:
            pass
        time.sleep(1)

    # If all retries fail, save it to the queue to send later
    if not success:
        message_queue.append(msg)

# ==========================================
#             MESSAGE QUEUE
# ==========================================
def process_queue():
    while True:
        if message_queue:
            msg = message_queue.pop(0)
            send(msg)
        time.sleep(2)

# ==========================================
#             MAIN BOT LOOP
# ==========================================
def bot_loop():
    global last_status, last_check_time, last_alert_time, last_ping_time
    
    # Fake Browser Headers to bypass Firewall
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    while True:
        if not bot_enabled:
            time.sleep(2)
            continue

        try:
            res = requests.get(URL, headers=headers, timeout=10)
            text = res.text.lower()
            status_code = res.status_code
            
            # 0. Anti-Ban (Soft block 429) - Silent Retry without changing status
            if status_code == 429 or "too many requests" in text:
                print("Soft block (429) hit! Silently retrying...")
                time.sleep(CHECK_INTERVAL)
                continue 
            
            # Text conditions mapping
            has_offline_text = any(x in text for x in ["buyer api offline", "submissions are locked", "买家 api已离线"])
            has_online_text = any(x in text for x in ["input (one per line)", "output (copyable)", "click convert"])
            
            # Print debug logs to Render console
            print(f"Code: {status_code} | Offline: {has_offline_text} | Online: {has_online_text}")

            # 1. Strict OFFLINE Check (Pop-up detected)
            if has_offline_text:
                current_status = "offline"
                message = "🔴 Buyer OFFLINE"
                
            # 2. Strict ONLINE Check
            elif has_online_text:
                current_status = "online"
                message = "🟢 Buyer ONLINE"
                
            # 3. Server Error Check
            elif status_code in [502, 503] or "bad gateway" in text:
                current_status = "error"
                message = f"⚠️ Site Error {status_code}"
                
            # 4. Unknown Status Check
            else:
                current_status = "unknown"
                message = "❓ Unknown Status"

        except Exception as e:
            current_status = "down"
            message = "❌ Site Down"
            print(f"Error fetching site: {e}")

        # Time Formatting (+6 Hours for Bangladesh Standard Time)
        now_time_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=6)).strftime("%I:%M:%S %p")
        last_check_time = now_time_str

        # Status Change Alert (Triggers only when status changes)
        if current_status != last_status:
            send(f"{message} - {now_time_str}")
            last_alert_time = now_time_str
            last_status = current_status

        # Alive Ping Checker
        now_time = time.time()
        if now_time - last_ping_time > ALIVE_INTERVAL:
            send(f"💚 Alive: {now_time_str}")
            last_ping_time = now_time

        # Normal Delay
        time.sleep(CHECK_INTERVAL)

# ==========================================
#                   RUN
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=process_queue, daemon=True).start()
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
        
