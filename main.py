import asyncio
import os
import secrets
from datetime import datetime
from contextlib import asynccontextmanager
import aiosqlite
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Form, Depends, Header, File, UploadFile, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import shutil
import subprocess
import tempfile
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict
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

from neonize.aioze.client import NewAClient
from neonize.events import ConnectedEv, MessageEv, DisconnectedEv, LoggedOutEv, QREv, ConnectFailureEv, KeepAliveTimeoutEv, CallOfferEv, NewsletterJoinEv
from neonize.proto.Neonize_pb2 import JID
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message as WAMessage, ContextInfo, ExtendedTextMessage, InteractiveMessage
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

async def process_video(url: str, request: Request = None, hd: bool = False) -> str:
    """
    Downloads, compresses, and converts video to WhatsApp-compatible format (H.264/AAC).
    Returns a local file path or the original URL if processing fails.
    """
    try:
        import httpx
        import magic
        
        ext = ".mp4"
        # Create temp files
        input_temp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        output_temp_path = input_temp.name.replace(ext, "_processed" + ext)
        
        # Optimization: Check if URL is local
        is_local = False
        if request:
            base_url = str(request.base_url).rstrip("/")
            if url.startswith(base_url):
                local_path = url.replace(base_url + "/", "")
                if os.path.exists(local_path):
                    shutil.copy(local_path, input_temp.name)
                    input_temp.close()
                    is_local = True

        if not is_local:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=60.0)
                if resp.status_code == 200:
                    input_temp.write(resp.content)
                    input_temp.close()
                else:
                    return url
        
        # FFmpeg command for WhatsApp: 
        # - H.264 video codec
        # - AAC audio codec
        # - HD: No downscale, lower CRF (higher quality)
        # - SD: Scale to max 720p, CRF 24
        
        # Base commands
        cmd = [
            "ffmpeg", "-y", "-i", input_temp.name,
            "-c:v", "libx264", "-profile:v", "main", "-level:v", "4.0",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k"
        ]
        
        if hd:
            # HD: Keep resolution but ensure dimensions are even (required by H.264)
            cmd += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-crf", "18"]
        else:
            # SD: Downscale to 720p
            cmd += ["-vf", "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(720,ih))',pad=ceil(iw/2)*2:ceil(ih/2)*2", "-crf", "24"]
            
        cmd += ["-preset", "faster", "-movflags", "+faststart", output_temp_path]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Move to static/uploads to make it accessible via URL
            final_filename = f"optimized_{os.path.basename(output_temp_path)}"
            final_path = os.path.join("static/uploads", final_filename)
            shutil.move(output_temp_path, final_path)
            
            # Cleanup input temp
            if os.path.exists(input_temp.name): os.remove(input_temp.name)
            
            return final_path
        else:
            print(f"❌ FFmpeg error: {stderr.decode()}")
            if os.path.exists(input_temp.name): os.remove(input_temp.name)
            if os.path.exists(output_temp_path): os.remove(output_temp_path)
            return url
    except Exception as e:
        print(f"❌ Video processing failed: {e}")
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

                        file_path = os.path.join(sessions_dir, session_file)
                        file_size = os.path.getsize(file_path)

                        if file_size < 200000:
                            print(f"🧹 Skipping and cleaning phantom session: {session_file}")
                            try: os.remove(file_path)
                            except: pass
                            continue

                        start_neonize(item, phone)

    yield

    # Shutdown
    print("🔌 Shutting down WhatsApp Gateway...")
    for user, client in clients.items():
        try:
            if asyncio.iscoroutinefunction(client.disconnect):
                await client.disconnect()
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
    # Daftar rute publik (API eksternal & assets)
    public_prefixes = ["/api/send-", "/api/status", "/api/check-", "/api/device/", "/api/groups", "/api/group-info", "/api/convert-jid", "/api/newsletter/", "/docs", "/openapi.json", "/static", "/favicon.ico"]
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
# ... (imports)
clients: Dict[str, NewAClient] = {}
bot_status: Dict[str, bool] = {}
bot_numbers: Dict[str, str] = {}
pairing_sessions = set() # Track sessions that are currently pairing
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
        
    print(f"🚀 Initializing WhatsApp Client for user [{username}] with phone [{phone}]...")
    session_path = f"storage/{username}/sessions/{phone}.sqlite3"
    client = NewAClient(session_path)
    clients[session_id] = client
    bot_status[session_id] = False
    
    @client.event(QREv)
    async def on_qr(c, qr_code):
        # Don't kill if we are in the middle of a pairing attempt
        if session_id in pairing_sessions:
            print(f"ℹ️ [{session_id}] QR Code generated, but skipping auto-delete because pairing is active.")
            return

        # LOUD LOG for the user to see in PM2
        print(f"\n" + "!"*60)
        print(f"⚠️  SESSION INVALID: User [{username}] | Device [{phone}]")
        print(f"⚠️  QR Code appeared in logs. Automatically deleting this session.")
        print("!"*60 + "\n")
        
        bot_status[session_id] = False
        try:
            await c.disconnect()
        except:
            pass
            
        # Give a small delay to let library close the file
        await asyncio.sleep(2)
        
        if os.path.exists(session_path):
            try:
                os.remove(session_path)
                print(f"🗑️  [{session_id}] Session file deleted successfully.")
            except Exception as e:
                print(f"❌ [{session_id}] Failed to delete session file: {e}")
        
        if session_id in clients:
            del clients[session_id]
        if session_id in bot_numbers:
            del bot_numbers[session_id]

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
        if session_id in bot_numbers:
            del bot_numbers[session_id]

    @client.event(ConnectFailureEv)
    async def on_connect_failure(c, _):
        bot_status[session_id] = False
        print(f"❌ [{session_id}] Login event: timeout / Connect Failure! Menghapus session...")
        try:
            await c.disconnect()
        except:
            pass
            
        if os.path.exists(session_path):
            await asyncio.sleep(2) # Give more time for the lib to release the file
            try:
                os.remove(session_path)
                print(f"🗑️ [{session_id}] File session dihapus karena timeout/gagal connect.")
            except Exception as e:
                print(f"❌ [{session_id}] Gagal menghapus session timeout: {e}")
        
        if session_id in clients:
            del clients[session_id]
        if session_id in bot_numbers:
            del bot_numbers[session_id]

    @client.event(KeepAliveTimeoutEv)
    async def on_keepalive_timeout(c, _):
        bot_status[session_id] = False
        print(f"⏰ [{session_id}] KeepAlive Timeout! Menghapus session...")
        try:
            await c.disconnect()
        except:
            pass
            
        if os.path.exists(session_path):
            await asyncio.sleep(2)
            try:
                os.remove(session_path)
                print(f"🗑️ [{session_id}] File session dihapus karena KeepAlive timeout.")
            except Exception as e:
                print(f"❌ [{session_id}] Gagal menghapus session: {e}")
        
        if session_id in clients:
            del clients[session_id]
        if session_id in bot_numbers:
            del bot_numbers[session_id]

    @client.event(CallOfferEv)
    async def on_call_offer(c, call):
        caller = call.BasicCallMeta.From
        print(f"📞 [{session_id}] Incoming call from {caller}")

    @client.event(NewsletterJoinEv)
    async def on_newsletter_join(c, event):
        print(f"📰 [{session_id}] Newsletter Join/Update: {event}")

    @client.event(MessageEv)
    async def on_message(c, message):
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
                # No logging for incoming messages
                if m.text and m.text.lower() == "ping":
                    await m.reply("pong!")
        except Exception as e:
            print(f"❌ [{session_id}] Error in on_message: {e}")
    asyncio.create_task(client.connect())

