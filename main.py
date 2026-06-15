import asyncio
import httpx
import time
import logging
import signal
import sys
import random
import os
from datetime import datetime, timezone, timedelta
import threading
from typing import Any
from flask import Flask, jsonify, request
from waitress import serve
from curl_cffi import requests as cffi_requests

# ==========================================
#          APEX-LEVEL CONFIGURATION
# ==========================================
TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
SECURITY_KEY: str | None = os.getenv("APEX_SECURITY_KEY")
CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "@cookieslinkserver")
URL: str = os.getenv("TARGET_API_URL", "https://skysysx.net/api/info")

if not TOKEN or not SECURITY_KEY:
    raise RuntimeError("❌ ERROR: Bot Token or Security Key is missing! Please set them in Render Environment Variables.")

CHECK_INTERVAL: float = 2.0    
ALIVE_INTERVAL: int = 3600     
RETRY_LIMIT: int = 5           
MAX_BACKGROUND_RETRIES: int = 3 

# ==========================================
#           ELITE LOGGING SYSTEM
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ⚡ %(message)s",
    datefmt="%Y-%m-%d %I:%M:%S %p"
)
logger: logging.Logger = logging.getLogger("ApexEngine")

# Strict Bangladesh Standard Time (+6 Hours)
BST: timezone = timezone(timedelta(hours=6))

# ==========================================
#    GLOBAL THREAD-SAFE MONITOR STATE
# ==========================================
state_lock: threading.Lock = threading.Lock() 

monitor_state: dict[str, Any] = {
    "status": "INITIALIZING...",
    "last_check": "N/A",
    "last_alert": "N/A",
    "latency_ms": 0,
    "enabled": True,
    "queue_size": 0,
    "dlq_size": 0,
    "interval": CHECK_INTERVAL,  
    "circuit_limit": 6,          
    "cooldown_429": 1.0,
    "circuit_cooldown": 2.0
}

def update_state(key: str, value: Any) -> None:
    with state_lock:
        monitor_state[key] = value

# ==========================================
#          FLASK DASHBOARD (MONITOR)
# ==========================================
app: Flask = Flask(__name__)
import logging as flask_logging
flask_logging.getLogger('werkzeug').setLevel(flask_logging.ERROR)

