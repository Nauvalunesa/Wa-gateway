"""Cookie-authenticated web endpoints for Neonize message tools."""

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from gateway.database import log_message
from gateway.security import dashboard_user
from gateway.services.neonize_tools import (
    build_ad_message,
    build_after_read_message,
    download_ad_thumbnail,
    get_settings,
    save_settings,
)
from gateway.services.neonize_spr import (
    SPRUnavailableError,
    send_spr_group,
    spr_capability,
)
from gateway.whatsapp.addressing import get_actual_jid, get_target_jid, normalize_phone_number
from gateway.whatsapp.clients import get_client
from gateway.whatsapp.runtime import GatewayClient


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

    @field_validator("image_url", "source_url")
    @classmethod
    def validate_https_url(cls, value: str):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("URL harus menggunakan https://")
        return value

    @field_validator("text")
    @classmethod
    def validate_ad_text(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("Isi teks iklan terlebih dahulu.")
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


class SPRSend(BaseModel):
    phone: str = Field(min_length=7, max_length=20)
    group_jid: str = Field(min_length=1, max_length=180)
    target_jids: list[str] = Field(min_length=1, max_length=25)
    target_message: str = Field(min_length=1, max_length=4000)
    decoy_message: str = Field(min_length=1, max_length=4000)


@router.get("/api/web/neonize-tools/settings")
async def read_settings(username: str = Depends(dashboard_user)):
    return get_settings(username)


@router.put("/api/web/neonize-tools/settings")
async def update_settings(data: ToolSettings, username: str = Depends(dashboard_user)):
    return {"success": True, **save_settings(username, data.ephemeral_default_seconds)}


@router.get("/api/web/neonize-tools/group-participants")
async def get_group_participants(
    phone: str = Query(min_length=7, max_length=20),
    group_jid: str = Query(min_length=1, max_length=180),
    username: str = Depends(dashboard_user),
):
    """Load a group's members for selecting DM recipients or SPR targets."""
    phone = normalize_phone_number(phone)
    client, _ = get_client(username, phone)
    if not client:
        raise HTTPException(503, "Pilih perangkat WhatsApp akun ini yang sedang online.")
    try:
        connected = client.is_connected
        if asyncio.iscoroutine(connected):
            connected = await connected
        if not connected:
            raise HTTPException(503, "Perangkat belum terhubung ke WhatsApp.")

        group = get_target_jid(group_jid.strip())
        if group.Server != "g.us":
            raise HTTPException(422, "Pilih JID grup WhatsApp yang berakhiran @g.us.")
        info = await client.get_group_info(group)
        participants = []
        seen = set()
        for member in info.Participants:
            member_jid = getattr(member, "JID", None) or member.LID
            raw_jid = f"{member_jid.User}@{member_jid.Server}"
            resolved_jid = raw_jid
            if member_jid.Server == "lid":
                try:
                    pn_jid = await client.get_pn_from_lid(member_jid)
                    if pn_jid:
                        resolved_jid = f"{pn_jid.User}@{pn_jid.Server}"
                except Exception:
                    pass
            if resolved_jid in seen:
                continue
            seen.add(resolved_jid)
            is_private_jid = resolved_jid.endswith("@s.whatsapp.net")
            participants.append({
                "jid": resolved_jid,
                "spr_jid": raw_jid,
                "phone": resolved_jid.split("@", 1)[0] if is_private_jid else "",
                "lid": raw_jid if raw_jid.endswith("@lid") else "",
                "is_admin": bool(getattr(member, "IsAdmin", False)),
                "is_super_admin": bool(getattr(member, "IsSuperAdmin", False)),
                "is_self": is_private_jid and resolved_jid.split("@", 1)[0] == phone,
            })
        group_name = getattr(info, "GroupName", None)
        group_name = getattr(group_name, "Name", group_name) or group_jid
        return {
            "success": True,
            "group": {"jid": group_jid, "name": str(group_name)},
            "participants": participants,
            "count": len(participants),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Anggota grup gagal dimuat: {exc}") from exc


@router.get("/api/web/neonize-tools/spr/capabilities")
async def get_spr_capabilities(
    phone: str = Query(min_length=7, max_length=20),
    username: str = Depends(dashboard_user),
):
    """Report whether this installed Neonize runtime has a real SPR transport."""
    phone = normalize_phone_number(phone)
    client, _ = get_client(username, phone)
    runtime = client if client is not None else GatewayClient
    return {**spr_capability(runtime), "connected": client is not None}


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
        thumbnail = await asyncio.to_thread(download_ad_thumbnail, data.image_url.strip())
        message = build_ad_message(
            text=data.text,
            thumbnail=thumbnail,
            title=data.title.strip(),
            advertiser=data.advertiser.strip(),
            image_url=data.image_url.strip(),
            source_url=data.source_url.strip(),
            source_app=data.source_app.strip(),
        )
        await client.send_message(target, message)
        await log_message(username, f"DEVICE({phone})", data.to, f"[AD INTERACTIVE] {data.title}", "OUTGOING")
        return {"success": True, "device": phone, "to": data.to, "message": "Satu pesan iklan dikirim."}
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


@router.post("/api/web/neonize-tools/spr")
async def send_spr(data: SPRSend, username: str = Depends(dashboard_user)):
    """Send one A/B SPR message to a group through Neonize's dedicated API."""
    phone = normalize_phone_number(data.phone)
    client, _ = get_client(username, phone)
    if not client:
        raise HTTPException(503, "Pilih perangkat WhatsApp akun ini yang sedang online.")
    capability = spr_capability(client)
    if not capability["supported"]:
        raise HTTPException(501, capability["reason"])

    try:
        group = await get_actual_jid(client, data.group_jid.strip())
        if group.Server != "g.us":
            raise HTTPException(422, "SPR hanya dapat dikirim ke grup WhatsApp.")
        info = await client.get_group_info(group)

        # Validate every selected target against the current group metadata.
        # The browser's member list is only a convenience, not an authorization
        # boundary for a forged request.
        allowed_jids: set[str] = set()
        for member in info.Participants:
            for field_name in ("JID", "LID", "PhoneNumber"):
                jid = getattr(member, field_name, None)
                if jid and getattr(jid, "User", "") and getattr(jid, "Server", ""):
                    allowed_jids.add(f"{jid.User}@{jid.Server}")
                    if jid.Server == "lid":
                        try:
                            pn_jid = await client.get_pn_from_lid(jid)
                            if pn_jid:
                                allowed_jids.add(f"{pn_jid.User}@{pn_jid.Server}")
                        except Exception:
                            pass
        targets = list(dict.fromkeys(value.strip() for value in data.target_jids))
        invalid = [jid for jid in targets if jid not in allowed_jids]
        if invalid:
            raise HTTPException(422, "Target harus dipilih dari anggota grup yang sedang dipilih.")

        await send_spr_group(
            client,
            f"{group.User}@{group.Server}",
            targets,
            data.target_message,
            data.decoy_message,
        )
        group_label = getattr(getattr(info, "GroupName", None), "Name", "") or data.group_jid
        await log_message(
            username,
            f"DEVICE({phone})",
            f"{group.User}@{group.Server}",
            f"[SPR GROUP] {len(targets)} target; decoy aktif ({group_label})",
            "OUTGOING",
        )
        return {
            "success": True,
            "device": phone,
            "group": f"{group.User}@{group.Server}",
            "target_count": len(targets),
            "message": "SPR grup dikirim melalui transport Neonize.",
        }
    except HTTPException:
        raise
    except SPRUnavailableError as exc:
        raise HTTPException(501, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
