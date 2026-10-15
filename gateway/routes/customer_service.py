"""Cookie-authenticated configuration, preview, and handoff controls for CS."""
from fastapi import APIRouter, Depends
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel

from gateway.messages.cs import build_cs_message, reply_content
from gateway.messages.cs_models import CSConfig, CSPreviewPayload
from gateway.security import dashboard_user as cs_user
from gateway.services.customer_service import (
    active_conversations, conversations, get_cs_settings, navigate, save_cs_settings,
)

router = APIRouter()


@router.get("/api/web/customer-service")
async def get_customer_service(username: str = Depends(cs_user)):
    config, revision = get_cs_settings(username)
    return {"config": config.model_dump(), "revision": revision}


@router.put("/api/web/customer-service")
async def put_customer_service(config: CSConfig, username: str = Depends(cs_user)):
    revision = save_cs_settings(username, config)
    return {"success": True, "config": config.model_dump(), "revision": revision}


@router.post("/api/web/customer-service/preview")
async def preview_customer_service(data: CSPreviewPayload, username: str = Depends(cs_user)):
    node, invalid = navigate(data.config, "preview", data.text, data.current_node)
    if not data.text and data.current_node:
        invalid = False
    content = reply_content(data.config, node, data.name, "preview")
    if invalid:
        content["body"] = "Pilihan tidak dikenali atau tombol sudah kedaluwarsa. Pilih kembali dari menu ini.\n\n" + content["body"]
    message = await build_cs_message(content)
    return {"success": True, "sent": False, "reply": content, "message": MessageToDict(message)}


@router.get("/api/web/customer-service/conversations")
async def list_customer_service_conversations(username: str = Depends(cs_user)):
    return {"conversations": active_conversations(username)}


class ResetConversation(BaseModel):
    phone: str
    chat: str


@router.post("/api/web/customer-service/reset")
async def reset_customer_service_conversation(data: ResetConversation, username: str = Depends(cs_user)):
    conversations.pop((username, data.phone, data.chat), None)
    return {"success": True}
