"""WhatsApp client events, pairing, and worker cleanup."""
import asyncio
import logging
import os
import time
from typing import Optional

from fastapi import HTTPException
from neonize.aioze.events import (
    CallOfferEv,
    ConnectFailureEv,
    ConnectedEv,
    DisconnectedEv,
    KeepAliveRestoredEv,
    KeepAliveTimeoutEv,
    LoggedOutEv,
    MessageEv,
    NewsletterJoinEv,
)

from gateway.database import init_user_db, log_message
from gateway.messages.store import store as ms
from gateway.services.auto_reply import try_airich_auto_reply
from gateway.services.customer_service import try_customer_service
from gateway.services.profile_privacy import auto_read_message
from gateway.services.ping import build_ping_reply, ping_enabled
from gateway.state import bot_numbers, bot_status, client_cleanup_tasks, clients, pairing_sessions
from gateway.whatsapp.addressing import normalize_phone_number
from gateway.whatsapp.runtime import GatewayClient as NewAClient
from gateway.whatsapp.serialization import Mess


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
        received_at = time.perf_counter()
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
                await auto_read_message(c, username, phone, m)
                auto_replied = await try_customer_service(c, username, phone, m)
                if not auto_replied:
                    auto_replied = await try_airich_auto_reply(c, username, phone, m)
                if not auto_replied and not m.is_edit and m.text and m.text.strip().lower() == "ping" and ping_enabled(username):
                    await m.reply(await build_ping_reply(received_at))
        except Exception as e:
            logging.getLogger(__name__).exception("on_message failed for session %s", session_id)
    if auto_connect:
        asyncio.create_task(client.connect())


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
