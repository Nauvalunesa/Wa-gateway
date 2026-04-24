import asyncio
import os
import secrets
from datetime import datetime
import aiosqlite
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Form, Depends, Header, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import shutil
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict

from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

from neonize.aioze.client import NewAClient
from neonize.events import ConnectedEv, MessageEv, DisconnectedEv, LoggedOutEv, QREv
from neonize.proto.Neonize_pb2 import JID
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message as WAMessage, ContextInfo, ExtendedTextMessage
from google.protobuf.json_format import ParseDict, MessageToDict
import json
from serialize import Mess, str_to_jid
from msg_store import store as ms

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

app = FastAPI(
    title="WhatsApp Multi-Session Gateway",
    description="A FastAPI gateway for WhatsApp using neonize supporting multiple sessions & API Keys",
    version="2.1.0"
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
    # Daftar rute publik (API eksternal & assets)
    public_prefixes = ["/api/send-", "/api/status", "/api/check-", "/api/device/", "/api/groups", "/api/group-info", "/api/convert-jid", "/docs", "/openapi.json", "/static", "/favicon.ico"]
    # Daftar rute auth (tidak perlu cek session, tapi tetap cek Host)
    auth_routes = ["/login", "/register"]
    
    path = request.url.path
    is_public = any(path.startswith(prefix) for prefix in public_prefixes)
    is_auth = path in auth_routes
    
    # 1. Cek Host untuk semua rute internal (Web & Internal API)
    if not is_public:
        host = request.headers.get("host", "")
        if host not in ["wa.nauval.site", "localhost:8880", "127.0.0.1:8880"]:
            return HTMLResponse(content="<h1>403 Forbidden</h1><p>Access only allowed via wa.nauval.site</p>", status_code=403)

    # 2. Cek Session untuk rute Web Internal (Redirect ke login jika belum ada akun)
    if not is_public and not is_auth:
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/login")
            
    response = await call_next(request)
    return response

app.add_middleware(SessionMiddleware, secret_key="super-secret-gateway-multi-key")

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

templates = Jinja2Templates(directory="templates")
os.makedirs("storage", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

clients: Dict[str, NewAClient] = {}
bot_status: Dict[str, bool] = {}
bot_numbers: Dict[str, str] = {}
system_db_path = "storage/system.db"

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
        
        # Check if default admin exists
        async with db.execute("SELECT id FROM users WHERE username='admin'") as cursor:
            if not await cursor.fetchone():
                admin_key = secrets.token_hex(16)
                await db.execute("INSERT INTO users (username, password, api_key, is_verified) VALUES ('admin', 'admin', ?, 1)", (admin_key,))
        await db.commit()

async def init_user_db(username: str):
    base_path = f"storage/{username}"
    os.makedirs(f"{base_path}/sessions", exist_ok=True)
    os.makedirs(f"{base_path}/history", exist_ok=True)
    os.makedirs(f"{base_path}/config", exist_ok=True)
    os.makedirs(f"{base_path}/device", exist_ok=True)
    
    db_path = f"{base_path}/history/logs.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sender_id TEXT,
                chat_id TEXT,
                message_text TEXT
            )
        ''')
        await db.commit()

async def log_message(username: str, sender_id: str, chat_id: str, text: str):
    db_path = f"storage/{username}/history/logs.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO logs (timestamp, sender_id, chat_id, message_text) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sender_id, chat_id, text)
        )
        await db.commit()

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
    if num.startswith("0"):
        if num.startswith("08"):
            return "62" + num[1:]
        return "62" + num[1:]
    return num

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

def get_client(username: str, phone: Optional[str] = None):
    if phone:
        session_id = f"{username}:{normalize_wa(phone)}"
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
def start_neonize(username: str, phone: str):
    session_id = f"{username}:{phone}"
    if session_id in clients:
        return
        
    print(f"🚀 Initializing WhatsApp Client for {username} ({phone})...")
    session_path = f"storage/{username}/sessions/{phone}.sqlite3"
    client = NewAClient(session_path)
    clients[session_id] = client
    bot_status[session_id] = False
    
    @client.event(QREv)
    async def on_qr(c, qr_code):
        # Jangan hapus session di sini, hanya tandai offline
        print(f"⚠️ [{session_id}] QR Code muncul. Menunggu pairing selesai...")
        bot_status[session_id] = False

    @client.event(ConnectedEv)
    async def on_connected(c, _):
        bot_status[session_id] = True
        if c.me:
            bot_numbers[session_id] = c.me.JID.User
        print(f"✅ [{session_id}] Bot connected as {bot_numbers.get(session_id, 'Unknown')}!")

    @client.event(DisconnectedEv)
    async def on_disconnected(c, _):
        bot_status[session_id] = False
        print(f"🔌 [{session_id}] Disconnect detected")

    @client.event(LoggedOutEv)
    async def on_logged_out(c, _):
        bot_status[session_id] = False
        print(f"⚠️ [{session_id}] Logged Out! Menghapus session...")
        try:
            await c.disconnect()
        except:
            pass
            
        if os.path.exists(session_path):
            await asyncio.sleep(1)
            try:
                os.remove(session_path)
                print(f"🗑️ [{session_id}] File session dihapus karena Logged Out.")
            except Exception as e:
                print(f"❌ [{session_id}] Gagal menghapus session: {e}")
        
        if session_id in clients:
            del clients[session_id]

    @client.event(MessageEv)
    async def on_message(c, message):
        try:
            ms.add_message(message)
            m = Mess(c, message)
            m.sender_id = f"{m.sender.User}@{m.sender.Server}"
            m.chat_id = f"{m.chat.User}@{m.chat.Server}"
            
            if m.from_me and m.text:
                # Cek apakah sudah di-log oleh API (untuk menghindari log ganda)
                # Pesan dari API biasanya sudah di-log manual di endpointnya.
                # Jika Anda mengirim manual dari HP, m.text biasanya murni teks tanpa prefix [OUT]
                await log_message(username, f"DEVICE({phone})", m.chat_id, f"[SEND] {m.text}")
            
            # Auto-reply tetap bisa jalan (opsional, tapi biarkan untuk testing)
            if not m.from_me and m.text and m.text.lower() == "ping":
                await m.reply("pong!")
        except Exception as e:
            print(f"❌ [{session_id}] Error in on_message: {e}")

    asyncio.create_task(client.connect())

@app.on_event("startup")
async def startup_event():
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
                        # Handle old naming if any
                        if phone == "session": continue 
                        start_neonize(item, phone)

@app.on_event("shutdown")
async def shutdown_event():
    print("🔌 Shutting down WhatsApp Gateway...")
    for user, client in clients.items():
        if asyncio.iscoroutinefunction(client.disconnect):
            await client.disconnect()
        else:
            client.disconnect()

# =======================
# API KEY DEPENDENCY
# =======================
async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="x-api-key header is missing")
        
    async with aiosqlite.connect(system_db_path) as db:
        async with db.execute("SELECT username FROM users WHERE api_key=?", (x_api_key,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Invalid API Key")
            return row[0] # Returns username

# =======================
# WEB ROUTES
# =======================
@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", include_in_schema=False)
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    async with aiosqlite.connect(system_db_path) as db:
        # Check if user exists first
        async with db.execute("SELECT * FROM users WHERE username=?", (username,)) as cursor:
            user_exists = await cursor.fetchone()
            if not user_exists:
                # User not found, redirect to register with info
                return templates.TemplateResponse("login.html", {
                    "request": request, 
                    "error": "Account not found. Please register first.",
                    "redirect_to_register": True
                })
        
        # If exists, check password
        async with db.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)) as cursor:
            user = await cursor.fetchone()
            if user:
                request.session["user"] = username
                await init_user_db(username)
                return RedirectResponse(url="/", status_code=303)
            else:
                return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})

@app.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register", include_in_schema=False)
async def do_register(request: Request, username: str = Form(...), password: str = Form(...)):
    if not username.isalnum():
        return templates.TemplateResponse("register.html", {"request": request, "error": "Username must be alphanumeric"})
        
    new_api_key = secrets.token_hex(16)
    async with aiosqlite.connect(system_db_path) as db:
        try:
            await db.execute("INSERT INTO users (username, password, api_key) VALUES (?, ?, ?)", (username, password, new_api_key))
            await db.commit()
            return RedirectResponse(url="/login", status_code=303)
        except Exception:
            return templates.TemplateResponse("register.html", {"request": request, "error": "Username already exists"})

@app.get("/logout", include_in_schema=False)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.post("/generate_apikey", include_in_schema=False)
async def generate_apikey(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse(url="/login")
    
    new_api_key = secrets.token_hex(16)
    async with aiosqlite.connect(system_db_path) as db:
        await db.execute("UPDATE users SET api_key=? WHERE username=?", (new_api_key, user))
        await db.commit()
    
    return RedirectResponse(url="/", status_code=303)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    user = request.session.get("user")
    api_key = await get_user_api_key(user)
    db_path = f"storage/{user}/history/logs.db"
    log_count = 0
    recent_logs = []
    
    if os.path.exists(db_path):
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT COUNT(id) FROM logs") as cursor:
                log_count = (await cursor.fetchone())[0]
                
            async with db.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 5") as cursor:
                columns = [col[0] for col in cursor.description]
                recent_logs = [dict(zip(columns, row)) for row in await cursor.fetchall()]
            
    # Check if ANY device is connected
    is_connected = False
    connected_devices = []
    for sid, status in bot_status.items():
        if sid.startswith(f"{user}:") and status:
            is_connected = True
            connected_devices.append(sid.split(":")[1])
            
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "api_key": api_key,
        "is_connected": is_connected,
        "connected_devices": connected_devices,
        "log_count": log_count,
        "recent_logs": recent_logs
    })

@app.get("/devices", response_class=HTMLResponse, include_in_schema=False)
async def devices_page(request: Request):
    user = request.session.get("user")
    
    # Get all sessions for this user
    user_devices = []
    sessions_dir = f"storage/{user}/sessions"
    if os.path.exists(sessions_dir):
        for f in os.listdir(sessions_dir):
            if f.endswith(".sqlite3"):
                phone = f.replace(".sqlite3", "")
                if phone == "session": continue
                session_id = f"{user}:{phone}"
                user_devices.append({
                    "phone": phone,
                    "is_connected": bot_status.get(session_id, False),
                    "bot_number": bot_numbers.get(session_id, phone)
                })
    
    return templates.TemplateResponse("devices.html", {
        "request": request,
        "user": user,
        "devices": user_devices
    })

@app.get("/logs", response_class=HTMLResponse, include_in_schema=False)
async def logs_page(request: Request):
    user = request.session.get("user")

    db_path = f"storage/{user}/history/logs.db"
    logs = []
    if os.path.exists(db_path):
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 50") as cursor:
                columns = [col[0] for col in cursor.description]
                logs = [dict(zip(columns, row)) for row in await cursor.fetchall()]

    return templates.TemplateResponse("logs.html", {
        "request": request,
        "user": user,
        "logs": logs
    })

@app.get("/tools", response_class=HTMLResponse, include_in_schema=False)
async def tools_page(request: Request):
    user = request.session.get("user")
    api_key = await get_user_api_key(user)
    
    # Get all potential devices from files
    user_devices = []
    sessions_dir = f"storage/{user}/sessions"
    if os.path.exists(sessions_dir):
        for f in os.listdir(sessions_dir):
            if f.endswith(".sqlite3"):
                phone = f.replace(".sqlite3", "")
                if phone == "session": continue
                session_id = f"{user}:{phone}"
                # Only include if actually connected in memory
                if bot_status.get(session_id, False):
                    user_devices.append(phone)

    return templates.TemplateResponse("tools.html", {
        "request": request,
        "user": user,
        "api_key": api_key,
        "devices": user_devices
    })

@app.get("/blast", response_class=HTMLResponse, include_in_schema=False)
async def blast_page(request: Request):
    user = request.session.get("user")
    
    # Get connected devices for the user
    user_devices = []
    for sid, status in bot_status.items():
        if sid.startswith(f"{user}:") and status:
            user_devices.append(sid.split(":")[1])
            
    return templates.TemplateResponse("blast.html", {
        "request": request,
        "user": user,
        "devices": user_devices
    })

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
            await log_message(username, f"BLAST({device_phone})", target, f"[OUT] {final_msg[:50]}...")
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

@app.post("/api/pair", include_in_schema=False)
async def pair_device(phone: str = Form(...), request: Request = None):
    # This is an internal API for the web dashboard, uses session auth.
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    
    phone_clean = normalize_wa(phone)
    session_id = f"{user}:{phone_clean}"
    
    if bot_status.get(session_id, False):
        raise HTTPException(status_code=400, detail="Device is already connected")
    
    if session_id not in clients:
        await init_user_db(user)
        # Ensure directory exists
        os.makedirs(f"storage/{user}/sessions", exist_ok=True)
        start_neonize(user, phone_clean)
        # Reduced sleep time for faster response
        await asyncio.sleep(0.5)
        
    try:
        client = clients[session_id]
        result = client.PairPhone(phone_clean, show_push_notification=True)
        code = await result if asyncio.iscoroutine(result) else result
        return {"success": True, "code": code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/logout_device", include_in_schema=False)
async def logout_device(request: Request, phone: str = Form(...)):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    
    phone_clean = normalize_wa(phone)
    session_id = f"{user}:{phone_clean}"
    session_path = f"storage/{user}/sessions/{phone_clean}.sqlite3"
    
    try:
        if session_id in clients:
            client = clients[session_id]
            if bot_status.get(session_id, False):
                try: await client.logout()
                except: pass
            else:
                try: await client.disconnect()
                except: pass
            del clients[session_id]
        
        bot_status[session_id] = False
        if session_id in bot_numbers: del bot_numbers[session_id]
        
        if os.path.exists(session_path):
            await asyncio.sleep(0.5)
            try: os.remove(session_path)
            except: pass
            
        return {"success": True, "message": "Session cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/internal_status", include_in_schema=False)
async def internal_status(request: Request, phone: str):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    
    phone_clean = normalize_wa(phone)
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

    session_id = f"{username}:{normalize_wa(phone)}"
    return {
        "status": "online" if bot_status.get(session_id, False) else "offline",
        "bot_number": bot_numbers.get(session_id, None),
        "user": username,
        "device": phone
    }

@app.get("/api/device/pair")
async def api_pair_device(phone: str, username: str = Depends(verify_api_key)):
    """External API: Get pairing code for a phone number"""
    phone_clean = normalize_wa(phone)
    session_id = f"{username}:{phone_clean}"
    
    if bot_status.get(session_id, False):
        raise HTTPException(status_code=400, detail="Device is already connected")
    
    if session_id not in clients:
        await init_user_db(username)
        os.makedirs(f"storage/{username}/sessions", exist_ok=True)
        start_neonize(username, phone_clean)
        await asyncio.sleep(0.5)
        
    try:
        client = clients[session_id]
        result = client.PairPhone(phone_clean, show_push_notification=True)
        code = await result if asyncio.iscoroutine(result) else result
        return {"success": True, "code": code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/device/logout")
async def api_logout_device(phone: str, username: str = Depends(verify_api_key)):
    """External API: Logout and delete WhatsApp session"""
    phone_clean = normalize_wa(phone)
    session_id = f"{username}:{phone_clean}"
    session_path = f"storage/{username}/sessions/{phone_clean}.sqlite3"
    
    if session_id not in clients and not os.path.exists(session_path):
        raise HTTPException(status_code=404, detail="No session found for this device")
    
    try:
        if session_id in clients:
            client = clients[session_id]
            if bot_status.get(session_id, False):
                await client.logout()
            else:
                await client.disconnect()
            del clients[session_id]
            
        bot_status[session_id] = False
        if session_id in bot_numbers: del bot_numbers[session_id]
        
        if os.path.exists(session_path):
            await asyncio.sleep(0.5)
            try: os.remove(session_path)
            except: pass
            
        return {"success": True, "message": f"Device {phone_clean} logged out and session cleared"}
    except Exception as e:
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
            
        await log_message(username, f"API({p})", to, f"[OUT] {text}")
        return {"success": True, "message": "Text message sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-image")
async def api_send_image(to: str, image_url: str, caption: Optional[str] = "", mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send an image via URL using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    
    target_jid = get_target_jid(to)
    try:
        mentioned_jids = await get_mentions_list(client, target_jid, mentions)
        if mentioned_jids:
            msg = await client.build_image_message(image_url, caption=caption)
            msg.imageMessage.contextInfo.mentionedJID.extend(mentioned_jids)
            await client.send_message(target_jid, msg)
        else:
            await client.send_image(target_jid, image_url, caption=caption)
            
        await log_message(username, f"API({p})", to, f"[OUT IMAGE] {image_url} | Caption: {caption}")
        return {"success": True, "message": "Image sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-audio")
async def api_send_audio(to: str, audio_url: str, ptt: bool = False, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send audio using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        await client.send_audio(target_jid, audio_url, ptt=ptt)
        await log_message(username, f"API({p})", to, f"[OUT AUDIO] {audio_url}")
        return {"success": True, "message": "Audio sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-video")
async def api_send_video(to: str, video_url: str, caption: Optional[str] = "", viewonce: bool = False, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send video using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        mentioned_jids = await get_mentions_list(client, target_jid, mentions)
        if mentioned_jids:
            msg = await client.build_video_message(video_url, caption=caption, viewonce=viewonce)
            msg.videoMessage.contextInfo.mentionedJID.extend(mentioned_jids)
            await client.send_message(target_jid, msg)
        else:
            await client.send_video(target_jid, video_url, caption=caption, viewonce=viewonce)
            
        await log_message(username, f"API({p})", to, f"[OUT VIDEO] {video_url} | Caption: {caption}")
        return {"success": True, "message": "Video sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-document")
async def api_send_document(to: str, document_url: str, caption: Optional[str] = "", title: Optional[str] = "", filename: Optional[str] = "", mimetype: Optional[str] = "", phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send document using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        await client.send_document(target_jid, document_url, caption=caption, title=title, filename=filename, mimetype=mimetype)
        await log_message(username, f"API({p})", to, f"[OUT DOCUMENT] {document_url} | Name: {filename}")
        return {"success": True, "message": "Document sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-sticker")
async def api_send_sticker(to: str, sticker_url: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send sticker using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        await client.send_sticker(target_jid, sticker_url)
        await log_message(username, f"API({p})", to, f"[OUT STICKER] {sticker_url}")
        return {"success": True, "message": "Sticker sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-contact")
async def api_send_contact(to: str, contact_name: str, contact_number: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send contact card using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        await client.send_contact(target_jid, contact_name, contact_number)
        await log_message(username, f"API({p})", to, f"[OUT CONTACT] {contact_name} ({contact_number})")
        return {"success": True, "message": "Contact sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-interactive")
async def api_send_interactive_get(to: str, payload: str, media_url: Optional[str] = None, media_type: Optional[str] = "image", mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Send interactive message via GET.
    Payload must be a JSON string.
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    
    target_jid = get_target_jid(to)
    try:
        data = json.loads(payload)
        
        # 1. Handle media from parameters
        if media_url:
            if "header" not in data: data["header"] = {}
            data["header"]["hasMediaAttachment"] = True
            if media_type == "video":
                data["header"]["videoMessage"] = (await client.build_video_message(media_url)).videoMessage
            else:
                data["header"]["imageMessage"] = (await client.build_image_message(media_url)).imageMessage
        
        # 2. Handle media already inside the JSON payload (convert URL/dict to proto)
        header = data.get("header", {})
        if header.get("hasMediaAttachment"):
            if "imageMessage" in header:
                val = header["imageMessage"]
                # Jika masih string (URL) atau dict (URL), convert ke proto
                url = val if isinstance(val, str) else val.get("URL") or val.get("url")
                if url:
                    header["imageMessage"] = (await client.build_image_message(url)).imageMessage
            elif "videoMessage" in header:
                val = header["videoMessage"]
                url = val if isinstance(val, str) else val.get("URL") or val.get("url")
                if url:
                    header["videoMessage"] = (await client.build_video_message(url)).videoMessage

        mentioned_jids = await get_mentions_list(client, target_jid, mentions)
        if mentioned_jids:
            if "contextInfo" not in data:
                data["contextInfo"] = {}
            data["contextInfo"]["mentionedJID"] = mentioned_jids

        msg = WAMessage(interactiveMessage=data)
        await client.send_message(target_jid, msg)
        await log_message(username, f"API({p})", to, f"[OUT INTERACTIVE]")
        return {"success": True, "message": "Interactive message sent successfully", "to": to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class InteractivePayload(BaseModel):
    to: str
    payload: dict
    phone: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = "image" # image or video
    mentions: Optional[str] = None

@app.post("/api/send-interactive")
async def api_send_interactive_post(data: InteractivePayload, username: str = Depends(verify_api_key)):
    """
    External API: Send interactive message via POST.
    """
    client, p = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    
    target_jid = get_target_jid(data.to)
    payload = data.payload
    
    # 1. Handle media from parameters
    if data.media_url:
        if "header" not in payload: payload["header"] = {}
        payload["header"]["hasMediaAttachment"] = True
        if data.media_type == "video":
            payload["header"]["videoMessage"] = (await client.build_video_message(data.media_url)).videoMessage
        else:
            payload["header"]["imageMessage"] = (await client.build_image_message(data.media_url)).imageMessage
    
    # 2. Handle media already inside the JSON payload (convert URL/dict to proto)
    header = payload.get("header", {})
    if header.get("hasMediaAttachment"):
        if "imageMessage" in header:
            val = header["imageMessage"]
            url = val if isinstance(val, str) else val.get("URL") or val.get("url")
            if url:
                header["imageMessage"] = (await client.build_image_message(url)).imageMessage
        elif "videoMessage" in header:
            val = header["videoMessage"]
            url = val if isinstance(val, str) else val.get("URL") or val.get("url")
            if url:
                header["videoMessage"] = (await client.build_video_message(url)).videoMessage

    try:
        mentioned_jids = await get_mentions_list(client, target_jid, data.mentions)
        if mentioned_jids:
            if "contextInfo" not in payload:
                payload["contextInfo"] = {}
            payload["contextInfo"]["mentionedJID"] = mentioned_jids

        msg = WAMessage(interactiveMessage=payload)
        await client.send_message(target_jid, msg)
        await log_message(username, f"API({p})", data.to, f"[OUT INTERACTIVE]")
        return {"success": True, "message": "Interactive message sent successfully", "to": data.to, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-status")
async def api_send_status(type: str, text: Optional[str] = "", url: Optional[str] = "", mentions: Optional[str] = None, hd: bool = False, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Send WhatsApp Status (Story)
    type: 'text', 'image', or 'video'
    hd: True for HD quality (if supported by source)
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    status_jid = str_to_jid("status@broadcast")
    try:
        mentioned_jids = await get_mentions_list(client, status_jid, mentions)
        
        if type == "text":
            if mentioned_jids:
                context_info = ContextInfo(mentionedJID=mentioned_jids)
                msg = WAMessage(extendedTextMessage=ExtendedTextMessage(text=text, contextInfo=context_info))
                await client.send_message(status_jid, msg)
            else:
                await client.send_message(status_jid, text)
            await log_message(username, f"API({p})", "status@broadcast", f"[STATUS TEXT] {text}")
        elif type == "image":
            if mentioned_jids:
                msg = await client.build_image_message(url, caption=text)
                # Pastikan contextInfo ada dan masukkan tag
                if not msg.imageMessage.HasField("contextInfo"):
                    msg.imageMessage.contextInfo.SetInParent()
                msg.imageMessage.contextInfo.mentionedJID.extend(mentioned_jids)
                await client.send_message(status_jid, msg)
            else:
                await client.send_image(status_jid, url, caption=text)
            await log_message(username, f"API({p})", "status@broadcast", f"[STATUS IMAGE] {url} {'(HD)' if hd else ''}")
        elif type == "video":
            if mentioned_jids:
                msg = await client.build_video_message(url, caption=text)
                # Pastikan contextInfo ada dan masukkan tag
                if not msg.videoMessage.HasField("contextInfo"):
                    msg.videoMessage.contextInfo.SetInParent()
                msg.videoMessage.contextInfo.mentionedJID.extend(mentioned_jids)
                await client.send_message(status_jid, msg)
            else:
                await client.send_video(status_jid, url, caption=text)
            await log_message(username, f"API({p})", "status@broadcast", f"[STATUS VIDEO] {url} {'(HD)' if hd else ''}")
        else:
            raise HTTPException(status_code=400, detail="Invalid status type. Use 'text', 'image', or 'video'")
        
        return {"success": True, "message": f"Status sent successfully {'(HD)' if hd else ''}", "device": p}
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
    """External API: Check if a number is registered on WhatsApp"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    clean_phone = normalize_wa(phone_to_check)
    try:
        res = client.is_on_whatsapp(clean_phone)
        if res and len(res) > 0:
            return {
                "success": True,
                "phone": phone_to_check,
                "is_registered": res[0].IsIn,
                "jid": res[0].JID.User + "@" + res[0].JID.Server if res[0].IsIn else None,
                "device": p
            }
        return {"success": True, "phone": phone_to_check, "is_registered": False, "device": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8880, reload=False)
