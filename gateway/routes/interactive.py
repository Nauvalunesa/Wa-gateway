"""Interactive API routes."""
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from neonize.ext.interactive_message import ButtonV2Message
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
    ContextInfo,
    InteractiveMessage,
    Message as WAMessage,
)

from gateway.database import log_message
from gateway.messages.interactive import normalize_interactive_payload
from gateway.messages.models import ButtonV2Payload, InteractivePayload
from gateway.security import verify_api_key
from gateway.whatsapp.addressing import get_actual_jid, get_mentions_list
from gateway.whatsapp.clients import get_client


router = APIRouter()


@router.get("/api/send-interactive")
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
                resolved_url = media_url
                if resolved_url.startswith("static/"):
                    video_url_to_send = f"{base_url}/{resolved_url}"
                else:
                    video_url_to_send = resolved_url
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
                        resolved_url = url
                        if resolved_url.startswith("static/"):
                            base_url = str(request.base_url).rstrip("/")
                            video_url_to_send = f"{base_url}/{resolved_url}"
                        else:
                            video_url_to_send = resolved_url
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


@router.post("/api/send-interactive")
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
            # But for now, let's keep it as is or handle local path
            resolved_url = data.media_url
            if resolved_url.startswith("static/"):
                video_url_to_send = f"{base_url}/{resolved_url}"
            else:
                video_url_to_send = resolved_url
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
                    resolved_url = url
                    if resolved_url.startswith("static/"):
                        base_url = str(request.base_url).rstrip("/")
                        video_url_to_send = f"{base_url}/{resolved_url}"
                    else:
                        video_url_to_send = resolved_url
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


@router.post("/api/send-buttonv2")
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


@router.get("/api/send-buttonv2")
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
