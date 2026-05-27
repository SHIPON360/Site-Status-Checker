import requests
import time
import datetime
from flask import Flask
from threading import Thread

# ================= CONFIG =================
TOKEN = "8529553766:AAGbCA43c868iHOFqoemoGITsXrugF-xx8A"
CHAT_ID = "@cookieslinkserver"
URL = "http://skysysx.net/e/boss"
# ==========================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Alive"

def run_web():
    app.run(host="0.0.0.0", port=10000)

last_status = None
last_ping = 0

def send(msg):
    try:
        requests.get(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg},
            timeout=5
        )
    except:
        pass

def bot_loop():
    global last_status, last_ping

    while True:
        try:
            r = requests.get(URL, timeout=5)
            text = r.text.lower()

            if any(x in text for x in [
                "buyer api offline",
                "submissions are locked",
                "submission locked",
                "买家 api已离线",
                "提交已锁定"
            ]):
                current_status = "offline"
                message = "🔴 Buyer OFFLINE"

            elif any(x in text for x in [
                "input (one per line)",
                "output (copyable)",
                "click convert",
                "convert",
                "push"
            ]):
                current_status = "online"
                message = "🟢 Buyer ONLINE"

            elif any(x in text for x in [
                "502",
                "bad gateway",
                "host error"
            ]):
                current_status = "error"
                message = "⚠️ Site Error 502"

            else:
                current_status = "unknown"
                message = "❓ Unknown Status"

        except:
            current_status = "down"
            message = "❌ Site Down"

        # 🔥 status change → instant alert (NO SPAM)
        if current_status != last_status:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            send(f"{message} | {now}")
            last_status = current_status

        # 💚 alive ping (every 60 sec)
        now_time = time.time()
        if now_time - last_ping > 60:
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            send(f"💚 Alive: {current_time}")
            last_ping = now_time

        time.sleep(2)

# run both server + bot
Thread(target=run_web).start()
bot_loop()