# =======================
# API KEY DEPENDENCY
# =======================
async def verify_api_key(x_api_key: Optional[str] = Header(None), key: Optional[str] = None) -> str:
    # Check Header first, then Query Param
    api_key = x_api_key or key

    if not api_key:
        raise HTTPException(status_code=401, detail="API Key is missing (use x-api-key header or ?key= query param)")

    async with aiosqlite.connect(system_db_path) as db:
        async with db.execute("SELECT username FROM users WHERE api_key=?", (api_key,)) as cursor:
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
    return templates.TemplateResponse(request, "login.html")

@app.post("/login", include_in_schema=False)
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    async with aiosqlite.connect(system_db_path) as db:
        # Check if user exists first
        async with db.execute("SELECT * FROM users WHERE username=?", (username,)) as cursor:
            columns = [col[0] for col in cursor.description]
            user_row = await cursor.fetchone()
            if not user_row:
                # User not found, redirect to register with info
                return templates.TemplateResponse(request, "login.html", {
                    "request": request, 
                    "error": "Account not found. Please register first.",
                    "redirect_to_register": True
                })
            
            user = dict(zip(columns, user_row))
        
        # Verify password hash
        if verify_password(password, user['password']):
            request.session["user"] = username
            await init_user_db(username)
            return RedirectResponse(url="/", status_code=303)
        else:
            return templates.TemplateResponse(request, "login.html", {"error": "Invalid password"})

@app.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")

