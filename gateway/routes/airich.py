"""Airich API routes."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from google.protobuf.json_format import MessageToDict, ParseError

from gateway.database import log_message
from gateway.messages.airich import build_airich_message
from gateway.messages.models import AIRichPayload
from gateway.security import verify_api_key
from gateway.whatsapp.addressing import get_actual_jid, get_mentions_list
from gateway.whatsapp.clients import get_client


router = APIRouter()


@router.post("/api/airich/preview")
async def api_airich_preview(data: AIRichPayload, username: str = Depends(verify_api_key)):
    """Build the message without sending. This is a protobuf preview, not a WhatsApp render."""
    try:
        msg = await build_airich_message(data)
        return {"success": True, "sent": False, "message": MessageToDict(msg)}
    except (ValueError, TypeError, ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/send-airich")
async def api_send_airich_post(request: Request, data: AIRichPayload, username: str = Depends(verify_api_key)):
    """Send AI Rich blocks, including experimental HTML primitives."""
    client, p = get_client(username, data.phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")
    target_jid = await get_actual_jid(client, data.to)
    try:
        mentions = await get_mentions_list(client, target_jid, data.mentions)
        wa_msg = await build_airich_message(data, client, mentions)
    except (ValueError, TypeError, ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        await client.send_message(target_jid, wa_msg)
        await log_message(username, f"DEVICE({p})", data.to, "[AIRICH]", "OUTGOING")
        return {"success": True, "message": "AI Rich message sent successfully", "to": data.to, "device": p}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/send-airich")
async def api_send_airich_get(request: Request, to: str, payload: str, mentions: Optional[str] = None, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """GET uses the same validated payload and builder as POST."""
    try:
        values = json.loads(payload)
        if not isinstance(values, dict):
            raise ValueError("payload must be a JSON object")
        values["to"] = to
        if phone is not None:
            values["phone"] = phone
        if mentions is not None:
            values["mentions"] = mentions
        data = AIRichPayload.model_validate(values)
    except (ValueError, TypeError, ParseError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await api_send_airich_post(request, data, username)
