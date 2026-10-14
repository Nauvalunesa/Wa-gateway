"""Cookie-authenticated web endpoints for Neonize message tools."""

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from gateway.database import log_message
from gateway.security import dashboard_user
from gateway.services.neonize_tools import (
    build_ad_message,
    build_after_read_message,
    get_settings,
    save_settings,
)
from gateway.whatsapp.addressing import get_actual_jid, get_target_jid, normalize_phone_number
from gateway.whatsapp.clients import get_client


router = APIRouter()


class ToolSettings(BaseModel):
    ephemeral_default_seconds: int = Field(ge=0, le=604800)


class AdSend(BaseModel):
    phone: str = Field(min_length=7, max_length=20)
    to: str = Field(min_length=1, max_length=180)
    text: str = Field(min_length=1, max_length=4000)
    title: str = Field(default="Utusan", min_length=1, max_length=80)
    advertiser: str = Field(default="Utusan.chat", max_length=80)
    image_url: str = Field(default="", max_length=2000)
    source_url: str = Field(min_length=8, max_length=2000)
    source_app: str = Field(default="Utusan.chat", min_length=1, max_length=80)
    button_label: str = Field(default="Kunjungi website", min_length=1, max_length=25)

    @field_validator("image_url", "source_url")
    @classmethod
    def validate_https_url(cls, value: str):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("URL harus menggunakan https://")
        return value


class AfterReadSend(BaseModel):
    phone: str = Field(min_length=7, max_length=20)
    to: str = Field(min_length=1, max_length=180)
    text: str = Field(min_length=1, max_length=4000)
    duration_seconds: int | None = Field(default=None, ge=1, le=604800)


class PrivateSend(BaseModel):
    phone: str = Field(min_length=7, max_length=20)
    recipients: list[str] = Field(min_length=1, max_length=25)
    text: str = Field(min_length=1, max_length=4000)


@router.get("/api/web/neonize-tools/settings")
async def read_settings(username: str = Depends(dashboard_user)):
    return get_settings(username)


@router.put("/api/web/neonize-tools/settings")
async def update_settings(data: ToolSettings, username: str = Depends(dashboard_user)):
    return {"success": True, **save_settings(username, data.ephemeral_default_seconds)}


@router.post("/api/web/neonize-tools/ad")
async def send_ad(data: AdSend, username: str = Depends(dashboard_user)):
    phone = normalize_phone_number(data.phone)
    client, _ = get_client(username, phone)
    if not client:
        raise HTTPException(503, "Pilih perangkat WhatsApp akun ini yang sedang online.")
    try:
        target = await get_actual_jid(client, data.to.strip())
        if target.Server not in {"s.whatsapp.net", "lid", "g.us"}:
            raise HTTPException(422, "Iklan interaktif hanya dapat dikirim ke chat atau grup.")
        message = build_ad_message(
            text=data.text.strip(),
            title=data.title.strip(),
            advertiser=data.advertiser.strip(),
            image_url=data.image_url.strip(),
            source_url=data.source_url.strip(),
            source_app=data.source_app.strip(),
            button_label=data.button_label.strip(),
        )
        await client.send_message(target, message)
        await log_message(username, f"DEVICE({phone})", data.to, f"[AD INTERACTIVE] {data.text}", "OUTGOING")
        return {"success": True, "device": phone, "to": data.to, "message": "Iklan interaktif dikirim."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/api/web/neonize-tools/after-read")
async def send_after_read(data: AfterReadSend, username: str = Depends(dashboard_user)):
    phone = normalize_phone_number(data.phone)
    client, _ = get_client(username, phone)
    if not client:
        raise HTTPException(503, "Pilih perangkat WhatsApp akun ini yang sedang online.")
    duration = data.duration_seconds or get_settings(username)["ephemeral_default_seconds"]
    if not duration:
        raise HTTPException(422, "Atur durasi bawaan atau pilih durasi sebelum mengirim.")
    try:
        target = await get_actual_jid(client, data.to.strip())
        if target.Server not in {"s.whatsapp.net", "lid", "g.us"}:
            raise HTTPException(422, "Pesan setelah dibaca hanya dapat dikirim ke chat atau grup.")
        await client.send_message(target, build_after_read_message(data.text.strip(), duration))
        await log_message(
            username,
            f"DEVICE({phone})",
            data.to,
            f"[AFTER READ {duration}s] {data.text}",
            "OUTGOING",
        )
        return {
            "success": True,
            "device": phone,
            "to": data.to,
            "duration_seconds": duration,
            "message": "Pesan dikirim dengan metadata durasi setelah dibaca.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/api/web/neonize-tools/private-reply")
async def send_private_reply(data: PrivateSend, username: str = Depends(dashboard_user)):
    phone = normalize_phone_number(data.phone)
    client, _ = get_client(username, phone)
    if not client:
        raise HTTPException(503, "Pilih perangkat WhatsApp akun ini yang sedang online.")

    targets = []
    seen = set()
    for recipient in data.recipients:
        raw = recipient.strip()
        if not raw:
            continue
        try:
            target = get_target_jid(raw if "@" in raw else normalize_phone_number(raw))
        except HTTPException:
            raise
        if target.Server not in {"s.whatsapp.net", "lid"}:
            raise HTTPException(422, "Balasan privat menerima nomor pribadi atau JID @lid; JID grup/channel tidak diizinkan.")
        key = (target.User, target.Server)
        if key not in seen:
            targets.append((target, raw))
            seen.add(key)
    if not targets:
        raise HTTPException(422, "Masukkan setidaknya satu nomor/JID pribadi yang valid.")

    results = []
    for index, (target, raw) in enumerate(targets):
        jid = f"{target.User}@{target.Server}"
        try:
            await client.send_message(target, data.text.strip())
            await log_message(username, f"DEVICE({phone})", jid, data.text.strip(), "OUTGOING")
            results.append({"to": jid, "success": True})
        except Exception as exc:
            results.append({"to": jid, "success": False, "error": str(exc)})
        if index + 1 < len(targets):
            await asyncio.sleep(0.5)
    return {
        "success": True,
        "device": phone,
        "sent": sum(result["success"] for result in results),
        "failed": sum(not result["success"] for result in results),
        "all_success": all(result["success"] for result in results),
        "results": results,
    }
