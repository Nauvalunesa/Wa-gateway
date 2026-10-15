"""Status API routes."""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
    ContextInfo,
    ExtendedTextMessage,
    Message as WAMessage,
)

from gateway.database import log_message
from gateway.security import verify_api_key
from gateway.whatsapp.addressing import get_mentions_list, get_target_jid
from gateway.whatsapp.clients import get_client
from gateway.whatsapp.serialization import str_to_jid


router = APIRouter()


@router.get("/api/send-status")
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
            if url:
                resolved_url = url
                if resolved_url.startswith("static/"):
                    base_url = str(request.base_url).rstrip("/")
                    media_to_send = f"{base_url}/{resolved_url}"
                else:
                    media_to_send = resolved_url

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


@router.get("/api/send-group-status")
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
            # Resolve local media URLs
            if url:
                resolved_url = url
                if resolved_url.startswith("static/"):
                    base_url = str(request.base_url).rstrip("/")
                    media_to_send = f"{base_url}/{resolved_url}"
                else:
                    media_to_send = resolved_url

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