@app.route("/")
def dashboard() -> str:
    with state_lock:
        current_state: dict[str, Any] = monitor_state.copy()
        
    return f"""
    <div style="font-family: monospace; background: #0b0c10; color: #66fcf1; padding: 20px; min-height: 100vh;">
        <h2>👑 APEX ENGINE - ENTERPRISE DASHBOARD</h2>
        <p>>_ TARGET API: {URL}</p>
        <p>>_ CURRENT STATUS: <strong style="color: #ffffff; background: #c0392b; padding: 2px 5px;">{current_state['status']}</strong></p>
        <p>>_ CHECK INTERVAL: <strong style="color: #f39c12;">{current_state['interval']} Seconds</strong> ⏱️</p>
        <p>>_ CIRCUIT LIMIT: <strong style="color: #e74c3c;">{current_state['circuit_limit']} Fails</strong> 🛡️</p>
        <p>>_ CIRCUIT COOLDOWN: <strong style="color: #e74c3c;">{current_state['circuit_cooldown']} Seconds</strong> 🔌</p>
        <p>>_ 429 COOLDOWN: <strong style="color: #e74c3c;">{current_state['cooldown_429']} Seconds</strong> ⏳</p>
        <p>>_ LAST PING TIME: {current_state['last_check']}</p>
        <p>>_ LAST ALERT SENT: {current_state['last_alert']}</p>
        <p>>_ NETWORK LATENCY: {current_state['latency_ms']} ms</p>
        <p>>_ ENGINE ACTIVE: {current_state['enabled']}</p>
        <p>>_ ACTIVE QUEUE: {current_state['queue_size']} | DEAD-LETTER (DLQ): {current_state['dlq_size']}</p>
        <hr style="border: 1px solid #45a29e;">
        
        <script>
            async function secureAction(endpoint, payload_data = {{}}) {{
                let key = prompt("Enter Security Key to proceed:");
                if (key) {{
                    payload_data['key'] = key;
                    try {{
                        let response = await fetch(endpoint, {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify(payload_data)
                        }});
                        let text = await response.text();
                        alert(text);
                        location.reload();
                    }} catch (err) {{
                        alert("❌ Request Failed: " + err);
                    }}
                }}
            }}
        </script>

        <button onclick="secureAction('/toggle')" style="background: #45a29e; color: #0b0c10; padding: 10px; font-weight: bold; border: none; cursor: pointer;">[ TOGGLE ENGINE ]</button>
        <button onclick="secureAction('/test')" style="background: #e74c3c; color: white; padding: 10px; font-weight: bold; border: none; cursor: pointer;">[ FIRE TEST SIGNAL ]</button>
        <br><br><br>
        
        <h3 style="color: #a78bfa;">⏱️ SET CHECK INTERVAL (GEAR)</h3>
        <button onclick="secureAction('/set_interval', {{sec: 5.0}})" style="background: #8e44ad; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟣 5 SECONDS ]</button>
        <button onclick="secureAction('/set_interval', {{sec: 4.0}})" style="background: #2980b9; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🔵 4 SECONDS ]</button>
        <button onclick="secureAction('/set_interval', {{sec: 3.0}})" style="background: #27ae60; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟢 3 SECONDS ]</button>
        <button onclick="secureAction('/set_interval', {{sec: 2.0}})" style="background: #f39c12; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟡 2 SECONDS ]</button>
        <button onclick="secureAction('/set_interval', {{sec: 1.0}})" style="background: #c0392b; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🔴 1 SECOND ]</button>
        <br><br>

        <h3 style="color: #a78bfa;">🛡️ SET CIRCUIT BREAKER LIMIT</h3>
        <button onclick="secureAction('/set_circuit', {{limit: 2}})" style="background: #c0392b; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ ULTRA STRICT (2 FAILS) ]</button>
        <button onclick="secureAction('/set_circuit', {{limit: 4}})" style="background: #e67e22; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ STRICT (4 FAILS) ]</button>
        <button onclick="secureAction('/set_circuit', {{limit: 6}})" style="background: #f39c12; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ NORMAL (6 FAILS) ]</button>
        <button onclick="secureAction('/set_circuit', {{limit: 8}})" style="background: #2980b9; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ RELAXED (8 FAILS) ]</button>
        <button onclick="secureAction('/set_circuit', {{limit: 10}})" style="background: #27ae60; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ MAX (10 FAILS) ]</button>
        <br><br>
        
        <h3 style="color: #a78bfa;">🔌 SET CIRCUIT BREAKER COOLDOWN</h3>
        <button onclick="secureAction('/set_circuit_cooldown', {{sec: 5.0}})" style="background: #8e44ad; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟣 5 SECONDS ]</button>
        <button onclick="secureAction('/set_circuit_cooldown', {{sec: 4.0}})" style="background: #2980b9; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🔵 4 SECONDS ]</button>
        <button onclick="secureAction('/set_circuit_cooldown', {{sec: 3.0}})" style="background: #27ae60; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟢 3 SECONDS ]</button>
        <button onclick="secureAction('/set_circuit_cooldown', {{sec: 2.0}})" style="background: #f39c12; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟡 2 SECONDS ]</button>
        <button onclick="secureAction('/set_circuit_cooldown', {{sec: 1.0}})" style="background: #c0392b; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🔴 1 SECOND ]</button>
        <br><br>

        <h3 style="color: #a78bfa;">⏳ SET 429 RATE LIMIT COOLDOWN</h3>
        <button onclick="secureAction('/set_cooldown', {{sec: 5.0}})" style="background: #8e44ad; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟣 5 SECONDS ]</button>
        <button onclick="secureAction('/set_cooldown', {{sec: 4.0}})" style="background: #2980b9; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🔵 4 SECONDS ]</button>
        <button onclick="secureAction('/set_cooldown', {{sec: 3.0}})" style="background: #27ae60; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟢 3 SECONDS ]</button>
        <button onclick="secureAction('/set_cooldown', {{sec: 2.0}})" style="background: #f39c12; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🟡 2 SECONDS ]</button>
        <button onclick="secureAction('/set_cooldown', {{sec: 1.0}})" style="background: #c0392b; color: white; padding: 8px; font-weight: bold; border: none; cursor: pointer;">[ 🔴 1 SECOND ]</button>
        <br><br><br>

        <a href="/status" style="color: #66fcf1; text-decoration: underline;">[ VIEW RAW JSON STATUS ]</a>
    </div>    
    """

