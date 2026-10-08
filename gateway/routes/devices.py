"""Devices API routes."""
import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse

from gateway.security import verify_api_key
from gateway.state import bot_numbers, bot_status, client_cleanup_tasks, clients, pairing_sessions
from gateway.whatsapp.addressing import normalize_phone_number
from gateway.whatsapp.clients import discard_failed_pairing_client, request_pairing_code


router = APIRouter()


@router.post("/api/pair", include_in_schema=False)
async def pair_device(phone: str = Form(...), request: Request = None):
    # This is an internal API for the web dashboard, uses session auth.
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    return await request_pairing_code(user, phone)


@router.get("/api/device/download_session", include_in_schema=False)
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


@router.post("/api/logout_device", include_in_schema=False)
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


@router.get("/api/internal_status", include_in_schema=False)
async def internal_status(request: Request, phone: str):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")

    phone_clean = normalize_phone_number(phone)
    session_id = f"{user}:{phone_clean}"

    return {
        "status": "online" if bot_status.get(session_id, False) else "offline",
        "bot_number": bot_numbers.get(session_id, phone_clean)
    }


@router.get("/api/status")
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


@router.get("/api/device/pair")
async def api_pair_device(phone: str, username: str = Depends(verify_api_key)):
    """External API: Get pairing code for a phone number"""
    return await request_pairing_code(username, phone)


@router.get("/api/device/logout")
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
