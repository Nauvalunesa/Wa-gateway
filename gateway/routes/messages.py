"""Messages API routes."""
import os
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
    ContextInfo,
    ExtendedTextMessage,
    Message as WAMessage,
)
from neonize.utils.enum import VoteType

from gateway.database import log_message
from gateway.messages.models import LocationSendPayload, PollSendPayload, ReactionSendPayload
from gateway.security import verify_api_key
from gateway.whatsapp.addressing import (
    get_actual_jid,
    get_mentions_list,
    get_target_jid,
    normalize_phone_number,
)
from gateway.whatsapp.clients import get_client


router = APIRouter()


@router.get("/api/send-message")
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


@router.get("/api/send-image")
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


@router.get("/api/send-audio")
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


@router.get("/api/send-video")
async def api_send_video(request: Request, to: str, video_url: str, caption: Optional[str] = "", hd: bool = False, viewonce: bool = False, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Send video using query params"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = get_target_jid(to)
    try:
        # Resolve local media URLs
        resolved_url = video_url
        # If it's a local path, convert to public URL for neonize to download (or neonize might handle local paths)
        if resolved_url.startswith("static/"):
            base_url = str(request.base_url).rstrip("/")
            video_url_to_send = f"{base_url}/{resolved_url}"
        else:
            video_url_to_send = resolved_url

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


@router.get("/api/send-document")
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


@router.get("/api/send-sticker")
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


@router.get("/api/send-contact")
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


@router.post("/api/send-location")
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


@router.post("/api/send-poll")
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


@router.post("/api/send-reaction")
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


@router.get("/api/resend")
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
