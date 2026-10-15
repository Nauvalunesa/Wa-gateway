"""SQLite initialization, migrations, and message history."""
from datetime import datetime
import os

import aiosqlite

from gateway.config import system_db_path


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
        if not os.path.exists(db_path):
            await init_user_db(username)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO logs (timestamp, sender, receiver, message, type) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sender, receiver, message, msg_type)
            )
            await db.commit()
    except Exception as e:
        if "no column named sender" in str(e) or "no column named type" in str(e) or "no such table: logs" in str(e):
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
