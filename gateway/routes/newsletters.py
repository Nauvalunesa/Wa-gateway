"""Newsletters API routes."""
import asyncio
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from google.protobuf.json_format import MessageToDict

from gateway.database import log_message
from gateway.security import verify_api_key
from gateway.whatsapp.addressing import get_actual_jid
from gateway.whatsapp.clients import get_client
from gateway.whatsapp.serialization import str_to_jid


router = APIRouter()


@router.post("/api/newsletter/send")
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


@router.get("/api/newsletter/list")
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


@router.get("/api/newsletter/info-by-invite")
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


@router.get("/api/newsletter/info")
async def api_newsletter_info(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get Newsletter Info"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        res = await client.get_newsletter_info(str_to_jid(jid))
        return {"success": True, "info": MessageToDict(res)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/newsletter/follow")
async def api_newsletter_follow(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Follow a Newsletter"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        await client.follow_newsletter(str_to_jid(jid))
        return {"success": True, "message": f"Followed newsletter {jid}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/newsletter/unfollow")
async def api_newsletter_unfollow(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Unfollow a Newsletter"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        await client.unfollow_newsletter(str_to_jid(jid))
        return {"success": True, "message": f"Unfollowed newsletter {jid}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/newsletter/messages")
async def api_newsletter_messages(jid: str, count: int = 10, before: Optional[int] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get Newsletter Messages"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        res = await client.get_newsletter_messages(str_to_jid(jid), count, before or 0)
        return {"success": True, "messages": [MessageToDict(m) for m in res]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/newsletter/create")
async def api_newsletter_create(name: str, description: str = "", phone: Optional[str] = None, username: str = Depends(verify_api_key), picture: Optional[str] = None):
    """External API: Create a Newsletter (Channel)"""
    client, p = get_client(username, phone)
    if not client: raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    try:
        res = await client.create_newsletter(name, description, picture or b"")
        return {"success": True, "message": "Newsletter created successfully", "info": MessageToDict(res)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