@app.post("/register", include_in_schema=False)
async def do_register(request: Request, username: str = Form(...), password: str = Form(...)):
    if not username.isalnum():
        return templates.TemplateResponse(request, "register.html", {"error": "Username must be alphanumeric"})
        
    new_api_key = secrets.token_hex(16)
    hashed_pw = hash_password(password)
    async with aiosqlite.connect(system_db_path) as db:
        try:
            await db.execute("INSERT INTO users (username, password, api_key) VALUES (?, ?, ?)", (username, hashed_pw, new_api_key))
            await db.commit()
            return RedirectResponse(url="/login", status_code=303)
        except Exception:
            return templates.TemplateResponse(request, "register.html", {"error": "Username already exists"})

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
            
    return templates.TemplateResponse(request, "dashboard.html", {
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
    
    return templates.TemplateResponse(request, "devices.html", {
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

    api_key = await get_user_api_key(user)

    return templates.TemplateResponse(request, "logs.html", {
        "request": request,
        "user": user,
        "api_key": api_key,
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

    return templates.TemplateResponse(request, "tools.html", {
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
            
    return templates.TemplateResponse(request, "blast.html", {
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

@app.post("/api/pair", include_in_schema=False)
async def pair_device(phone: str = Form(...), request: Request = None):
    # This is an internal API for the web dashboard, uses session auth.
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    
    phone_clean = normalize_wa(phone)
    # WhatsApp pairing usually expects + prefix
    phone_for_pairing = "+" + phone_clean if not phone_clean.startswith("+") else phone_clean
    session_id = f"{user}:{phone_clean}"
    
    if bot_status.get(session_id, False):
        raise HTTPException(status_code=400, detail="Device is already connected")
    
    # Mark as pairing attempt
    pairing_sessions.add(session_id)
    
    try:
        # 1. Be extremely aggressive in clearing existing client
        if session_id in clients:
            print(f"🧹 Clearing existing client for {session_id} to start fresh...")
            old_client = clients[session_id]
            try:
                # Try logout first if connected, then disconnect
                if bot_status.get(session_id, False):
                    await old_client.logout()
                await old_client.disconnect()
            except: 
                pass
            
            # Small delay to let OS release file locks
            await asyncio.sleep(1.0)
            del clients[session_id]
            bot_status[session_id] = False

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
        start_neonize(user, phone_clean)
        
        # Give more time for the new client to reach the pairing-ready state
        await asyncio.sleep(3.0)
            
        client = clients.get(session_id)
        if not client:
            raise HTTPException(status_code=500, detail="Failed to initialize new client")
            
        print(f"📲 Requesting Pairing Code for {phone_for_pairing}...")
        result = client.PairPhone(phone_for_pairing, show_push_notification=True)
        code = await result if asyncio.iscoroutine(result) else result
        
        if not code:
            raise Exception("WhatsApp server returned empty code. Try again.")
            
        return {"success": True, "code": code}
    except Exception as e:
        # Cleanup on failure
        if session_id in pairing_sessions:
            pairing_sessions.remove(session_id)
        print(f"❌ Pairing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Keep protected for 2 minutes to allow user to enter code
        async def delayed_remove():
            await asyncio.sleep(120) 
            if session_id in pairing_sessions:
                pairing_sessions.remove(session_id)
        asyncio.create_task(delayed_remove())

@app.post("/api/logout_device", include_in_schema=False)
async def logout_device(request: Request, phone: str = Form(...)):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    
    phone_clean = normalize_wa(phone)
    session_id = f"{user}:{phone_clean}"
    session_path = f"storage/{user}/sessions/{phone_clean}.sqlite3"
    
    print(f"🗑️ Attempting to logout and delete session for {session_id}...")
    
    try:
        # 1. Cleanup client
        if session_id in clients:
            client = clients[session_id]
            try:
                if bot_status.get(session_id, False):
                    print(f"🔌 Sending logout command to WhatsApp...")
                    await client.logout()
                else:
                    print(f"🔌 Disconnecting client...")
                    await client.disconnect()
            except Exception as e:
                print(f"⚠️ Error during client logout/disconnect: {e}")
                # Force disconnect if logout failed
                try: await client.disconnect()
                except: pass
            
            # Remove from tracking
            del clients[session_id]
        
        bot_status[session_id] = False
        if session_id in bot_numbers: del bot_numbers[session_id]
        
        # 2. Delete file with retry
        if os.path.exists(session_path):
            print(f"📂 Deleting session file: {session_path}")
            # Wait a bit for file handles to close
            await asyncio.sleep(1.0)
            
            deleted = False
            for i in range(5):
                try:
                    os.remove(session_path)
                    print(f"✅ Session file {session_path} deleted on attempt {i+1}.")
                    deleted = True
                    break
                except Exception as e:
                    print(f"⚠️ Failed to delete session file (attempt {i+1}): {e}")
                    await asyncio.sleep(1.0)
            
            if not deleted:
                print(f"❌ Failed to delete session file after 5 attempts.")
                # We still return success True because the memory state is cleared,
                # but it might reappear on restart.
            
        return {"success": True, "message": "Session cleared"}
    except Exception as e:
        print(f"❌ Error in logout_device: {e}")
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
            
            del clients[session_id]
            
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
        if mentioned_jids:
            msg = await client.build_image_message(img_to_send, caption=caption)
            msg.imageMessage.contextInfo.mentionedJID.extend(mentioned_jids)
            await client.send_message(target_jid, msg)
        else:
            await client.send_image(target_jid, img_to_send, caption=caption)
            
        await log_message(username, f"DEVICE({p})", to, f"[IMAGE] {image_url} | {caption}", "OUTGOING")
        return {"success": True, "message": f"Image sent successfully {'(HD)' if hd else ''}", "to": to, "device": p}
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
        if mentioned_jids:
            msg = await client.build_video_message(video_url_to_send, caption=caption, viewonce=viewonce)
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
            # Some neonize versions might support high_quality=True or similar in protobuf
            # For now we use the helper but log the intent
            await client.send_image(target_jid, media_to_send, caption=caption or text)
        elif type == "video":
            await client.send_video(target_jid, media_to_send, caption=caption or text)
        elif type == "audio":
            await client.send_audio(target_jid, media_to_send)
        elif type == "document":
            await client.send_document(target_jid, media_to_send, caption=caption or text)
        else:
            raise HTTPException(status_code=400, detail="Unsupported message type for newsletter")
            
        await log_message(username, f"DEVICE({p})", str(target_jid), f"[NEWSLETTER] {type.upper()} | {caption or text}", "OUTGOING")
        return {"success": True, "message": f"{type.capitalize()} sent to newsletter {'(HD)' if hd else ''}"}
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
async def api_newsletter_create(name: str, description: str = "", phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Create a Newsletter (Channel)"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        res = await client.create_newsletter(name, description)
        return {"success": True, "message": "Newsletter created successfully", "info": MessageToDict(res)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-contact")
async def api_send_contact(to: str, contact_name: str, contact_number: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send contact card using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = await get_actual_jid(client, to)
    try:
        await client.send_contact(target_jid, contact_number, contact_name)
        await log_message(username, f"DEVICE({p})", to, f"[CONTACT] {contact_name} ({contact_number})", "OUTGOING")
        return {"success": True, "message": "Contact card sent successfully", "to": to, "device": p}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-interactive")
async def api_send_interactive_get(request: Request, to: str, payload: str, media_url: Optional[str] = None, media_type: Optional[str] = "image", mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Send interactive message via GET.
    Payload must be a JSON string.
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    
    target_jid = await get_actual_jid(client, to)
    try:
        data = json.loads(payload)
        
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
                optimized_url = await process_video(media_url, request)
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
                        optimized_url = await process_video(url, request)
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
async def api_send_interactive_post(request: Request, data: InteractivePayload, username: str = Depends(verify_api_key)):
    """
    External API: Send interactive message via POST.
    """
    client, p = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    
    target_jid = await get_actual_jid(client, data.to)
    payload = data.payload
    
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
            optimized_url = await process_video(data.media_url, request)
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
                    optimized_url = await process_video(url, request)
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/send-status")
async def api_send_status(request: Request, type: str, text: Optional[str] = "", url: Optional[str] = "", mentions: Optional[str] = None, hd: bool = False, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
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
            if mentioned_jids:
                msg = await client.build_image_message(media_to_send, caption=text)
                # Pastikan contextInfo ada dan masukkan tag
                if not msg.imageMessage.HasField("contextInfo"):
                    msg.imageMessage.contextInfo.SetInParent()
                msg.imageMessage.contextInfo.mentionedJID.extend(mentioned_jids)
                await client.send_message(status_jid, msg)
            else:
                await client.send_image(status_jid, media_to_send, caption=text)
            await log_message(username, f"DEVICE({p})", "status@broadcast", f"[STATUS IMAGE] {url} | {text}", "OUTGOING")
        elif type == "video":
            if mentioned_jids:
                msg = await client.build_video_message(media_to_send, caption=text)
                # Pastikan contextInfo ada dan masukkan tag
                if not msg.videoMessage.HasField("contextInfo"):
                    msg.videoMessage.contextInfo.SetInParent()
                msg.videoMessage.contextInfo.mentionedJID.extend(mentioned_jids)
                await client.send_message(status_jid, msg)
            else:
                await client.send_video(status_jid, media_to_send, caption=text)
            await log_message(username, f"DEVICE({p})", "status@broadcast", f"[STATUS VIDEO] {url} | {text}", "OUTGOING")
        else:
            raise HTTPException(status_code=400, detail="Invalid status type. Use 'text', 'image', or 'video'")
        
        return {"success": True, "message": f"Status sent successfully {'(HD)' if hd else ''}", "device": p}
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
        await log_message(username, f"DEVICE({p})", to, f"[GROUP STATUS {type.upper()}] {text}", "OUTGOING")
        
        return {"success": True, "message": f"Group Status sent successfully", "to": to, "device": p}
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
