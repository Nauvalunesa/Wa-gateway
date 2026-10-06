import os
import logging
logging.getLogger("neonize").setLevel(logging.WARNING)
import asyncio
import sys
import secrets
import time
from copy import deepcopy
from datetime import datetime
from contextlib import asynccontextmanager
import aiosqlite
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Form, Depends, Header, File, UploadFile, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
import shutil
import subprocess
import tempfile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Dict, List, Union, Any, Literal
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

# Password hashing setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)

from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

from neonize_runtime import GatewayClient as NewAClient
from neonize.utils.enum import VoteType
from neonize.aioze.events import ConnectedEv, MessageEv, DisconnectedEv, LoggedOutEv, QREv, ConnectFailureEv, KeepAliveTimeoutEv, KeepAliveRestoredEv, CallOfferEv, NewsletterJoinEv
from neonize.proto.Neonize_pb2 import JID
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message as WAMessage, ContextInfo, ExtendedTextMessage, InteractiveMessage, AIRichResponseMessage, FutureProofMessage, MessageContextInfo
from neonize.proto.waAICommonDeprecated.WAAICommonDeprecated_pb2 import AIRichResponseSubMessage
from neonize.proto.waAICommon.WAWebProtobufsAICommon_pb2 import AIRichResponseUnifiedResponse, BotMetadata, ForwardedAIBotMessageInfo
from google.protobuf.json_format import ParseDict, MessageToDict, ParseError
import json
from serialize import Mess, str_to_jid
from msg_store import store as ms
from neonize.ext.interactive_message import (
    AIRichMessage,
    Source as AIRichSource,
    Product as AIRichProduct,
    Reel as AIRichReel,
    Post as AIRichPost,
    ButtonV2Message,
)

AIRICH_CARDS = {
    "source": AIRichSource,
    "product": AIRichProduct,
    "reels": AIRichReel,
    "post": AIRichPost,
}

# ... (imports)

async def get_mentions_list(client, target_jid, mentions_str):
    if not mentions_str:
        return []

    mentioned_jids = []
    # Split by comma for multiple targets
    parts = mentions_str.split(",")

    for p in parts:
        p = p.strip()
        if not p: continue

        # Handle "all" for groups (only if not Status)
        if p.lower() == "all" and target_jid.Server == "g.us":
            try:
                info = await client.get_group_info(target_jid)
                for participant in info.Participants:
                    jid = participant.JID
                    if jid.Server == "lid":
                        try:
                            res = await client.get_pn_from_lid(jid)
                            if res: jid = res
                        except: pass
                    mentioned_jids.append(f"{jid.User}@{jid.Server}")
            except: pass
            continue

        # Handle explicit Group JID (expand it) - THIS IS FOR STATUS GROUP TAGGING
        if "@g.us" in p:
            try:
                g_jid = str_to_jid(p)
                info = await client.get_group_info(g_jid)
                print(f"📢 Expanding {len(info.Participants)} members from group {p} for tagging...")
                for participant in info.Participants:
                    jid = participant.JID
                    # Always try to convert to PN JID for Status mentions to work for non-contacts
                    if jid.Server == "lid":
                        try:
                            res = await client.get_pn_from_lid(jid)
                            if res: jid = res
                        except: pass
                    mentioned_jids.append(f"{jid.User}@{jid.Server}")
            except Exception as e:
                print(f"⚠️ Failed to expand group for mentions: {e}")
            continue

        # Handle individual JID or Phone Number
        if "@" in p:
            mentioned_jids.append(p)
        else:
            mentioned_jids.append(normalize_wa(p) + "@s.whatsapp.net")

    # Return unique list
    final_list = list(set(mentioned_jids))
    print(f"✅ Total unique mentions: {len(final_list)}")
    return final_list

async def process_video(url: str, request: Request = None, hd: bool = False) -> str:
    """
    Returns the original URL without compression.
    (Compression via FFmpeg was disabled as requested)
    """
    return url

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_system_db()
    for item in os.listdir("storage"):
        if item == "system.db": continue
        user_dir = os.path.join("storage", item)
        if os.path.isdir(user_dir):
            await init_user_db(item)
            sessions_dir = os.path.join(user_dir, "sessions")
            if os.path.exists(sessions_dir):
                for session_file in os.listdir(sessions_dir):
                    if session_file.endswith(".sqlite3"):
                        phone = session_file.replace(".sqlite3", "")
                        if phone == "session": continue

                        start_neonize(item, phone)

    yield

    # Shutdown
    print("🔌 Shutting down WhatsApp Gateway...")
    for user, client in list(clients.items()):
        try:
            if asyncio.iscoroutinefunction(client.disconnect):
                await client.stop()
            else:
                client.disconnect()
        except:
            pass

app = FastAPI(
    title="WhatsApp Multi-Session Gateway",
    description="A FastAPI gateway for WhatsApp using neonize supporting multiple sessions & API Keys",
    version="1.5.0",
    lifespan=lifespan
)


# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def restrict_internal_routes(request: Request, call_next):
    public_prefixes = ["/assets/", "/favicon.svg", "/api/send-", "/api/status", "/api/check-", "/api/device/", "/api/groups", "/api/group-info", "/api/convert-jid", "/api/newsletter/", "/api/airich/", "/api/passkey/", "/api/blast", "/docs", "/openapi.json", "/static"]
    if not any(request.url.path.startswith(prefix) for prefix in public_prefixes):
        host = request.headers.get("host", "")
        allowed = os.getenv("GATEWAY_ALLOWED_HOSTS", "utusan.chat,localhost:8880,127.0.0.1:8880,localhost:5173,127.0.0.1:5173,testserver").split(",")
        if host not in allowed:
            return HTMLResponse("Host tidak diizinkan", status_code=403)
    response = await call_next(request)
    return response

# Persist the cookie signing key across restarts without hardcoding credentials.
os.makedirs("storage", exist_ok=True)
_secret_file = os.path.join("storage", ".session-secret")
if not os.path.exists(_secret_file):
    with open(_secret_file, "w") as secret_file:
        secret_file.write(secrets.token_hex(32))
    os.chmod(_secret_file, 0o600)
with open(_secret_file) as secret_file:
    session_secret = os.getenv("GATEWAY_SESSION_SECRET") or secret_file.read().strip()
app.add_middleware(SessionMiddleware, secret_key=session_secret, same_site="lax",
                   https_only=os.getenv("GATEWAY_SECURE_COOKIE", "false").lower() == "true")

# Ensure upload directory exists
os.makedirs("static/uploads", exist_ok=True)

@app.post("/api/upload", include_in_schema=False)
async def upload_file(request: Request, file: UploadFile = File(...)):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")

    file_ext = os.path.splitext(file.filename)[1]
    file_name = f"{secrets.token_hex(8)}{file_ext}"
    file_path = os.path.join("static/uploads", file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Return the full URL that can be accessed by the bot
    # We use request.base_url to get the current domain
    base_url = str(request.base_url).rstrip("/")
    return {"success": True, "url": f"{base_url}/static/uploads/{file_name}"}

os.makedirs("storage", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
# ... (imports)
clients: Dict[str, NewAClient] = {}
bot_status: Dict[str, bool] = {}
bot_numbers: Dict[str, str] = {}
pairing_sessions = set() # Track sessions that are currently pairing
client_cleanup_tasks = set()
passkey_requests: Dict[str, Any] = {}
passkey_confirmations: Dict[str, Any] = {}
passkey_errors: Dict[str, Any] = {}
airich_auto_rules: Dict[str, List[Dict[str, Any]]] = {}
airich_auto_seen: Dict[str, float] = {}
airich_auto_last: Dict[tuple[str, str, str], float] = {}
system_db_path = "storage/system.db"


def get_airich_auto_rules(username: str) -> List[Dict[str, Any]]:
    if username not in airich_auto_rules:
        path = os.path.join("storage", username, "config", "airich_auto_replies.json")
        try:
            with open(path, encoding="utf-8") as source:
                saved = json.load(source)
            airich_auto_rules[username] = saved if isinstance(saved, list) else []
        except FileNotFoundError:
            airich_auto_rules[username] = []
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Could not load AI Rich auto-replies for %s: %s", username, exc)
            airich_auto_rules[username] = []
    return airich_auto_rules[username]


def save_airich_auto_rules(username: str, rules: List[Dict[str, Any]]) -> None:
    path = os.path.join("storage", username, "config", "airich_auto_replies.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as destination:
        json.dump(rules, destination, ensure_ascii=False)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)
    airich_auto_rules[username] = rules

# =======================
# DATABASE SETUP
# =======================
async def init_system_db():
    async with aiosqlite.connect(system_db_path) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                email TEXT UNIQUE,
                is_verified INTEGER DEFAULT 0,
                api_key TEXT UNIQUE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                otp TEXT,
                expires_at DATETIME
            )
        ''')
        # Try to upgrade older DB
        try:
            await db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        except: pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0")
        except: pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN api_key TEXT UNIQUE")
        except: pass

        # (Default admin seeding removed — operators register their own
        # account via the /register page. No built-in admin/admin credential.)
        await db.commit()

async def init_user_db(username: str):
    base_path = f"storage/{username}"
    os.makedirs(f"{base_path}/sessions", exist_ok=True)
    os.makedirs(f"{base_path}/history", exist_ok=True)
    os.makedirs(f"{base_path}/config", exist_ok=True)
    os.makedirs(f"{base_path}/device", exist_ok=True)

    db_path = f"{base_path}/history/logs.db"
    async with aiosqlite.connect(db_path) as db:
        # Check if we need to migrate old schema
        try:
            # Check for sender_id column
            async with db.execute("PRAGMA table_info(logs)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if columns and "sender_id" in columns:
                    print(f"🔄 Migrating logs database for {username}...")
                    await db.execute("ALTER TABLE logs RENAME COLUMN sender_id TO sender")
                    await db.execute("ALTER TABLE logs RENAME COLUMN chat_id TO receiver")
                    await db.execute("ALTER TABLE logs RENAME COLUMN message_text TO message")
                    await db.execute("ALTER TABLE logs ADD COLUMN type TEXT DEFAULT 'SYSTEM'")
        except Exception as e:
            print(f"⚠️ Migration note for {username}: {e}")

        await db.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sender TEXT,
                receiver TEXT,
                message TEXT,
                type TEXT
            )
        ''')
        await db.commit()

async def log_message(username: str, sender: str, receiver: str, message: str, msg_type: str = "SYSTEM"):
    db_path = f"storage/{username}/history/logs.db"
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO logs (timestamp, sender, receiver, message, type) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sender, receiver, message, msg_type)
            )
            await db.commit()
    except Exception as e:
        if "no column named sender" in str(e) or "no column named type" in str(e):
            await init_user_db(username)
            # Retry after migration
            try:
                async with aiosqlite.connect(db_path) as db:
                    await db.execute(
                        "INSERT INTO logs (timestamp, sender, receiver, message, type) VALUES (?, ?, ?, ?, ?)",
                        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sender, receiver, message, msg_type)
                    )
                    await db.commit()
            except Exception as e2:
                print(f"❌ Critical error in log_message after migration: {e2}")
        else:
            print(f"❌ Error in log_message: {e}")