@app.route("/toggle", methods=["POST"])
def toggle() -> Any:
    data = request.get_json(silent=True) or {}
    if data.get("key") != SECURITY_KEY:
        logger.warning("Unauthorized TOGGLE attempt blocked!")
        return "❌ ACCESS DENIED: Invalid Security Key!", 403

    with state_lock:
        monitor_state["enabled"] = not monitor_state["enabled"]
        is_active: bool = monitor_state["enabled"]
        current_status = monitor_state["status"]

    if is_active:
        telegram_client.fire_and_forget(f"🟢 অফিস চালু হলো! বায়ারের বর্তমান অবস্থা: {current_status}")
    else:
        telegram_client.fire_and_forget("🔴 অফিস বন্ধ হলো")

    logger.info(f"Engine state changed. Active: {is_active}")
    return f"✅ Action Successful! Engine Active: {is_active}"

@app.route("/test", methods=["POST"])
def test_alert() -> Any:
    data = request.get_json(silent=True) or {}
    if data.get("key") != SECURITY_KEY:
        return "❌ ACCESS DENIED!", 403

    telegram_client.fire_and_forget("🚨 SYSTEM TEST: The Secure Apex Engine is operational!")
    return "✅ Test signal injected!"

@app.route("/set_interval", methods=["POST"])
def set_interval() -> Any:
    data = request.get_json(silent=True) or {}
    if data.get("key") != SECURITY_KEY:
        return "❌ ACCESS DENIED!", 403
    try:
        new_speed = float(data.get("sec", 2.0))
        with state_lock:
            monitor_state["interval"] = new_speed
        telegram_client.fire_and_forget(f"⏱️ Engine Speed Changed: Checking every {new_speed}s!")
        return f"✅ Interval successfully set to {new_speed}s!"
    except Exception as e:
        return f"❌ Error: {e}", 400

@app.route("/set_circuit", methods=["POST"])
def set_circuit() -> Any:
    data = request.get_json(silent=True) or {}
    if data.get("key") != SECURITY_KEY:
        return "❌ ACCESS DENIED!", 403
    try:
        limit = int(data.get("limit", 6))
        with state_lock:
            monitor_state["circuit_limit"] = limit
        return f"✅ Circuit Breaker limit set to {limit} fails!"
    except Exception as e:
        return f"❌ Error: {e}", 400

@app.route("/set_circuit_cooldown", methods=["POST"])
def set_circuit_cooldown() -> Any:
    data = request.get_json(silent=True) or {}
    if data.get("key") != SECURITY_KEY:
        return "❌ ACCESS DENIED!", 403
    try:
        sec = float(data.get("sec", 2.0))
        with state_lock:
            monitor_state["circuit_cooldown"] = sec
        return f"✅ Circuit Breaker Cooldown set to {sec}s!"
    except Exception as e:
        return f"❌ Error: {e}", 400

@app.route("/set_cooldown", methods=["POST"])
def set_cooldown() -> Any:
    data = request.get_json(silent=True) or {}
    if data.get("key") != SECURITY_KEY:
        return "❌ ACCESS DENIED!", 403
    try:
        sec = float(data.get("sec", 1.0))
        with state_lock:
            monitor_state["cooldown_429"] = sec
        return f"✅ 429 Cooldown set to {sec}s!"
    except Exception as e:
        return f"❌ Error: {e}", 400

@app.route("/status", methods=["GET"])
def api_status():
    with state_lock:
        return jsonify(monitor_state)

# ==========================================
#      ASYNC TELEGRAM DELIVERY ENGINE
# ==========================================
loop_ref: asyncio.AbstractEventLoop | None = None 
engine_running: bool = True 

