import asyncio
import httpx
import time
import logging
import signal
import sys
import random
from datetime import datetime, timezone, timedelta
import threading
from typing import Any
from flask import Flask, jsonify, request
from waitress import serve

# ==========================================
#          APEX-LEVEL CONFIGURATION
# ==========================================
TOKEN: str = "8529553766:AAGbCA43c868iHOFqoemoGITsXrugF-xx8A"   # WARNING: Insert Telegram Bot Token
CHAT_ID: str = "@cookieslinkserver"   # WARNING: Insert Telegram Chat ID
URL: str = "https://skysysx.net/api/info"    

# 🔐 SECURITY CONFIGURATION
SECURITY_KEY: str = "4268!?Sk"  # WARNING: Change this to your secret password!

CHECK_INTERVAL: float = 2.0    # 2.0 Second Absolute Polling
ALIVE_INTERVAL: int = 3600     
RETRY_LIMIT: int = 5           
MAX_BACKGROUND_RETRIES: int = 3 # Dead-Letter Queue Limit

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

# 100% RAM-based state (No slow Disk I/O)
monitor_state: dict[str, Any] = {
    "status": "INITIALIZING...",
    "last_check": "N/A",
    "last_alert": "N/A",
    "latency_ms": 0,
    "enabled": True,
    "queue_size": 0,
    "dlq_size": 0
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
    <div style="font-family: monospace; background: #0b0c10; color: #66fcf1; padding: 20px; height: 100vh;">
        <h2>👑 APEX ENGINE - ENTERPRISE DASHBOARD</h2>
        <p>>_ TARGET API: {URL}</p>
        <p>>_ CURRENT STATUS: <strong style="color: #ffffff;">{current_state['status']}</strong></p>
        <p>>_ LAST PING TIME: {current_state['last_check']}</p>
        <p>>_ LAST ALERT SENT: {current_state['last_alert']}</p>
        <p>>_ NETWORK LATENCY: {current_state['latency_ms']} ms</p>
        <p>>_ ENGINE ACTIVE: {current_state['enabled']}</p>
        <p>>_ ACTIVE QUEUE: {current_state['queue_size']} | DEAD-LETTER (DLQ): {current_state['dlq_size']}</p>
        <hr style="border: 1px solid #45a29e;">
        
        <script>
            function secureAction(action) {{
                let key = prompt("Enter Security Key to proceed:");
                if (key) {{
                    window.location.href = "/" + action + "?key=" + encodeURIComponent(key);
                }}
            }}
        </script>

        <a href="javascript:secureAction('toggle')" style="background: #45a29e; color: #0b0c10; padding: 10px; text-decoration: none; font-weight: bold;">[ TOGGLE ENGINE ]</a>
        <br><br><br>
        <a href="javascript:secureAction('test')" style="background: #e74c3c; color: white; padding: 10px; text-decoration: none; font-weight: bold;">[ FIRE TEST SIGNAL ]</a>
        <br><br><br>
        <a href="/status" style="color: #66fcf1; text-decoration: underline;">[ VIEW RAW JSON STATUS ]</a>
    </div>    
    """

@app.route("/toggle")
def toggle() -> Any:
    # 🔐 STRICT SECURITY CHECK
    if request.args.get("key") != SECURITY_KEY:
        logger.warning("Unauthorized TOGGLE attempt blocked!")
        return "❌ ACCESS DENIED: Invalid Security Key!", 403

    with state_lock:
        monitor_state["enabled"] = not monitor_state["enabled"]
        is_active: bool = monitor_state["enabled"]
    logger.info(f"Engine state changed. Active: {is_active}")
    return f"✅ Action Successful! Engine Active: {is_active} <br><br> <a href='/'>[ Go Back to Dashboard ]</a>"

@app.route("/test")
def test_alert() -> Any:
    # 🔐 STRICT SECURITY CHECK
    if request.args.get("key") != SECURITY_KEY:
        logger.warning("Unauthorized TEST SIGNAL attempt blocked!")
        return "❌ ACCESS DENIED: Invalid Security Key!", 403

    if loop_ref:
        asyncio.run_coroutine_threadsafe(
            telegram_client.fire_and_forget("🚨 SYSTEM TEST: The Secure Apex Engine is fully operational!"), 
            loop_ref
        )
    return "✅ Test signal injected instantly! <br><br> <a href='/'>[ Go Back to Dashboard ]</a>"

@app.route("/status")
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
        self.failed_queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue() 
        self.dlq_count: int = 0

    async def fire_and_forget(self, msg: str) -> None:
        """Rocket Speed: Non-blocking instant delivery."""
        asyncio.create_task(self._process_initial_send(msg))

    async def _process_initial_send(self, msg: str) -> None:
        success: bool = await self._deliver_with_retry(msg)
        if not success:
            await self.failed_queue.put((msg, 1)) 
            update_state("queue_size", self.failed_queue.qsize())
            logger.error("Signal moved to background retry queue.")

    async def _deliver_with_retry(self, msg: str) -> bool:
        url: str = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload: dict[str, str] = {"chat_id": CHAT_ID, "text": msg}
        timeout_config: httpx.Timeout = httpx.Timeout(4.0, connect=1.5, read=2.5)
        
        for attempt in range(RETRY_LIMIT):
            try:
                response = await self.client.post(url, json=payload, timeout=timeout_config)
                response.raise_for_status() 
                
                logger.info(f"SIGNAL DISPATCHED SUCCESSFULLY: {msg}")
                update_state("last_alert", datetime.now(BST).strftime("%I:%M:%S %p"))
                return True
                
            except httpx.TimeoutException:
                logger.warning(f"Telegram timeout (Attempt {attempt+1}/{RETRY_LIMIT})")
            except httpx.RequestError as e:
                logger.warning(f"Telegram network glitch: {e}")
            except httpx.HTTPStatusError as e:
                logger.warning(f"Telegram API rejected payload: {e}")
            except Exception as e:
                logger.error(f"Unexpected Telegram error: {e}")
            
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
                    logger.error("DEAD-LETTER QUEUE (DLQ): Message dropped after max retries.")
                else:
                    await asyncio.sleep(5.0) 
                    await self.failed_queue.put((msg, retry_count + 1))
                    
            self.failed_queue.task_done()
            update_state("queue_size", self.failed_queue.qsize())

    async def close(self) -> None:
        await self.client.aclose()
        logger.info("Telegram client connections safely closed.")

telegram_client: TelegramClient = TelegramClient()

# ==========================================
#          THE APEX POLING ENGINE
# ==========================================
class EliteMasterBot:
    def __init__(self) -> None:
        self.last_status: str = "starting"
        self.last_ping_time: float = time.time()
        self.circuit_breaker_fails: int = 0

    async def execute_engine(self) -> None:
        global loop_ref
        loop_ref = asyncio.get_running_loop()

        logger.info("CORE IGNITION: Async Polling Engine Active. HTTP/2 Multiplexing Enabled.")
        worker_task = asyncio.create_task(telegram_client.background_retry_worker())
        
        headers: dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
        
        limits: httpx.Limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        timeout_config: httpx.Timeout = httpx.Timeout(6.0, connect=2.0, read=4.0)
        
        try:
            async with httpx.AsyncClient(http2=True, headers=headers, limits=limits) as client:
                
                while engine_running:
                    with state_lock:
                        is_enabled: bool = monitor_state["enabled"]
                        
                    if not is_enabled:
                        await asyncio.sleep(1.0)
                        continue

                    current_status: str = "unknown"
                    message: str = ""
                    start_time: float = time.perf_counter()
                    
                    try:
                        # 9.7/10: Smart Circuit Breaker (Prevents perma-bans)
                        if self.circuit_breaker_fails >= 6:
                            logger.warning("CIRCUIT BREAKER OPEN: Target server unstable. Cooldown (2s)...")
                            await asyncio.sleep(2.0)
                            self.circuit_breaker_fails = 0
                            continue

                        response = await client.get(URL, timeout=timeout_config)
                        latency: int = round((time.perf_counter() - start_time) * 1000)
                        update_state("latency_ms", latency)
                        
                        status_code: int = response.status_code
                        
                        # 9.7/10: Smart 429 Evasion
                        if status_code == 429:
                            logger.warning(f"THROTTLED (429): Rate limit hit. Latency: {latency}ms")
                            await asyncio.sleep(1.0)
                            continue
                            
                        if status_code == 200:
                            self.circuit_breaker_fails = 0 
                            try:
                                data: dict = response.json()
                                is_offline: bool = data.get("api_offline_locked", True)
                                
                                current_status = "offline" if is_offline else "online"
                                message = "🔴 Buyer OFFLINE" if is_offline else "🟢 Buyer ONLINE"
                            except Exception as json_err:
                                current_status = "error"
                                message = "⚠️ Data Parse Error"
                                logger.error(f"Failed to read JSON: {json_err}")
                                
                        elif status_code in [502, 503, 504]:
                            current_status = "error"
                            message = f"⚠️ Target Server Down (Code {status_code})"
                            self.circuit_breaker_fails += 1
                            
                        else:
                            current_status = "error"
                            message = f"⚠️ Unknown HTTP Error ({status_code})"
                            self.circuit_breaker_fails += 1

                    except httpx.TimeoutException:
                        current_status = "down"
                        message = "❌ Target Connection Timed Out"
                        self.circuit_breaker_fails += 1
                        logger.warning("Polling Timeout.")
                    except httpx.RequestError as req_err:
                        current_status = "down"
                        message = "❌ Network Socket Drop"
                        self.circuit_breaker_fails += 1
                        logger.warning(f"Network error: {req_err}")
                    except Exception as e:
                        current_status = "down"
                        message = "❌ Unexpected Core Error"
                        self.circuit_breaker_fails += 1
                        logger.error(f"Core error: {e}")

                    now_str: str = datetime.now(BST).strftime("%I:%M:%S %p")
                    update_state("last_check", now_str)
                    update_state("status", current_status.upper())

                    # INSTANT PARADIGM SHIFT: Firing immediately on ANY status change
                    if current_status != self.last_status:
                        await telegram_client.fire_and_forget(f"{message} - {now_str}")
                        self.last_status = current_status
                        logger.info(f"PARADIGM SHIFT DETECTED: -> {current_status.upper()}")

                    # System Heartbeat (24 Funny Messages)
                    current_epoch: float = time.time()
                    if current_epoch - self.last_ping_time > ALIVE_INTERVAL:
                        funny_msgs = [
                            "বায়ার কি কিস্তির ভয়ে পালালো? 🏃‍♂️",
                            "বায়ার আইলে বস্তায় ভরুম! 🥔",
                            "ম্যাডামের কসম, বায়াররে ছাড়ুম না! 🤞",
                            "বায়ারের নেটে কি ইঁদুরে কাটছে? 🐀",
                            "হলুদ ছানা রেডি, বায়ার গায়েব! 🐥",
                            "বায়ার কি লুডু খেলতেছে? 🎲",
                            "বায়ার আইলে কান ধইরা আনুম! 👂",
                            "বায়ারের পিসিতে শিওর ভাইরাস! 🦠",
                            "বায়ার কি ছ্যাকা খাইছে? 💔",
                            "বায়ারের মনে হয় এমবি শেষ! 📉",
                            "বায়ার আইলে গামছা দিয়া বান্ধুম! 🧣",
                            "বায়ার কি আজ রোজা রাখছে? 🤐",
                            "চা ঠান্ডা হইয়া গেলো, বায়ার কই! ☕",
                            "বায়ারের আইপিতে জিনে ধরছে! 🧞‍♂️",
                            "বায়ারকে খুঁজতে পুলিশ ডাকুম? 🚓",
                            "বায়ার আসলেই জরিমানা করুম! 💸",
                            "বায়ার কি ভিনগ্রহে গেলো? 👽",
                            "বায়ারের অপেক্ষায় চোখ ট্যারা! 😵‍💫",
                            "বায়ার আইলে মুরগি জবাই! 🐓",
                            "বায়ার মনে হয় বাথরুমে গেছে! 🚽",
                            "বায়ারের মনে হয় কারেন্ট নাই! 🕯️",
                            "বায়ার আসলেই সাইরেন বাজবে! 🚨",
                            "আমি সজাগ, বায়ার লাপাত্তা! 🤦‍♂️",
                            "বায়ার কি রাস্তা ভুলা গেছে? 🤷‍♂️"
                        ]
                        random_msg = random.choice(funny_msgs)
                        await telegram_client.fire_and_forget(f"💚 {random_msg} - {now_str}")
                        self.last_ping_time = current_epoch

                    await asyncio.sleep(CHECK_INTERVAL)

        finally:
            await telegram_client.close()
            worker_task.cancel() 
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

def run_apex_loop() -> None:
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot: EliteMasterBot = EliteMasterBot()
    try:
        loop.run_until_complete(bot.execute_engine())
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()

# Graceful Shutdown Handler
def handle_sigterm(*args: Any) -> None:
    global engine_running
    logger.info("RECEIVED SHUTDOWN SIGNAL. Initiating Graceful Shutdown...")
    engine_running = False
    sys.exit(0)

# ==========================================
#          MASTER BOOT RECORD (RUN)
# ==========================================
if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)

    threading.Thread(target=run_apex_loop, daemon=True, name="CoreEngineThread").start()
    
    logger.info("Starting Production WSGI Server (Waitress) on port 10000...")
    serve(app, host="0.0.0.0", port=10000)