async def get_user_api_key(username: str) -> str:
    async with aiosqlite.connect(system_db_path) as db:
        async with db.execute("SELECT api_key FROM users WHERE username=?", (username,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

# =======================
# UTILS
# =======================
def normalize_wa(num):
    if not num: return ""
    num = str(num).strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(num) > 15: return num

    # If starts with 08, it's definitely Indonesia
    if num.startswith("08"):
        return "62" + num[1:]
    # If starts with 0 but not 08, we still assume Indonesia for this gateway context
    # but more safely:
    if num.startswith("0") and len(num) >= 9:
        return "62" + num[1:]

    return num


def normalize_phone_number(phone: str) -> str:
    number = normalize_wa(phone)
    if not number.isascii() or not number.isdigit() or not 7 <= len(number) <= 15:
        raise HTTPException(422, "Nomor WhatsApp harus berisi 7–15 digit dengan kode negara.")
    return number

def get_target_jid(target: str) -> JID:
    if "@" in target:
        return str_to_jid(target)
    clean_id = target.split(":")[0]
    if len(clean_id) >= 15 and clean_id.startswith("1"):
        jid_str = clean_id + "@lid"
    elif "-" in clean_id:
        jid_str = clean_id + "@g.us"
    else:
        jid_str = normalize_wa(clean_id) + "@s.whatsapp.net"
    return str_to_jid(jid_str)

async def get_actual_jid(client, to: str) -> JID:
    """Resolves a JID or a WhatsApp Channel URL to a valid JID object."""
    if not to: return get_target_jid("")
    if "whatsapp.com/channel/" in to:
        invite_key = to.split("whatsapp.com/channel/")[1].split("/")[0]
        try:
            res = await client.get_newsletter_info_with_invite(invite_key)
            jid_obj = getattr(res, "ID", getattr(res, "JID", None))
            if jid_obj: return jid_obj
            raise Exception("Could not find JID in newsletter info")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Newsletter URL: {str(e)}")
    return get_target_jid(to)

def get_client(username: str, phone: Optional[str] = None):
    if phone:
        session_id = f"{username}:{normalize_phone_number(phone)}"
        if bot_status.get(session_id, False):
            return clients.get(session_id), phone
        return None, phone
    else:
        # Get first connected device
        for sid, status in bot_status.items():
            if sid.startswith(f"{username}:") and status:
                return clients.get(sid), sid.split(":")[1]
    return None, None

# =======================
# NEONIZE SETUP
# =======================
def start_neonize(username: str, phone: str, auto_connect: bool = True):
    session_id = f"{username}:{phone}"
    if session_id in clients:
        return

    print(f"🚀 Initializing WhatsApp Client for user [{username}] with phone [{phone}]...")
    session_path = f"storage/{username}/sessions/{phone}.sqlite3"
    client = NewAClient(session_path)
    client._pairing_ready = asyncio.Event()
    client._pairing_failed = asyncio.Event()
    client._pairing_failure_reason = ""
    client._has_connected = False
    clients[session_id] = client
    bot_status[session_id] = False

    @client.qr
    async def on_qr(c, qr_code):
        if clients.get(session_id) is not client:
            return
        bot_status[session_id] = False
        client._pairing_ready.set()
        logging.getLogger(__name__).info("Session %s requires pairing", session_id)

    @client.event(ConnectedEv)
    async def on_connected(c, _):
        if clients.get(session_id) is not client:
            return
        bot_status[session_id] = True
        client._has_connected = True
        pairing_sessions.discard(session_id)
        if c.me:
            bot_numbers[session_id] = c.me.JID.User
        print(f"✅ [{session_id}] Bot connected as {bot_numbers.get(session_id, 'Unknown')}!")

    @client.event(DisconnectedEv)
    async def on_disconnected(c, _):
        if clients.get(session_id) is not client:
            return
        bot_status[session_id] = False
        print(f"🔌 [{session_id}] Disconnect detected")

    @client.event(LoggedOutEv)
    async def on_logged_out(c, _):
        if clients.get(session_id) is not client:
            return
        bot_status[session_id] = False
        print(f"⚠️ [{session_id}] Logged Out! Menghapus session...")
        await discard_failed_pairing_client(session_id, client)
        if session_id in clients:
            return  # A new pairing attempt already owns the database path.

        if os.path.exists(session_path):
            try:
                os.remove(session_path)
                print(f"🗑️ [{session_id}] File session dihapus karena Logged Out.")
            except Exception as e:
                print(f"❌ [{session_id}] Gagal menghapus session: {e}")


    @client.event(ConnectFailureEv)
    async def on_connect_failure(c, event):
        if clients.get(session_id) is not client:
            return
        bot_status[session_id] = False
        client._pairing_failure_reason = str(event) or "Koneksi WhatsApp gagal."
        client._pairing_failed.set()
        logging.getLogger(__name__).warning("Connection failed for %s: %s", session_id, event)

    @client.event(KeepAliveTimeoutEv)
    async def on_keepalive_timeout(c, event):
        if clients.get(session_id) is not client:
            return
        bot_status[session_id] = False
        client._pairing_failure_reason = str(event) or "Koneksi WhatsApp timeout."
        client._pairing_failed.set()
        logging.getLogger(__name__).warning("Keepalive timeout for %s: %s", session_id, event)

    @client.event(KeepAliveRestoredEv)
    async def on_keepalive_restored(c, event):
        if clients.get(session_id) is not client:
            return
        bot_status[session_id] = True

    @client.event(CallOfferEv)
    async def on_call_offer(c, call):
        caller = call.BasicCallMeta.From
        print(f"📞 [{session_id}] Incoming call from {caller}")

    @client.event(NewsletterJoinEv)
    async def on_newsletter_join(c, event):
        print(f"📰 [{session_id}] Newsletter Join/Update: {event}")

    @client.event(MessageEv)
    async def on_message(c, message):
        if clients.get(session_id) is not client:
            return
        try:
            ms.add_message(message)
            m = Mess(c, message)
            m.sender_id = f"{m.sender.User}@{m.sender.Server}"
            m.chat_id = f"{m.chat.User}@{m.chat.Server}"

            # Prepare display text
            display_text = m.text
            if not display_text and m.is_media:
                display_text = f"[{m.media_type.upper()}]"

            # Khusus Newsletter: Print only, no log for incoming
            if m.chat.Server == "newsletter":
                log_prefix = "[EDIT]" if m.is_edit else "[IN]"
                sender_info = f"{m.sender_id}"
                if hasattr(m, 'sender_alt') and m.sender_alt:
                    sender_info += f" (Admin: {m.sender_alt.User}@{m.sender_alt.Server})"
                print(f"📰 {log_prefix} in {m.chat_id} by {sender_info}: {display_text}")

            if m.from_me:
                # Log outgoing messages (including those synced from other devices)
                if display_text:
                    await log_message(username, f"DEVICE({phone})", m.chat_id, display_text, "OUTGOING")

            if not m.from_me:
                auto_replied = await try_airich_auto_reply(c, username, phone, m)
                if not auto_replied and m.text and m.text.lower() == "ping":
                    await m.reply("pong!")
        except Exception as e:
            logging.getLogger(__name__).exception("on_message failed for session %s", session_id)
    if auto_connect:
        asyncio.create_task(client.connect())

# =======================
# API KEY DEPENDENCY
# =======================
async def verify_api_key(request: Request, x_api_key: Optional[str] = Header(None), key: Optional[str] = None) -> str:
    # Check Header first, then Query Param
    # This endpoint uses "key" for the channel invite, not authentication.
    api_key = x_api_key or (None if request.url.path == "/api/newsletter/info-by-invite" else key)

    if not api_key:
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="Silakan masuk atau sertakan API key.")
        from urllib.parse import urlsplit
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and urlsplit(origin).netloc != request.headers.get("host")):
            raise HTTPException(403, "Origin tidak diizinkan")
        async with aiosqlite.connect(system_db_path) as db:
            async with db.execute("SELECT username FROM users WHERE username=?", (user,)) as cursor:
                row = await cursor.fetchone()
        if row:
            return row[0]
        request.session.clear()
        raise HTTPException(401, "Sesi login sudah tidak berlaku.")

    async with aiosqlite.connect(system_db_path) as db:
        async with db.execute("SELECT username FROM users WHERE api_key=?", (api_key,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Invalid API Key")
            return row[0] # Returns username
# =================================================================
# WEB FRONTEND — React assets and dashboard routes are mounted below.
# Pages are authored in React and served from the compiled frontend assets.
# The handlers below are helpers + internal/external API routes.
# =================================================================

async def run_blast(username: str, phone_list: list, message_template: str, delay_min: int, delay_max: int, device_phones: list):
    import random
    import re

    print(f"🚀 Starting Blast for {username} to {len(phone_list)} numbers...")

    for i, item in enumerate(phone_list):
        # Rotate devices
        device_phone = device_phones[i % len(device_phones)]
        session_id = f"{username}:{device_phone}"
        client = clients.get(session_id)

        if not client or not bot_status.get(session_id):
            print(f"❌ Device {device_phone} disconnected, skipping one target.")
            continue

        target = str(item.get('phone', '')).strip()
        if not target: continue

        # Personalization
        final_msg = message_template
        for key, value in item.items():
            final_msg = final_msg.replace(f"{{{key}}}", str(value))

        target_jid = get_target_jid(target)
        try:
            await client.send_message(target_jid, final_msg)
            await log_message(username, f"DEVICE({device_phone})", target, final_msg, "OUTGOING")
        except Exception as e:
            print(f"❌ Failed to send blast to {target}: {e}")

        # Delay except for the last one
        if i < len(phone_list) - 1:
            wait_time = random.randint(delay_min, delay_max)
            await asyncio.sleep(wait_time)

    print(f"✅ Blast Campaign for {username} finished!")

class BlastRequest(BaseModel):
    phone_data: list # [{'phone': '628...', 'name': 'John'}, ...]
    message: str
    delay_min: int = 5
    delay_max: int = 15
    devices: list # ['628...', ...]

@app.post("/api/blast", include_in_schema=False)
async def api_blast(data: BlastRequest, request: Request):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")

    if not data.devices:
        raise HTTPException(status_code=400, detail="No devices selected")

    asyncio.create_task(run_blast(user, data.phone_data, data.message, data.delay_min, data.delay_max, data.devices))

    return {"success": True, "message": "Blast campaign started in background"}

# =======================
# EXTERNAL API ROUTES
# =======================

async def get_pairing_code_safe(client, phone_for_pairing):
    # NewAClient.connect() schedules the long-lived connection task and returns
    # before WhatsApp is ready. Wait for the QR event before calling PairPhone.
    ready = getattr(client, "_pairing_ready", None)
    if ready is None:
        raise RuntimeError("Pairing client is missing its QR-ready event")
    if not getattr(client, "connect_task", None):
        await client.connect()
    connect_task = getattr(client, "connect_task", None)
    ready_task = asyncio.create_task(ready.wait())
    failed = getattr(client, "_pairing_failed", None)
    failure_task = asyncio.create_task(failed.wait()) if failed is not None else None
    try:
        wait_tasks = [ready_task]
        if isinstance(connect_task, asyncio.Future):
            wait_tasks.append(connect_task)
        if failure_task is not None:
            wait_tasks.append(failure_task)
        if len(wait_tasks) > 1:
            done, _ = await asyncio.wait(
                wait_tasks, timeout=30,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if ready_task not in done:
                if failure_task is not None and failure_task in done:
                    reason = getattr(client, "_pairing_failure_reason", "")
                    raise RuntimeError(f"Neonize gagal sebelum pairing siap: {reason or 'koneksi ditolak'}")
                if connect_task in done:
                    try:
                        await connect_task
                    except Exception as exc:
                        raise RuntimeError(f"Neonize gagal tersambung sebelum pairing siap: {exc}") from exc
                    raise RuntimeError("Koneksi Neonize berhenti sebelum pairing siap")
                raise RuntimeError("WhatsApp tidak mengirim event pairing-ready dalam 30 detik; client dibersihkan, silakan coba lagi")
        else:
            await asyncio.wait_for(ready_task, timeout=30)
    except asyncio.TimeoutError as exc:
        raise RuntimeError("WhatsApp tidak mengirim event pairing-ready dalam 30 detik; client dibersihkan, silakan coba lagi") from exc
    finally:
        if not ready_task.done():
            ready_task.cancel()
        if failure_task is not None and not failure_task.done():
            failure_task.cancel()
    try:
        return await asyncio.wait_for(
            client.PairPhone(phone_for_pairing.lstrip("+"), show_push_notification=True),
            timeout=45,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Permintaan kode pairing ke WhatsApp timeout setelah 45 detik; koneksi dibersihkan agar bisa dicoba lagi tanpa restart PM2.") from exc


async def discard_failed_pairing_client(session_id: str, client) -> None:
    """Remove a failed pairing client and stop its Neonize worker before retrying."""
    if clients.get(session_id) is client:
        clients.pop(session_id, None)
        bot_status[session_id] = False
        bot_numbers.pop(session_id, None)
    try:
        await asyncio.wait_for(client.stop(), timeout=5)
    except Exception:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=3)
        except Exception as exc:
            logging.getLogger(__name__).warning("Failed pairing client cleanup for %s: %s", session_id, exc)
    connect_task = getattr(client, "connect_task", None)
    if isinstance(connect_task, asyncio.Future):
        try:
            await asyncio.wait_for(asyncio.shield(connect_task), timeout=5)
        except (Exception, asyncio.CancelledError) as exc:
            logging.getLogger(__name__).warning("Neonize worker exit for %s: %s", session_id, type(exc).__name__)

@app.post("/api/pair", include_in_schema=False)
async def pair_device(phone: str = Form(...), request: Request = None):
    # This is an internal API for the web dashboard, uses session auth.
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    return await request_pairing_code(user, phone)


async def request_pairing_code(user: str, phone: str):

    phone_clean = normalize_phone_number(phone)
    # WhatsApp pairing usually expects + prefix
    phone_for_pairing = "+" + phone_clean if not phone_clean.startswith("+") else phone_clean
    session_id = f"{user}:{phone_clean}"

    if bot_status.get(session_id, False):
        raise HTTPException(status_code=400, detail="Device is already connected")

    # Mark as pairing attempt
    if session_id in pairing_sessions:
        raise HTTPException(status_code=409, detail="Permintaan pairing untuk nomor ini masih berjalan; tunggu kode atau coba lagi setelah proses selesai.")
    pairing_sessions.add(session_id)

    client = None
    success = False
    try:
        # 1. Be extremely aggressive in clearing existing client
        if session_id in clients:
            print(f"🧹 Stopping existing client for {session_id} before pairing...")
            await discard_failed_pairing_client(session_id, clients[session_id])
            await asyncio.sleep(0.25)

        # 2. Force delete the session file
        session_path = f"storage/{user}/sessions/{phone_clean}.sqlite3"
        if os.path.exists(session_path):
            print(f"🗑️ Force deleting session file: {session_path}")
            # Try multiple times if locked
            for _ in range(3):
                try:
                    os.remove(session_path)
                    print(f"✅ Session file deleted.")
                    break
                except Exception as e:
                    print(f"⚠️ Retry deleting file ({e})...")
                    await asyncio.sleep(1.0)

        # 3. Start fresh
        await init_user_db(user)
        os.makedirs(f"storage/{user}/sessions", exist_ok=True)
        start_neonize(user, phone_clean, auto_connect=False)

        client = clients.get(session_id)
        if not client:
            raise HTTPException(status_code=500, detail="Failed to initialize new client")

        print(f"📲 Requesting Pairing Code for {phone_for_pairing}...")
        code = await get_pairing_code_safe(client, phone_for_pairing)

        if not code:
            raise Exception("WhatsApp server returned empty code. Try again.")

        success = True
        return {"success": True, "code": code}
    except (Exception, asyncio.CancelledError) as e:
        # Cleanup on failure
        failed_client = client
        if failed_client is not None:
            await discard_failed_pairing_client(session_id, failed_client)
        if session_id in pairing_sessions:
            pairing_sessions.remove(session_id)
        print(f"❌ Pairing failed: {e}")
        if isinstance(e, asyncio.CancelledError):
            raise
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Expire only this attempt. An old timer must never release a newer
        # attempt's lock, and unpaired clients must not leave workers behind.
        async def delayed_remove():
            await asyncio.sleep(120)
            if clients.get(session_id) is client:
                if not client._has_connected and not bot_status.get(session_id, False):
                    await discard_failed_pairing_client(session_id, client)
                pairing_sessions.discard(session_id)
        if success:
            task = asyncio.create_task(delayed_remove())
            client_cleanup_tasks.add(task)
            task.add_done_callback(client_cleanup_tasks.discard)
        else:
            pairing_sessions.discard(session_id)

@app.get("/api/passkey/poll", include_in_schema=False)
async def poll_passkey(phone: str, request: Request):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    session_id = f"{user}:{normalize_wa(phone)}"
    print(f"🔍 [DEBUG POLL] phone={phone}, session_id={session_id}, passkey_requests_keys={list(passkey_requests.keys())}")

    if session_id in passkey_errors:
        err = passkey_errors.pop(session_id)
        return {"status": "error", "error": err}

    if session_id in passkey_confirmations:
        conf = passkey_confirmations.pop(session_id)
        return {"status": "confirm", "data": conf}

    if session_id in passkey_requests:
        pubkey = passkey_requests.get(session_id)
        return {
            "status": "request",
            "publicKey": MessageToDict(pubkey) if hasattr(pubkey, "DESCRIPTOR") else pubkey
        }

    return {"status": "waiting"}

@app.post("/api/passkey/response", include_in_schema=False)
@app.post("/api/passkey/confirm", include_in_schema=False)
async def unsupported_passkey(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    raise HTTPException(status_code=501, detail="Neonize 0.5.2 does not support passkey pairing; use a pairing code")

@app.get("/api/device/download_session", include_in_schema=False)
async def download_session(phone: str, format: str = Query("sqlite"), request: Request = None):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    phone_clean = normalize_phone_number(phone)
    session_path = f"storage/{user}/sessions/{phone_clean}.sqlite3"

    if not os.path.exists(session_path):
        raise HTTPException(status_code=404, detail="Berkas database sesi tidak ditemukan.")

    if format.lower() == "json":
        import base64
        import sqlite3
        import json
        from fastapi.responses import Response
        try:
            conn = sqlite3.connect(session_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row['name'] for row in cursor.fetchall()]

            db_data = {}
            for table in tables:
                cursor.execute(f"SELECT * FROM {table};")
                rows = cursor.fetchall()
                table_rows = []
                for row in rows:
                    row_dict = {}
                    for key in row.keys():
                        val = row[key]
                        if isinstance(val, bytes):
                            row_dict[key] = f"base64:{base64.b64encode(val).decode('utf-8')}"
                        else:
                            row_dict[key] = val
                    table_rows.append(row_dict)
                db_data[table] = table_rows
            conn.close()

            json_str = json.dumps(db_data, indent=4)
            return Response(
                content=json_str,
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={phone_clean}.json"}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Gagal mengonversi sesi ke JSON: {e}")

    return FileResponse(
        path=session_path,
        filename=f"{phone_clean}.sqlite3",
        media_type="application/x-sqlite3"
    )

@app.post("/api/logout_device", include_in_schema=False)
async def logout_device(request: Request, phone: str = Form(...)):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    phone_clean = normalize_phone_number(phone)
    session_id = f"{user}:{phone_clean}"
    session_path = f"storage/{user}/sessions/{phone_clean}.sqlite3"

    # Remove the local session immediately. On Linux an open SQLite file can be
    # unlinked safely; a slow WhatsApp disconnect must not hold the HTTP request.
    pairing_sessions.discard(session_id)
    client = clients.pop(session_id, None)
    was_connected = bot_status.pop(session_id, False)
    bot_numbers.pop(session_id, None)
    try:
        if os.path.exists(session_path):
            os.remove(session_path)
    except OSError as exc:
        if client is not None:
            clients[session_id] = client
        raise HTTPException(status_code=500, detail=f"Gagal menghapus database sesi: {exc}") from exc

    if client is not None:
        async def close_client():
            try:
                if was_connected:
                    await asyncio.wait_for(client.logout(), timeout=4)
                else:
                    await asyncio.wait_for(client.disconnect(), timeout=4)
            except Exception:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=3)
                except Exception:
                    logging.getLogger(__name__).warning("Client cleanup timed out for %s", session_id)
            finally:
                await discard_failed_pairing_client(session_id, client)

        task = asyncio.create_task(close_client())
        client_cleanup_tasks.add(task)
        task.add_done_callback(client_cleanup_tasks.discard)

    return {"success": True, "message": "Sesi lokal berhasil dihapus"}

@app.get("/api/internal_status", include_in_schema=False)
async def internal_status(request: Request, phone: str):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")

    phone_clean = normalize_phone_number(phone)
    session_id = f"{user}:{phone_clean}"

    return {
        "status": "online" if bot_status.get(session_id, False) else "offline",
        "bot_number": bot_numbers.get(session_id, phone_clean)
    }


@app.get("/api/status")
async def api_status(phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Check Bot Status using x-api-key header"""
    if not phone:
        # Get first available device if phone not specified
        for sid, status in bot_status.items():
            if sid.startswith(f"{username}:"):
                phone = sid.split(":")[1]
                break

    if not phone:
        return {"status": "offline", "message": "No devices linked", "user": username}

    session_id = f"{username}:{normalize_phone_number(phone)}"
    return {
        "status": "online" if bot_status.get(session_id, False) else "offline",
        "bot_number": bot_numbers.get(session_id, None),
        "user": username,
        "device": phone
    }

@app.get("/api/device/pair")
async def api_pair_device(phone: str, username: str = Depends(verify_api_key)):
    """External API: Get pairing code for a phone number"""
    return await request_pairing_code(username, phone)

@app.get("/api/device/logout")
async def api_logout_device(phone: str, username: str = Depends(verify_api_key)):
    """External API: Logout and delete WhatsApp session"""
    phone_clean = normalize_phone_number(phone)
    session_id = f"{username}:{phone_clean}"
    session_path = f"storage/{username}/sessions/{phone_clean}.sqlite3"

    if session_id not in clients and not os.path.exists(session_path):
        raise HTTPException(status_code=404, detail="No session found for this device")

    print(f"🗑️ [API] Attempting to logout and delete session for {session_id}...")

    try:
        # 1. Cleanup client
        if session_id in clients:
            client = clients[session_id]
            try:
                if bot_status.get(session_id, False):
                    print(f"🔌 [API] Sending logout command to WhatsApp...")
                    await client.logout()
                else:
                    print(f"🔌 [API] Disconnecting client...")
                    await client.disconnect()
            except Exception as e:
                print(f"⚠️ [API] Error during client logout/disconnect: {e}")
                # Force disconnect
                try: await client.disconnect()
                except: pass
            finally:
                await discard_failed_pairing_client(session_id, client)

        bot_status[session_id] = False
        if session_id in bot_numbers: del bot_numbers[session_id]

        # 2. Delete file with retry
        if os.path.exists(session_path):
            print(f"📂 [API] Deleting session file: {session_path}")
            await asyncio.sleep(1.0)

            deleted = False
            for i in range(5):
                try:
                    os.remove(session_path)
                    print(f"✅ [API] Session file {session_path} deleted on attempt {i+1}.")
                    deleted = True
                    break
                except Exception as e:
                    print(f"⚠️ [API] Failed to delete session file (attempt {i+1}): {e}")
                    await asyncio.sleep(1.0)

            if not deleted:
                print(f"❌ [API] Failed to delete session file after 5 attempts.")

        return {"success": True, "message": f"Device {phone_clean} logged out and session cleared"}
    except Exception as e:
        print(f"❌ [API] Error in api_logout_device: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/groups")
async def api_get_groups(phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get list of joined groups"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    # Ensure client is connected
    status = client.is_connected
    if asyncio.iscoroutine(status): status = await status
    if not status:
        raise HTTPException(status_code=503, detail="Client is initialized but not connected to WA servers")

    try:
        print(f"🔍 Fetching groups for {p}...")
        groups = await client.get_joined_groups()
        res = []

        if groups:
            # Handle RepeatedCompositeContainer or list
            try:
                for g in groups:
                    try:
                        if hasattr(g, 'JID') and g.JID:
                            jid_str = str(f"{g.JID.User}@{g.JID.Server}")
                        else:
                            jid_str = str(getattr(g, 'jid', ''))

                        if not jid_str or jid_str == "None": continue

                        # Bersihkan Nama dari metadata protobuf
                        name_raw = getattr(g, 'Name', '') or getattr(g, 'GroupName', '') or jid_str
                        name_str = str(name_raw)
                        if 'Name: "' in name_str:
                            import re
                            match = re.search(r'Name: "([^"]+)"', name_str)
                            if match: name_str = match.group(1)

                        res.append({
                            "jid": str(jid_str),
                            "name": name_str,
                            "is_parent": bool(getattr(g, 'IsParentGroup', False)),
                            "is_community": bool(getattr(g, 'IsCommunity', False))
                        })
                    except: continue
            except TypeError:
                group_list = getattr(groups, 'GroupInfo', []) or getattr(groups, 'Groups', []) or []
                for g in group_list:
                    try:
                        if hasattr(g, 'JID') and g.JID:
                            jid_str = str(f"{g.JID.User}@{g.JID.Server}")
                        else:
                            jid_str = str(getattr(g, 'jid', ''))

                        name_raw = getattr(g, 'Name', '') or getattr(g, 'GroupName', '') or jid_str
                        name_str = str(name_raw)
                        if 'Name: "' in name_str:
                            import re
                            match = re.search(r'Name: "([^"]+)"', name_str)
                            if match: name_str = match.group(1)

                        res.append({
                            "jid": str(jid_str),
                            "name": name_str,
                            "is_parent": bool(getattr(g, 'IsParentGroup', False)),
                            "is_community": bool(getattr(g, 'IsCommunity', False))
                        })
                    except: continue

        return {"success": True, "groups": res, "count": len(res), "device": p}
    except Exception as e:
        print(f"❌ Error in api_get_groups: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch groups: {str(e)}")

@app.get("/api/group-info")
async def api_group_info(group_jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get group metadata and participants with LID to PN conversion"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    status = client.is_connected
    if asyncio.iscoroutine(status): status = await status
    if not status:
        raise HTTPException(status_code=503, detail="Client is initialized but not connected to WA servers")

    try:
        info = await client.get_group_info(str_to_jid(group_jid))
        participants = []
        for p_member in info.Participants:
            orig_jid = f"{p_member.JID.User}@{p_member.JID.Server}"
            final_jid = orig_jid

            # Jika peserta pakai LID, coba konversi ke nomor HP
            if p_member.JID.Server == "lid":
                try:
                    res = await client.get_pn_from_lid(p_member.JID)
                    if res:
                        final_jid = f"{res.User}@{res.Server}"
                except: pass

            participants.append({
                "jid": final_jid,
                "lid": orig_jid if p_member.JID.Server == "lid" else None,
                "is_admin": bool(p_member.IsAdmin),
                "is_super_admin": bool(p_member.IsSuperAdmin)
            })

        # Ambil nama grup secara aman dari info.GroupName
        group_name = group_jid
        group_name_obj = getattr(info, 'GroupName', None)
        if group_name_obj:
            if isinstance(group_name_obj, str):
                group_name = group_name_obj
            else:
                group_name = getattr(group_name_obj, 'Name', group_jid)

        # Bersihkan jika masih ada metadata string
        group_name = str(group_name)
        if 'Name: "' in group_name:
            import re
            match = re.search(r'Name: "([^"]+)"', group_name)
            if match: group_name = match.group(1)

        return {
            "success": True,
            "jid": group_jid,
            "name": group_name,
            "owner": f"{info.OwnerJID.User}@{info.OwnerJID.Server}" if hasattr(info, 'OwnerJID') and info.OwnerJID.User else None,
            "participants": participants,
            "device": p
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-message")
async def api_send_message(to: str, text: str, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send a text message using query params and x-api-key header"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    target_jid = get_target_jid(to)
    try:
        mentioned_jids = await get_mentions_list(client, target_jid, mentions)
        if mentioned_jids:
            context_info = ContextInfo(mentionedJID=mentioned_jids)
            msg = WAMessage(extendedTextMessage=ExtendedTextMessage(text=text, contextInfo=context_info))
            await client.send_message(target_jid, msg)
        else:
            await client.send_message(target_jid, text)

        await log_message(username, f"DEVICE({p})", to, text, "OUTGOING")
        return {"success": True, "message": "Text message sent successfully", "to": to, "device": p}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-image")
async def api_send_image(request: Request, to: str, image_url: str, caption: Optional[str] = "", hd: bool = False, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send an image via URL using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    target_jid = get_target_jid(to)
    try:
        # Optimization: Check if URL is local
        base_url = str(request.base_url).rstrip("/")
        img_to_send = image_url
        if image_url.startswith(base_url):
            local_path = image_url.replace(base_url + "/", "")
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    img_to_send = f.read()

        mentioned_jids = await get_mentions_list(client, target_jid, mentions)
        if mentioned_jids or hd:
            msg = await client.build_image_message(img_to_send, caption=caption)
            if mentioned_jids:
                msg.imageMessage.contextInfo.mentionedJID.extend(mentioned_jids)
            await client.send_message(target_jid, msg)
        else:
            await client.send_image(target_jid, img_to_send, caption=caption)

        await log_message(username, f"DEVICE({p})", to, f"[IMAGE] {image_url} | {caption}", "OUTGOING")
        return {"success": True, "message": f"Image sent successfully ", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-audio")
async def api_send_audio(request: Request, to: str, audio_url: str, ptt: bool = False, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send audio using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        # Optimization: Check if URL is local
        base_url = str(request.base_url).rstrip("/")
        audio_to_send = audio_url
        if audio_url.startswith(base_url):
            local_path = audio_url.replace(base_url + "/", "")
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    audio_to_send = f.read()

        await client.send_audio(target_jid, audio_to_send, ptt=ptt)
        await log_message(username, f"DEVICE({p})", to, f"[AUDIO] {audio_url}", "OUTGOING")
        return {"success": True, "message": "Audio sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-video")
async def api_send_video(request: Request, to: str, video_url: str, caption: Optional[str] = "", hd: bool = False, viewonce: bool = False, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send video using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        # Optimize video for WhatsApp
        optimized_url = await process_video(video_url, request, hd=hd)
        # If it's a local path, convert to public URL for neonize to download (or neonize might handle local paths)
        if optimized_url.startswith("static/"):
            base_url = str(request.base_url).rstrip("/")
            video_url_to_send = f"{base_url}/{optimized_url}"
        else:
            video_url_to_send = optimized_url

        mentioned_jids = await get_mentions_list(client, target_jid, mentions)
        if mentioned_jids or hd or viewonce:
            msg = await client.build_video_message(video_url_to_send, caption=caption, viewonce=viewonce)
            if mentioned_jids:
                msg.videoMessage.contextInfo.mentionedJID.extend(mentioned_jids)
            await client.send_message(target_jid, msg)
        else:
            await client.send_video(target_jid, video_url_to_send, caption=caption, viewonce=viewonce)

        await log_message(username, f"DEVICE({p})", to, f"[VIDEO] {video_url} | {caption}", "OUTGOING")
        return {"success": True, "message": "Video sent successfully", "to": to, "device": p}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-document")
async def api_send_document(request: Request, to: str, document_url: str, caption: Optional[str] = "", title: Optional[str] = "", filename: Optional[str] = "", mimetype: Optional[str] = "", phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send document using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        # Optimization: Check if URL is local
        base_url = str(request.base_url).rstrip("/")
        doc_to_send = document_url
        if document_url.startswith(base_url):
            local_path = document_url.replace(base_url + "/", "")
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    doc_to_send = f.read()

        await client.send_document(target_jid, doc_to_send, caption=caption, title=title, filename=filename, mimetype=mimetype)
        await log_message(username, f"DEVICE({p})", to, f"[DOCUMENT] {filename} | {document_url}", "OUTGOING")
        return {"success": True, "message": "Document sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-sticker")
async def api_send_sticker(request: Request, to: str, sticker_url: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send sticker using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        # Optimization: Check if URL is local
        base_url = str(request.base_url).rstrip("/")
        sticker_to_send = sticker_url
        if sticker_url.startswith(base_url):
            local_path = sticker_url.replace(base_url + "/", "")
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    sticker_to_send = f.read()

        await client.send_sticker(target_jid, sticker_to_send)
        await log_message(username, f"DEVICE({p})", to, f"[STICKER] {sticker_url}", "OUTGOING")
        return {"success": True, "message": "Sticker sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/newsletter/send")
async def api_newsletter_send(
    request: Request,
    to: str,
    type: str = "text",
    text: Optional[str] = "",
    media_url: Optional[str] = None,
    caption: Optional[str] = "",
    hd: bool = False,
    phone: Optional[str] = None,
    username: str = Depends(verify_api_key)
):
    """Dedicated API: Send message/media to a Newsletter channel. 'to' can be JID or URL."""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    target_jid = await get_actual_jid(client, to)
    if target_jid.Server != "newsletter":
        raise HTTPException(status_code=400, detail="Target must be a newsletter JID or URL")

    try:
        # Optimization: Check if URL is local
        media_to_send = media_url
        if media_url:
            base_url = str(request.base_url).rstrip("/")
            if media_url.startswith(base_url):
                local_path = media_url.replace(base_url + "/", "")
                if os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        media_to_send = f.read()

        if type == "text":
            await client.send_message(target_jid, text)
        elif type == "image":
            if hd:
                msg = await client.build_image_message(media_to_send, caption=caption or text)
                await client.send_message(target_jid, msg)
            else:
                await client.send_image(target_jid, media_to_send, caption=caption or text)
        elif type == "video":
            if hd:
                msg = await client.build_video_message(media_to_send, caption=caption or text)
                await client.send_message(target_jid, msg)
            else:
                await client.send_video(target_jid, media_to_send, caption=caption or text)
        elif type == "audio":
            await client.send_audio(target_jid, media_to_send)
        elif type == "document":
            await client.send_document(target_jid, media_to_send, caption=caption or text)
        else:
            raise HTTPException(status_code=400, detail="Unsupported message type for newsletter")

        await log_message(username, f"DEVICE({p})", str(target_jid), f"[NEWSLETTER] {type.upper()} | {caption or text}", "OUTGOING")
        return {"success": True, "message": f"{type.capitalize()} sent to newsletter "}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/newsletter/list")
async def api_newsletter_list(phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: List Subscribed Newsletters with Full Details"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        print(f"DEBUG: Fetching newsletter list for {p}")
        # Get basic list
        try:
            basic_list = await client.get_subscribed_newletters()
        except Exception as e:
            print(f"DEBUG: Error in get_subscribed_newletters: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch newsletter list: {str(e)}")

        if basic_list is None:
            print("DEBUG: basic_list is None")
            return {"success": True, "newsletters": []}

        print(f"DEBUG: Found {len(basic_list)} basic newsletters")

        # Fetch full details for each concurrently to be fast
        tasks = []
        for m in basic_list:
            try:
                # Try ID first (based on logs), then JID
                jid_obj = getattr(m, "ID", getattr(m, "JID", None))
                if jid_obj:
                    tasks.append(client.get_newsletter_info(jid_obj))
                else:
                    print(f"DEBUG: No JID/ID for message: {m}")
            except Exception as e:
                print(f"DEBUG: Error preparing task for {m}: {e}")

        detailed_list = []
        if tasks:
            detailed_list = await asyncio.gather(*tasks, return_exceptions=True)

        final_newsletters = []
        for i, res in enumerate(detailed_list):
            if isinstance(res, Exception):
                print(f"DEBUG: Error fetching info for index {i}: {res}")
                # Fallback to basic info if detail fetch fails
                final_newsletters.append(MessageToDict(basic_list[i]))
            else:
                final_newsletters.append(MessageToDict(res))

        await log_message(username, f"DEVICE({p})", "SYSTEM", f"Fetched {len(final_newsletters)} newsletters", "SYSTEM")
        return {"success": True, "newsletters": final_newsletters}
    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG: Global error in api_newsletter_list: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/newsletter/info-by-invite")
async def api_newsletter_info_by_invite(key: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Get Newsletter Info by Invite Key or URL.
    - key: The invite key (e.g. 0029VajW...) or the full URL.
    """
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        # If full URL, extract key
        if "whatsapp.com/channel/" in key:
            key = key.split("whatsapp.com/channel/")[1].split("/")[0]

        res = await client.get_newsletter_info_with_invite(key)
        await log_message(username, f"DEVICE({p})", "SYSTEM", f"Fetched newsletter info by invite: {key}", "SYSTEM")
        return {"success": True, "info": MessageToDict(res)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/newsletter/info")
async def api_newsletter_info(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get Newsletter Info"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        res = await client.get_newsletter_info(str_to_jid(jid))
        return {"success": True, "info": MessageToDict(res)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/newsletter/follow")
async def api_newsletter_follow(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Follow a Newsletter"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        await client.follow_newsletter(str_to_jid(jid))
        return {"success": True, "message": f"Followed newsletter {jid}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/newsletter/unfollow")
async def api_newsletter_unfollow(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Unfollow a Newsletter"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        await client.unfollow_newsletter(str_to_jid(jid))
        return {"success": True, "message": f"Unfollowed newsletter {jid}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/newsletter/messages")
async def api_newsletter_messages(jid: str, count: int = 10, before: Optional[int] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get Newsletter Messages"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        res = await client.get_newsletter_messages(str_to_jid(jid), count, before or 0)
        return {"success": True, "messages": [MessageToDict(m) for m in res]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/newsletter/create")
async def api_newsletter_create(name: str, description: str = "", phone: Optional[str] = None, username: str = Depends(verify_api_key), picture: Optional[str] = None):
    """External API: Create a Newsletter (Channel)"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        res = await client.create_newsletter(name, description, picture or b"")
        return {"success": True, "message": "Newsletter created successfully", "info": MessageToDict(res)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-contact")
async def api_send_contact(to: str, contact_name: str, contact_number: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send contact card using query params"""
    contact_name = contact_name.strip()
    if not contact_name:
        raise HTTPException(422, "Nama kontak tidak boleh kosong.")
    contact_number = normalize_phone_number(contact_number)
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = await get_actual_jid(client, to)
    try:
        await client.send_contact(target_jid, contact_name, contact_number)
        await log_message(username, f"DEVICE({p})", to, f"[CONTACT] {contact_name} ({contact_number})", "OUTGOING")
        return {"success": True, "message": "Contact card sent successfully", "to": to, "device": p}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LocationSendPayload(BaseModel):
    to: str
    phone: Optional[str] = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: Optional[str] = None
    address: Optional[str] = None


@app.post("/api/send-location")
async def api_send_location(data: LocationSendPayload, username: str = Depends(verify_api_key)):
    client, device = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="Perangkat WhatsApp tidak terhubung")
    target_jid = await get_actual_jid(client, data.to)
    message = WAMessage()
    message.locationMessage.degreesLatitude = data.latitude
    message.locationMessage.degreesLongitude = data.longitude
    if data.name:
        message.locationMessage.name = data.name
    if data.address:
        message.locationMessage.address = data.address
    await client.send_message(target_jid, message)
    await log_message(username, f"DEVICE({device})", data.to, f"[LOCATION] {data.latitude}, {data.longitude}", "OUTGOING")
    return {"success": True, "message": "Lokasi berhasil dikirim", "to": data.to}


class PollSendPayload(BaseModel):
    to: str
    phone: Optional[str] = None
    question: str = Field(min_length=1, max_length=255)
    options: List[str] = Field(min_length=2, max_length=12)
    allow_multiple: bool = False

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value):
        if not value.strip():
            raise ValueError("Pertanyaan polling tidak boleh kosong.")
        return value.strip()


@app.post("/api/send-poll")
async def api_send_poll(data: PollSendPayload, username: str = Depends(verify_api_key)):
    client, device = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="Perangkat WhatsApp tidak terhubung")
    options = [option.strip() for option in data.options if option.strip()]
    if len(options) < 2 or len(options) > 12 or len(set(options)) != len(options):
        raise HTTPException(status_code=422, detail="Polling memerlukan 2–12 opsi yang berbeda.")
    target_jid = await get_actual_jid(client, data.to)
    message = await client.build_poll_vote_creation(
        data.question, options, VoteType.MULTIPLE if data.allow_multiple else VoteType.SINGLE
    )
    await client.send_message(target_jid, message)
    await log_message(username, f"DEVICE({device})", data.to, f"[POLL] {data.question}", "OUTGOING")
    return {"success": True, "message": "Polling berhasil dikirim", "to": data.to}


class ReactionSendPayload(BaseModel):
    to: str
    phone: Optional[str] = None
    message_id: str = Field(min_length=1)
    reaction: str = Field(min_length=1, max_length=8)
    sender: Optional[str] = None


@app.post("/api/send-reaction")
async def api_send_reaction(data: ReactionSendPayload, username: str = Depends(verify_api_key)):
    client, device = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="Perangkat WhatsApp tidak terhubung")
    target_jid = await get_actual_jid(client, data.to)
    sender_jid = get_target_jid(data.sender) if data.sender else (client.me.JID if client.me else target_jid)
    message = await client.build_reaction(target_jid, sender_jid, data.message_id, data.reaction)
    await client.send_message(target_jid, message)
    await log_message(username, f"DEVICE({device})", data.to, f"[REACTION] {data.reaction} → {data.message_id}", "OUTGOING")
    return {"success": True, "message": "Reaksi berhasil dikirim", "to": data.to}

def normalize_interactive_payload(payload: dict) -> dict:
    """Accept the former frontend spelling without dropping protobuf validation."""
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(422, "Payload interactive harus berupa objek JSON yang berisi pesan.")
    result = deepcopy(payload)
    header = result.get("header")
    if header is not None:
        if not isinstance(header, dict):
            raise HTTPException(422, "Header interactive harus berupa objek JSON.")
        for field in ("imageMessage", "videoMessage"):
            media = header.get(field)
            if media is not None and not isinstance(media, (dict, str)):
                raise HTTPException(422, f"{field} harus berupa URL atau objek media.")
            if isinstance(media, dict):
                url = media.get("URL") or media.get("url")
                if url is not None and not isinstance(url, str):
                    raise HTTPException(422, "URL media interactive harus berupa teks.")
    flow = result.get("nativeFlowMessage")
    if flow is not None and not isinstance(flow, dict):
        raise HTTPException(422, "nativeFlowMessage harus berupa objek JSON.")
    if isinstance(flow, dict) and "buttons" in flow and not isinstance(flow["buttons"], list):
        raise HTTPException(422, "buttons harus berupa daftar tombol.")
    if isinstance(flow, dict) and "messageParamsJson" in flow:
        flow.setdefault("messageParamsJSON", flow.pop("messageParamsJson"))
    if isinstance(flow, dict) and isinstance(flow.get("buttons"), list):
        for button in flow["buttons"]:
            if not isinstance(button, dict):
                raise HTTPException(422, "Setiap tombol harus berupa objek JSON.")
            if isinstance(button, dict) and "buttonParamsJson" in button:
                legacy = button.pop("buttonParamsJson")
                button.setdefault("buttonParamsJSON", legacy)
    return result


@app.get("/api/send-interactive")
async def api_send_interactive_get(request: Request, to: str, payload: str, media_url: Optional[str] = None, media_type: Optional[str] = "image", hd: bool = False, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Send interactive message via GET.
    Payload must be a JSON string.
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    target_jid = await get_actual_jid(client, to)
    try:
        data = normalize_interactive_payload(json.loads(payload))

        # 1. Handle media from parameters
        media_handled = False
        if media_url:
            media_handled = True
            if "header" not in data: data["header"] = {}
            data["header"]["hasMediaAttachment"] = True

            # Optimization: Check if URL is local
            base_url = str(request.base_url).rstrip("/")
            media_to_send = media_url
            if media_url.startswith(base_url):
                local_path = media_url.replace(base_url + "/", "")
                if os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        media_to_send = f.read()

            if media_type == "video":
                optimized_url = await process_video(media_url, request, hd=hd)
                if optimized_url.startswith("static/"):
                    video_url_to_send = f"{base_url}/{optimized_url}"
                else:
                    video_url_to_send = optimized_url
                res = await client.build_video_message(video_url_to_send)
                data["header"]["videoMessage"] = MessageToDict(res.videoMessage)
            else:
                res = await client.build_image_message(media_to_send)
                data["header"]["imageMessage"] = MessageToDict(res.imageMessage)

        # 2. Handle media already inside the JSON payload (only if not handled above)
        if not media_handled:
            header = data.get("header", {})
            if header.get("hasMediaAttachment"):
                if "imageMessage" in header:
                    val = header["imageMessage"]
                    url = val if isinstance(val, str) else val.get("URL") or val.get("url")
                    if url and not url.startswith("https://mmg.whatsapp.net"):
                        # Optimization for local URL
                        base_url = str(request.base_url).rstrip("/")
                        img_to_send = url
                        if url.startswith(base_url):
                            local_path = url.replace(base_url + "/", "")
                            if os.path.exists(local_path):
                                with open(local_path, "rb") as f:
                                    img_to_send = f.read()

                        res = await client.build_image_message(img_to_send)
                        header["imageMessage"] = MessageToDict(res.imageMessage)
                elif "videoMessage" in header:
                    val = header["videoMessage"]
                    url = val if isinstance(val, str) else val.get("URL") or val.get("url")
                    if url and not url.startswith("https://mmg.whatsapp.net"):
                        optimized_url = await process_video(url, request, hd=hd)
                        if optimized_url.startswith("static/"):
                            base_url = str(request.base_url).rstrip("/")
                            video_url_to_send = f"{base_url}/{optimized_url}"
                        else:
                            video_url_to_send = optimized_url
                        res = await client.build_video_message(video_url_to_send)
                        header["videoMessage"] = MessageToDict(res.videoMessage)
        mentioned_jids = await get_mentions_list(client, target_jid, mentions)
        if mentioned_jids:
            if "contextInfo" not in data:
                data["contextInfo"] = {}
            data["contextInfo"]["mentionedJID"] = mentioned_jids

        # Build Protobuf Message
        inter_msg = InteractiveMessage()
        ParseDict(data, inter_msg)
        msg = WAMessage(interactiveMessage=inter_msg)

        await client.send_message(target_jid, msg)
        await log_message(username, f"DEVICE({p})", to, "[INTERACTIVE]", "OUTGOING")
        return {"success": True, "message": "Interactive message sent successfully", "to": to, "device": p}
    except HTTPException:
        raise
    except (ValueError, TypeError, ParseError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class InteractivePayload(BaseModel):
    to: str
    payload: dict
    phone: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = "image" # image or video
    mentions: Optional[str] = None
    hd: bool = False

@app.post("/api/send-interactive")
async def api_send_interactive_post(request: Request, data: InteractivePayload, username: str = Depends(verify_api_key)):
    """
    External API: Send interactive message via POST.
    """
    client, p = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    target_jid = await get_actual_jid(client, data.to)
    payload = normalize_interactive_payload(data.payload)

    # 1. Handle media from parameters
    media_handled = False
    if data.media_url:
        media_handled = True
        if "header" not in payload: payload["header"] = {}
        payload["header"]["hasMediaAttachment"] = True

        # Check if URL is local to avoid loopback fetch issues
        base_url = str(request.base_url).rstrip("/")
        media_url_to_process = data.media_url
        if data.media_url.startswith(base_url):
            local_path = data.media_url.replace(base_url + "/", "")
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    media_url_to_process = f.read()

        if data.media_type == "video":
            # For video, we still use process_video which might need a URL or we could adapt it
            # But for now, let's keep it as is or handle local path
            optimized_url = await process_video(data.media_url, request, hd=data.hd)
            if optimized_url.startswith("static/"):
                video_url_to_send = f"{base_url}/{optimized_url}"
            else:
                video_url_to_send = optimized_url
            res = await client.build_video_message(video_url_to_send)
            payload["header"]["videoMessage"] = MessageToDict(res.videoMessage)
        else:
            res = await client.build_image_message(media_url_to_process)
            payload["header"]["imageMessage"] = MessageToDict(res.imageMessage)

    # 2. Handle media already inside the JSON payload (only if not handled above)
    if not media_handled:
        header = payload.get("header", {})
        if header.get("hasMediaAttachment"):
            if "imageMessage" in header:
                val = header["imageMessage"]
                url = val if isinstance(val, str) else val.get("URL") or val.get("url")
                if url and not url.startswith("https://mmg.whatsapp.net"):
                    # Optimization for local URL in payload
                    base_url = str(request.base_url).rstrip("/")
                    image_data_to_send = url
                    if url.startswith(base_url):
                        local_path = url.replace(base_url + "/", "")
                        if os.path.exists(local_path):
                            with open(local_path, "rb") as f:
                                image_data_to_send = f.read()

                    res = await client.build_image_message(image_data_to_send)
                    header["imageMessage"] = MessageToDict(res.imageMessage)
            elif "videoMessage" in header:
                val = header["videoMessage"]
                url = val if isinstance(val, str) else val.get("URL") or val.get("url")
                if url and not url.startswith("https://mmg.whatsapp.net"):
                    optimized_url = await process_video(url, request, hd=data.hd)
                    if optimized_url.startswith("static/"):
                        base_url = str(request.base_url).rstrip("/")
                        video_url_to_send = f"{base_url}/{optimized_url}"
                    else:
                        video_url_to_send = optimized_url
                    res = await client.build_video_message(video_url_to_send)
                    header["videoMessage"] = MessageToDict(res.videoMessage)

    try:
        mentioned_jids = await get_mentions_list(client, target_jid, data.mentions)
        if mentioned_jids:
            if "contextInfo" not in payload:
                payload["contextInfo"] = {}
            payload["contextInfo"]["mentionedJID"] = mentioned_jids

        # Build Protobuf Message
        inter_msg = InteractiveMessage()
        ParseDict(payload, inter_msg)
        msg = WAMessage(interactiveMessage=inter_msg)

        await client.send_message(target_jid, msg)
        await log_message(username, f"DEVICE({p})", data.to, "[INTERACTIVE]", "OUTGOING")
        return {"success": True, "message": "Interactive message sent successfully", "to": data.to, "device": p}
    except HTTPException:
        raise
    except (ValueError, TypeError, ParseError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ButtonV2ItemPayload(BaseModel):
    display_text: str = Field(min_length=1, max_length=25)
    button_id: Optional[str] = None

class ButtonV2Payload(BaseModel):
    to: str
    phone: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    body: str = Field(min_length=1)
    footer: Optional[str] = None
    thumbnail_url: Optional[str] = None
    buttons: List[ButtonV2ItemPayload] = Field(min_length=1, max_length=3)
    mentions: Optional[str] = None

@app.post("/api/send-buttonv2")
async def api_send_buttonv2_post(request: Request, data: ButtonV2Payload, username: str = Depends(verify_api_key)):
    """
    External API: Send ButtonV2 (legacy buttons) via POST.
    """
    client, p = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    target_jid = await get_actual_jid(client, data.to)

    try:
        button_msg = ButtonV2Message()
        if data.title:
            button_msg.set_title(data.title)
        if data.subtitle:
            button_msg.set_subtitle(data.subtitle)
        if data.body:
            button_msg.set_body(data.body)
        if data.footer:
            button_msg.set_footer(data.footer)

        if data.thumbnail_url:
            base_url = str(request.base_url).rstrip("/")
            thumb_to_send = data.thumbnail_url
            if data.thumbnail_url.startswith(base_url):
                local_path = data.thumbnail_url.replace(base_url + "/", "")
                if os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        thumb_to_send = f.read()
            button_msg.set_thumbnail(thumb_to_send)

        for btn in data.buttons:
            button_msg.add_button(btn.display_text, btn.button_id)

        mentioned_jids = await get_mentions_list(client, target_jid, data.mentions)
        if mentioned_jids:
            context_info = ContextInfo(mentionedJID=mentioned_jids)
            button_msg.set_context_info(context_info)

        proto = await button_msg.prepare_asend(client)
        await client.send_message(target_jid, proto)
        await log_message(username, f"DEVICE({p})", data.to, "[BUTTONV2]", "OUTGOING")
        return {"success": True, "message": "ButtonV2 message sent successfully", "to": data.to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-buttonv2")
async def api_send_buttonv2_get(
    request: Request,
    to: str,
    body: str,
    buttons: str, # JSON string of buttons list
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    footer: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    mentions: Optional[str] = None,
    phone: Optional[str] = None,
    username: str = Depends(verify_api_key)
):
    """
    External API: Send ButtonV2 (legacy buttons) via GET.
    """
    try:
        data = ButtonV2Payload(
            to=to, body=body, buttons=json.loads(buttons), title=title,
            subtitle=subtitle, footer=footer, thumbnail_url=thumbnail_url,
            mentions=mentions, phone=phone,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return await api_send_buttonv2_post(request, data, username)


class AIRichBlock(BaseModel):
    type: Literal["text", "code", "table", "image", "video", "source", "product", "reels", "post", "tip", "suggest", "html"]
    text: Optional[str] = None
    latex: bool = True
    hyperlink: bool = True
    citation: bool = True
    language: Optional[str] = None
    html: Optional[str] = Field(default=None, max_length=500000)
    trusted_sources: List[str] = Field(default_factory=list)
    code: Optional[str] = None
    table: Optional[List[List[str]]] = None
    url: Optional[Union[str, List[str]]] = None
    duration: int = Field(default=0, ge=0)
    source: Optional[Union[Dict, List[Dict]]] = None
    product: Optional[Union[Dict, List[Dict]]] = None
    reel: Optional[Union[Dict, List[Dict]]] = None
    post: Optional[Union[Dict, List[Dict]]] = None
    suggestions: Optional[Union[str, List[str]]] = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_content(self):
        field = {"text": "text", "tip": "text", "code": "code", "table": "table",
                 "image": "url", "video": "url", "source": "source", "product": "product",
                 "reels": "reel", "post": "post", "suggest": "suggestions", "html": "html"}[self.type]
        value = getattr(self, field)
        if not value or isinstance(value, list) and any(not item for item in value):
            raise ValueError(f"{self.type} requires a nonempty {field}")
        if self.type == "code" and not self.language:
            raise ValueError("code requires language; use language=html to display HTML source")
        if self.type == "table" and any(len(row) != len(value[0]) for row in value):
            raise ValueError("table rows must have the same number of columns")
        if self.type in AIRICH_CARDS:
            for item in value if isinstance(value, list) else [value]:
                try:
                    AIRICH_CARDS[self.type](**item)
                except TypeError as exc:
                    raise ValueError(str(exc)) from exc
        return self


class AIRichPayload(BaseModel):
    to: str = Field(min_length=1)
    phone: Optional[str] = None
    title: Optional[str] = None
    footer: Optional[str] = None
    mentions: Optional[str] = None
    blocks: List[AIRichBlock] = Field(default_factory=list)
    submessages: Optional[List[Dict[str, Any]]] = None
    unified: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_mode(self):
        if (self.submessages is None) != (self.unified is None):
            raise ValueError("raw mode requires both submessages and unified")
        if self.submessages is not None and self.blocks:
            raise ValueError("choose blocks or raw mode")
        if self.submessages is None and not self.blocks:
            raise ValueError("provide at least one AI Rich block")
        return self


async def build_airich_message(data: AIRichPayload, client=None, mentioned_jids=None):
    context = ContextInfo(mentionedJID=mentioned_jids or [])
    if data.submessages is not None:
        subs = [ParseDict(sub, AIRichResponseSubMessage()) for sub in data.submessages]
        context.forwardingScore = 1
        context.isForwarded = True
        context.forwardedAiBotMessageInfo.CopyFrom(ForwardedAIBotMessageInfo(botJID="0@bot"))
        context.forwardOrigin = ContextInfo.META_AI
        rich = AIRichResponseMessage(messageType=1, submessages=subs,
            unifiedResponse=AIRichResponseUnifiedResponse(data=json.dumps(data.unified).encode()),
            contextInfo=context)
        return WAMessage(messageContextInfo=MessageContextInfo(deviceListMetadataVersion=2,
            botMetadata=BotMetadata(messageDisclaimerText=data.title or "")),
            botForwardedMessage=FutureProofMessage(message=WAMessage(richResponseMessage=rich)))

    if any(block.type == "html" for block in data.blocks):
        sections, subs = [], []
        for block in data.blocks:
            if block.type == "html":
                sections.append({"view_model": {
                    "primitive": {"__typename": "GenAIaeacdsnwHtmlPrimitive",
                                  "payload": block.html, "trusted_sources": block.trusted_sources},
                    "__typename": "GenAISingleLayoutViewModel"}})
                subs.append({"messageType": 2, "messageText": block.text or data.title or "HTML interactif"})
            else:
                part = await build_airich_message(data.model_copy(update={"blocks": [block], "title": None, "footer": None}), client)
                rich = part.botForwardedMessage.message.richResponseMessage
                sections.extend(json.loads(rich.unifiedResponse.data).get("sections", []))
                subs.extend(MessageToDict(sub) for sub in rich.submessages)
        if data.footer:
            part = await build_airich_message(AIRichPayload(to=data.to, blocks=[{"type": "text", "text": data.footer}]), client)
            rich = part.botForwardedMessage.message.richResponseMessage
            sections.extend(json.loads(rich.unifiedResponse.data).get("sections", []))
            subs.extend(MessageToDict(sub) for sub in rich.submessages)
        import uuid
        raw = data.model_copy(update={"blocks": [], "submessages": subs,
            "unified": {"response_id": str(uuid.uuid4()), "sections": sections}})
        return await build_airich_message(raw, client, mentioned_jids)

    msg = AIRichMessage()
    if data.title:
        msg.set_title(data.title)
    if data.footer:
        msg.set_footer(data.footer)
    msg.set_context_info(context)
    for block in data.blocks:
        kind = block.type
        if kind == "text":
            msg.add_text(block.text, latex=block.latex, hyperlink=block.hyperlink, citation=block.citation)
        elif kind == "code":
            msg.add_code(block.language, block.code)
        elif kind == "table":
            msg.add_table(block.table)
        elif kind == "image":
            msg.add_image(block.url)
        elif kind == "video":
            msg.add_video(block.url, duration=block.duration)
        elif kind in AIRICH_CARDS:
            items = getattr(block, "reel" if kind == "reels" else kind)
            cards = [AIRICH_CARDS[kind](**item) for item in (items if isinstance(items, list) else [items])]
            getattr(msg, {"source": "add_source", "product": "add_product", "reels": "add_reels", "post": "add_post"}[kind])(cards)
        elif kind == "tip":
            msg.add_tip(block.text)
        elif kind == "suggest":
            msg.add_suggest(block.suggestions)
    return await msg.prepare_asend(client)


async def try_airich_auto_reply(client, username: str, phone: str, message) -> bool:
    """Send the first matching per-account AI Rich rule for an incoming chat message."""
    text = (getattr(message, "text", "") or "").strip()
    if not text or getattr(message, "is_edit", False):
        return False
    server = getattr(getattr(message, "chat", None), "Server", "")
    if server not in ("s.whatsapp.net", "g.us"):
        return False
    chat_id = f"{message.chat.User}@{server}"
    normalized = text.casefold()
    for rule in get_airich_auto_rules(username):
        if not rule.get("enabled", True):
            continue
        keyword = str(rule.get("keyword", "")).strip().casefold()
        if not keyword:
            continue
        matched = normalized == keyword if rule.get("match") == "exact" else keyword in normalized
        if not matched:
            continue
        scope = rule.get("scope", "all")
        if scope == "private" and server != "s.whatsapp.net":
            continue
        if scope == "group" and server != "g.us":
            continue
        rule_id = str(rule.get("id", keyword))
        cooldown_key = (f"{username}:{phone}", chat_id, rule_id)
        now = time.monotonic()
        cooldown = max(0, min(86400, int(rule.get("cooldown_seconds", 30))))
        if cooldown and now - airich_auto_last.get(cooldown_key, 0) < cooldown:
            continue
        message_id = str(getattr(getattr(message, "info", None), "ID", ""))
        seen_key = f"{username}:{phone}:{message_id}" if message_id else ""
        if seen_key and seen_key in airich_auto_seen:
            return False
        if seen_key:
            airich_auto_seen[seen_key] = now
        if len(airich_auto_seen) > 5000:
            for key, seen_at in list(airich_auto_seen.items()):
                if now - seen_at > 3600 or len(airich_auto_seen) > 4000:
                    airich_auto_seen.pop(key, None)
        data = AIRichPayload(
            to=chat_id,
            phone=phone,
            blocks=rule["blocks"],
        )
        rich_message = await build_airich_message(data, client)
        await client.send_message(message.chat, rich_message)
        if cooldown:
            airich_auto_last[cooldown_key] = now
        await log_message(username, f"DEVICE({phone})", chat_id, f"[AI RICH AUTO REPLY] {keyword}", "OUTGOING")
        return True
    return False


@app.post("/api/airich/preview")
async def api_airich_preview(data: AIRichPayload, username: str = Depends(verify_api_key)):
    """Build the message without sending. This is a protobuf preview, not a WhatsApp render."""
    try:
        msg = await build_airich_message(data)
        return {"success": True, "sent": False, "message": MessageToDict(msg)}
    except (ValueError, TypeError, ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/send-airich")
async def api_send_airich_post(request: Request, data: AIRichPayload, username: str = Depends(verify_api_key)):
    """Send AI Rich blocks, including experimental HTML primitives."""
    client, p = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = await get_actual_jid(client, data.to)
    try:
        mentions = await get_mentions_list(client, target_jid, data.mentions)
        wa_msg = await build_airich_message(data, client, mentions)
    except (ValueError, TypeError, ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        await client.send_message(target_jid, wa_msg)
        await log_message(username, f"DEVICE({p})", data.to, "[AIRICH]", "OUTGOING")
        return {"success": True, "message": "AI Rich message sent successfully", "to": data.to, "device": p}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/send-airich")
async def api_send_airich_get(request: Request, to: str, payload: str, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """GET uses the same validated payload and builder as POST."""
    try:
        values = json.loads(payload)
        if not isinstance(values, dict):
            raise ValueError("payload must be a JSON object")
        values["to"] = to
        if phone is not None:
            values["phone"] = phone
        if mentions is not None:
            values["mentions"] = mentions
        data = AIRichPayload.model_validate(values)
    except (ValueError, TypeError, ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await api_send_airich_post(request, data, username)

@app.get("/api/send-status")
async def api_send_status(request: Request, type: str, text: Optional[str] = "", url: Optional[str] = "", mentions: Optional[str] = None, hd: bool = False, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Send WhatsApp Status (Story)
    type: 'text', 'image', or 'video'
    Media is uploaded from the source file; hd is retained for API compatibility.
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    status_jid = str_to_jid("status@broadcast")
    try:
        mentioned_jids = await get_mentions_list(client, status_jid, mentions)

        # Optimization: Check if URL is local
        media_to_send = url
        if url:
            base_url = str(request.base_url).rstrip("/")
            if url.startswith(base_url):
                local_path = url.replace(base_url + "/", "")
                if os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        media_to_send = f.read()

        if type == "text":
            if mentioned_jids:
                context_info = ContextInfo(mentionedJID=mentioned_jids)
                msg = WAMessage(extendedTextMessage=ExtendedTextMessage(text=text, contextInfo=context_info))
                await client.send_message(status_jid, msg)
            else:
                await client.send_message(status_jid, text)
            await log_message(username, f"DEVICE({p})", "status@broadcast", text, "OUTGOING")
        elif type == "image":
            if mentioned_jids or hd:
                msg = await client.build_image_message(media_to_send, caption=text)
                # Pastikan contextInfo ada dan masukkan tag
                if not msg.imageMessage.HasField("contextInfo"):
                    msg.imageMessage.contextInfo.SetInParent()
                if mentioned_jids:
                    msg.imageMessage.contextInfo.mentionedJID.extend(mentioned_jids)
                await client.send_message(status_jid, msg)
            else:
                await client.send_image(status_jid, media_to_send, caption=text)
            await log_message(username, f"DEVICE({p})", "status@broadcast", f"[STATUS IMAGE] {url} | {text} ", "OUTGOING")
        elif type == "video":
            # Optimize video for Status
            video_to_process = url
            if not url and isinstance(media_to_send, bytes):
                # If we have bytes but no URL, we might need to write to a temp file first
                # But process_video expects a URL or local path string.
                # For status, it's better if we always have a URL.
                pass

            if url:
                optimized_url = await process_video(url, request, hd=hd)
                if optimized_url.startswith("static/"):
                    base_url = str(request.base_url).rstrip("/")
                    media_to_send = f"{base_url}/{optimized_url}"
                else:
                    media_to_send = optimized_url

            if mentioned_jids or hd:
                msg = await client.build_video_message(media_to_send, caption=text)
                # Pastikan contextInfo ada dan masukkan tag
                if not msg.videoMessage.HasField("contextInfo"):
                    msg.videoMessage.contextInfo.SetInParent()
                if mentioned_jids:
                    msg.videoMessage.contextInfo.mentionedJID.extend(mentioned_jids)
                await client.send_message(status_jid, msg)
            else:
                await client.send_video(status_jid, media_to_send, caption=text)
            await log_message(username, f"DEVICE({p})", "status@broadcast", f"[STATUS VIDEO] {url} | {text} ", "OUTGOING")
        else:
            raise HTTPException(status_code=400, detail="Invalid status type. Use 'text', 'image', or 'video'")

        return {"success": True, "message": f"Status sent successfully ", "device": p}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-group-status")
async def api_send_group_status(request: Request, to: str, type: str, text: Optional[str] = "", url: Optional[str] = "", mentions: Optional[str] = None, hd: bool = False, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Send WhatsApp Group Status (Story to specific Group)
    to: Group JID
    type: 'text', 'image', or 'video'
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    target_jid = get_target_jid(to)
    if target_jid.Server != "g.us":
        raise HTTPException(422, "Status grup memerlukan JID grup berakhiran @g.us.")
    try:
        mentioned_jids = await get_mentions_list(client, target_jid, mentions)

        # Optimization: Check if URL is local
        media_to_send = url
        if url:
            base_url = str(request.base_url).rstrip("/")
            if url.startswith(base_url):
                local_path = url.replace(base_url + "/", "")
                if os.path.exists(local_path):
                    with open(local_path, "rb") as f:
                        media_to_send = f.read()

        inner_msg = WAMessage()
        if type == "text":
            if mentioned_jids:
                context_info = ContextInfo(mentionedJID=mentioned_jids)
                inner_msg.extendedTextMessage.CopyFrom(ExtendedTextMessage(text=text, contextInfo=context_info))
            else:
                inner_msg.conversation = text
        elif type == "image":
            temp_msg = await client.build_image_message(media_to_send, caption=text)
            if mentioned_jids:
                if not temp_msg.imageMessage.HasField("contextInfo"):
                    temp_msg.imageMessage.contextInfo.SetInParent()
                temp_msg.imageMessage.contextInfo.mentionedJID.extend(mentioned_jids)
            inner_msg.imageMessage.CopyFrom(temp_msg.imageMessage)
        elif type == "video":
            # Optimize video for Status
            if url:
                optimized_url = await process_video(url, request, hd=hd)
                if optimized_url.startswith("static/"):
                    base_url = str(request.base_url).rstrip("/")
                    media_to_send = f"{base_url}/{optimized_url}"
                else:
                    media_to_send = optimized_url

            temp_msg = await client.build_video_message(media_to_send, caption=text)
            if mentioned_jids:
                if not temp_msg.videoMessage.HasField("contextInfo"):
                    temp_msg.videoMessage.contextInfo.SetInParent()
                temp_msg.videoMessage.contextInfo.mentionedJID.extend(mentioned_jids)
            inner_msg.videoMessage.CopyFrom(temp_msg.videoMessage)
        else:
            raise HTTPException(status_code=400, detail="Invalid status type. Use 'text', 'image', or 'video'")

        msg = WAMessage()
        msg.groupStatusMessageV2.message.CopyFrom(inner_msg)

        await client.send_message(target_jid, msg)
        await log_message(username, f"DEVICE({p})", to, f"[GROUP STATUS {type.upper()}] {text} ", "OUTGOING")

        return {"success": True, "message": f"Group Status sent successfully ", "to": to, "device": p}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/convert-jid")
async def api_convert_jid(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Convert JID between LID and PN.
    If PN JID provided, returns LID JID.
    If LID JID provided, returns PN JID.
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    # Ensure client is connected
    status = client.is_connected
    if asyncio.iscoroutine(status): status = await status
    if not status:
        raise HTTPException(status_code=503, detail="Client is initialized but not connected to WA servers")

    try:
        target = str_to_jid(jid)
        res_jid = None

        if target.Server == "lid":
            # Convert LID to PN
            res = await client.get_pn_from_lid(target)
            if res:
                res_jid = f"{res.User}@{res.Server}"
        else:
            # Convert PN to LID
            res = await client.get_lid_from_pn(target)
            if res:
                res_jid = f"{res.User}@{res.Server}"

        return {
            "success": True,
            "input": jid,
            "result": res_jid,
            "device": p
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/check-number")
async def api_check_number(phone_to_check: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Check if a number is registered on WhatsApp and get ALL available profile info from neonize"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    clean_phone = normalize_wa(phone_to_check)
    try:
        # 1. Basic Check & Primary JID
        res = await client.is_on_whatsapp(clean_phone)
        if not res or not res[0].IsIn:
            return {"success": True, "phone": phone_to_check, "is_registered": False, "device": p}

        actual_jid = res[0].JID
        jid_str = f"{actual_jid.User}@{actual_jid.Server}"

        # 2. Get LID (Identity JID) or PN JID
        lid_jid = None
        pn_jid = jid_str if actual_jid.Server == "s.whatsapp.net" else None

        try:
            if actual_jid.Server == "s.whatsapp.net":
                lid_res = await client.get_lid_from_pn(actual_jid)
                if lid_res: lid_jid = f"{lid_res.User}@{lid_res.Server}"
            elif actual_jid.Server == "lid":
                lid_jid = jid_str
                pn_res = await client.get_pn_from_lid(actual_jid)
                if pn_res: pn_jid = f"{pn_res.User}@{pn_res.Server}"
        except: pass

        # 3. Get User Info (Status, Verified Name Details)
        status_text = ""
        pushname = ""
        is_verified = False
        verified_details = {}
        linked_devices = []

        # Check verified name from is_on_whatsapp first
        try:
            v_name_initial = getattr(res[0], 'VerifiedName', None)
            if v_name_initial:
                d_initial = getattr(v_name_initial, 'Details', None)
                v_name_str = getattr(d_initial, 'verifiedName', "") if d_initial else ""
                if v_name_str:
                    pushname = v_name_str
                    is_verified = True
                    verified_details = {
                        "issuer": getattr(d_initial, 'issuer', ""),
                        "serial": getattr(d_initial, 'serial', 0),
                        "issue_time": getattr(d_initial, 'issueTime', 0),
                        "localized_names": []
                    }
        except:
            pass

        try:
            info_res = await client.get_user_info(actual_jid)
            if info_res:
                user_infos = getattr(info_res, 'UsersInfo', info_res) if hasattr(info_res, 'UsersInfo') else info_res

                if user_infos and len(user_infos) > 0:
                    u_info = getattr(user_infos[0], 'UserInfo', None)
                    if u_info:
                        status_text = getattr(u_info, 'Status', "")

                        # Update verified info if more details found
                        v_name = getattr(u_info, 'VerifiedName', None)
                        if v_name:
                            cert = getattr(v_name, 'Certificate', None)
                            d = getattr(cert, 'Details', getattr(v_name, 'Details', None)) if cert else getattr(v_name, 'Details', None)
                            v_name_str = getattr(d, 'verifiedName', "") if d else ""
                            if v_name_str:
                                pushname = v_name_str
                                is_verified = True
                                verified_details = {
                                    "issuer": getattr(d, 'issuer', ""),
                                    "serial": getattr(d, 'serial', 0),
                                    "issue_time": getattr(d, 'issueTime', 0),
                                    "localized_names": [getattr(l, 'verifiedName', "") for l in getattr(d, 'localizedNames', [])]
                                }

                        # Linked Devices
                        devs = getattr(u_info, 'Devices', [])
                        for dev in devs:
                            linked_devices.append({
                                "jid": f"{dev.User}@{dev.Server}",
                                "device_id": dev.Device,
                                "is_companion": dev.Device > 0
                            })
        except Exception as e:
            print(f"⚠️ Failed to get extended user info: {e}")

        # 4. Get Profile Picture (Full Info)
        pp_info = {}
        try:
            pp_res = await client.get_profile_picture(actual_jid)
            if pp_res:
                pp_info = {
                    "url": getattr(pp_res, 'URL', ''),
                    "id": getattr(pp_res, 'ID', ''),
                    "type": getattr(pp_res, 'Type', ''),
                    "direct_path": getattr(pp_res, 'DirectPath', '')
                }
        except: pass

        return {
            "success": True,
            "phone": phone_to_check,
            "is_registered": True,
            "jid": pn_jid or jid_str,
            "lid": lid_jid,
            "info": {
                "pushname": pushname,
                "status": status_text,
                "is_verified": is_verified,
                "verified_details": verified_details,
                "devices": linked_devices
            },
            "profile_picture": pp_info,
            "device_used": p
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/resend")
async def api_resend(log_id: int, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Resend a message from the logs"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    db_path = f"storage/{username}/history/logs.db"
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Logs database not found")

    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT receiver, message FROM logs WHERE id=?", (log_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Log entry not found")

                receiver, message = row
                target_jid = get_target_jid(receiver)

                # Check if it's a media placeholder or simple text
                if message.startswith("[IMAGE]"):
                    # Extract URL from [IMAGE] URL | Caption
                    parts = message.replace("[IMAGE] ", "").split(" | ")
                    url = parts[0]
                    caption = parts[1] if len(parts) > 1 else ""
                    await client.send_image(target_jid, url, caption=caption)
                elif message.startswith("[VIDEO]"):
                    parts = message.replace("[VIDEO] ", "").split(" | ")
                    url = parts[0]
                    caption = parts[1] if len(parts) > 1 else ""
                    await client.send_video(target_jid, url, caption=caption)
                elif message.startswith("[AUDIO]"):
                    url = message.replace("[AUDIO] ", "")
                    await client.send_audio(target_jid, url)
                elif message.startswith("[DOCUMENT]"):
                    parts = message.replace("[DOCUMENT] ", "").split(" | ")
                    url = parts[1] if len(parts) > 1 else parts[0]
                    await client.send_document(target_jid, url)
                else:
                    await client.send_message(target_jid, message)

                await log_message(username, f"DEVICE({p})", receiver, message, "OUTGOING")
                return {"success": True, "message": "Message resent successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from dashboard_api import setup_dashboard
setup_dashboard(app, sys.modules[__name__])


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8880, reload=False)