class TelegramClient:
    def __init__(self) -> None:
        limits: httpx.Limits = httpx.Limits(max_connections=10, max_keepalive_connections=10)
        self.client: httpx.AsyncClient = httpx.AsyncClient(http2=True, limits=limits)
        self.failed_queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue(maxsize=1000) 
        self.dlq_count: int = 0

    def fire_and_forget(self, msg: str) -> None:
        if loop_ref is not None and loop_ref.is_running():
            asyncio.run_coroutine_threadsafe(self._process_initial_send(msg), loop_ref)

    async def _process_initial_send(self, msg: str) -> None:
        success: bool = await self._deliver_with_retry(msg)
        if not success:
            if self.failed_queue.full():
                logger.error("❌ Retry queue full.")
                return
            await self.failed_queue.put((msg, 1)) 
            update_state("queue_size", self.failed_queue.qsize())

    async def _deliver_with_retry(self, msg: str) -> bool:
        url: str = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload: dict[str, str] = {"chat_id": CHAT_ID, "text": msg}
        timeout_config: httpx.Timeout = httpx.Timeout(4.0, connect=1.5, read=2.5)
        
        for attempt in range(RETRY_LIMIT):
            try:
                response = await self.client.post(url, json=payload, timeout=timeout_config)
                response.raise_for_status() 
                logger.info(f"SIGNAL DISPATCHED: {msg}")
                update_state("last_alert", datetime.now(BST).strftime("%I:%M:%S %p"))
                return True
            except Exception as e:
                logger.warning(f"Telegram glitch: {e}")
            await asyncio.sleep(0.2)
        return False

    async def background_retry_worker(self) -> None:
        while engine_running:
            try:
                msg, retry_count = await asyncio.wait_for(self.failed_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue 
                
            success: bool = await self._deliver_with_retry(msg)
            if not success:
                if retry_count >= MAX_BACKGROUND_RETRIES:
                    self.dlq_count += 1
                    update_state("dlq_size", self.dlq_count)
                else:
                    await asyncio.sleep(5.0) 
                    await self.failed_queue.put((msg, retry_count + 1))
            self.failed_queue.task_done()
            update_state("queue_size", self.failed_queue.qsize())

    async def close(self) -> None:
        await self.client.aclose()

telegram_client: TelegramClient = TelegramClient()

# ==========================================
#          THE APEX POLING ENGINE
# ==========================================
class EliteMasterBot:
    def __init__(self) -> None:
        self.last_status: str | None = None
        self.last_ping_time: float = time.time()
        self.circuit_breaker_fails: int = 0
        self.timeout_count: int = 0  

    async def execute_engine(self) -> None:
        global loop_ref
        loop_ref = asyncio.get_running_loop()
        logger.info("CORE IGNITION: Async Polling Engine Active.")
        worker_task = asyncio.create_task(telegram_client.background_retry_worker())
        
        try:
            async with cffi_requests.AsyncSession(impersonate="chrome136", timeout=4.0) as scraper:
                while engine_running:
                    with state_lock:
                        is_enabled: bool = monitor_state["enabled"]
                        current_interval: float = monitor_state["interval"]
                        current_circuit_limit: int = monitor_state["circuit_limit"]
                        current_429_cooldown: float = monitor_state["cooldown_429"]
                        current_circuit_cooldown: float = monitor_state["circuit_cooldown"]
                        
                    if not is_enabled:
                        await asyncio.sleep(1.0)
                        continue

                    current_status: str = "unknown"
                    message: str = ""
                    start_time: float = time.perf_counter()
                    
                    if self.circuit_breaker_fails >= current_circuit_limit:
                        await asyncio.sleep(current_circuit_cooldown)
                        try:
                            test = await scraper.get(URL)
                            if test.status_code == 200:
                                self.circuit_breaker_fails = 0
                            else:
                                self.circuit_breaker_fails += 1
                                continue
                        except Exception:
                            self.circuit_breaker_fails += 1
                            continue

                    try:
                        response = await scraper.get(URL)
                        update_state("latency_ms", round((time.perf_counter() - start_time) * 1000))
                        
                        if response.status_code == 429:
                            update_state("status", "RATE LIMITED (429)")
                            await asyncio.sleep(current_429_cooldown)
                            continue
                            
                        elif response.status_code == 200:
                            self.circuit_breaker_fails = 0 
                            self.timeout_count = 0  
                            try:
                                data: dict = response.json()
                                if data.get("api_offline_locked", True):
                                    current_status, message = "offline", "🔴 Buyer OFFLINE"
                                elif data.get("push_locked", False):
                                    current_status, message = "locked", "🔒 Push LOCKED"
                                elif data.get("webhook_status") != "ok":
                                    current_status, message = "webhook_error", f"⚠️ Webhook Error"
                                else:
                                    current_status, message = "online", "🟢 Buyer ONLINE"
                            except:
                                current_status, message = "error", "⚠️ Data Parse Error"
                                
                        else:
                            self.circuit_breaker_fails += 1
                            current_status = self.last_status if self.last_status else "error"
                            if self.circuit_breaker_fails >= 3:
                                current_status = "error"
                                message = f"⚠️ Unknown HTTP Error ({response.status_code})"

                    except Exception as e:
                        if "time" in str(e).lower() or "timeout" in str(e).lower():
                            self.timeout_count += 1
                            if self.timeout_count < 3:
                                await asyncio.sleep(current_interval)
                                continue
                            current_status, message = "down", "❌ Target Connection Timed Out"
                        else:
                            self.circuit_breaker_fails += 1
                            current_status = self.last_status if self.last_status else "down"

                    update_state("status", current_status.upper())
                    
                    if self.last_status is None:
                        self.last_status = current_status
                        continue

                    if current_status != self.last_status:
                        telegram_client.fire_and_forget(f"{message} - {datetime.now(BST).strftime('%I:%M:%S %p')}")
                        self.last_status = current_status

                    if time.time() - self.last_ping_time > ALIVE_INTERVAL:
                        # Fully explicit list of messages to prevent any "shortcut" complaints
                        online_msgs = [
                            "বায়ার লাইনে, কোপাও সবাই! ⚔️", 
                            "বায়ার হাজির, ঝাপাইয়া পড়ো! 🦅", 
                            "বায়ার লাইভ, বস্তা ভরো সবাই! 💰", 
                            "বায়ার একটিভ, উরাধুরা কোপাও! 🪓", 
                            "বায়ার স্পটে, লুটপাট শুরু করো! 🏴‍☠️", 
                            "বায়ার মাঠে, ধরো ধরো সবাই! 🏃‍♂️", 
                            "বায়ার রেডি, লাগাও কোপ ইচ্ছামতো! 🔥", 
                            "বায়ার আইছে, কিবোর্ড ভাইঙ্গা ফেলো! ⌨️", 
                            "বায়ার হাজির, হলুদ ছানারা অ্যাটাক! 🐥", 
                            "বায়ার লকড, সবাই পজিশন নাও! 🚀", 
                            "বায়ার জ্যান্ত, এক্কেরে ছেঁইচা ফেলো! 🥊", 
                            "বায়ার লাইনে, আজকে পুরাই আগুন! 💥"
                        ]
                        
                        offline_msgs = [
                            "বায়ার হাওয়া, সবাই রেস্ট নাও! 🛌", 
                            "বায়ার পালাইছে, কোপানো বন্ধ! 🛑", 
                            "বায়ার গায়েব, চিল করো সবাই! 😎", 
                            "বায়ার লাপাত্তা, অস্ত্র রাইখা দাও! 🛡️", 
                            "বায়ার নাই, সবাই চা-পানি খাও! ☕", 
                            "বায়ার ডরে পালাইছে, ছানা হতাশ! 🐥", 
                            "বায়ার পলটি নিছে, রিলাক্স করো সবাই! 🧘‍♂️", 
                            "বায়ার অফলাইনে, আজকে আর খেলা নাই! ❌", 
                            "বায়ার ভাইগা গেছে, তোমরা ওয়েট করো! ⏳", 
                            "বায়ার নাইকা, বস্তা সরাইয়া রাখো! 🎒", 
                            "বায়ার ফিনিশ, ঘুমাও সবাই শান্তিতে! 😴", 
                            "বায়ার অফলাইন, ম্যাডামরে সময় দাও! 👩‍❤️‍👨"
                        ]
                        
                        random_msg = ""
                        if self.last_status == "online":
                            random_msg = random.choice(online_msgs)
                            telegram_client.fire_and_forget(f"💚 {random_msg} - {datetime.now(BST).strftime('%I:%M:%S %p')}")
                        else:
                            random_msg = random.choice(offline_msgs)
                            telegram_client.fire_and_forget(f"💔 {random_msg} - {datetime.now(BST).strftime('%I:%M:%S %p')}")
                        
                        self.last_ping_time = time.time()

                    await asyncio.sleep(current_interval)

        finally:
            await telegram_client.close()
            worker_task.cancel() 

def run_apex_loop() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(EliteMasterBot().execute_engine())
    finally:
        loop.close()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)
    threading.Thread(target=run_apex_loop, daemon=False).start()
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
