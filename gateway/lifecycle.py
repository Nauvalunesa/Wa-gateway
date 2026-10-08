"""Application startup, session restoration, and shutdown."""
import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
import os

from fastapi import FastAPI

from gateway.database import init_system_db, init_user_db
from gateway.state import clients
from gateway.whatsapp.clients import start_neonize, get_client
from gateway.services.customer_service import inactivity_worker


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

    idle_task = asyncio.create_task(inactivity_worker(get_client))
    try:
        yield
    finally:
        idle_task.cancel()
        with suppress(asyncio.CancelledError):
            await idle_task

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
