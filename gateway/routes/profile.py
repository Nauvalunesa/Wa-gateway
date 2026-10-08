"""Cookie-authenticated own-device profile and photo editing."""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from gateway.messages.profile_models import (
    ProfileAboutPayload, ProfileNamePayload, ProfilePreferences,
    ProfilePreferencesPayload, ProfilePrivacyPayload,
)
from gateway.services.profile_privacy import read_privacy, save_preferences, set_privacy
from gateway.security import dashboard_user
from gateway.services.profile import (
    MAX_PHOTO_BYTES, apply_profile_change, prepare_profile_photo,
    read_own_profile,
)
from gateway.whatsapp.clients import get_client
from gateway.whatsapp.addressing import normalize_phone_number

router = APIRouter()


def require_profile_client(username: str, phone: str):
    client, _ = get_client(username, normalize_phone_number(phone))
    if not client:
        raise HTTPException(503, "Perangkat WhatsApp tidak terhubung. Pilih perangkat online.")
    return client


@router.get("/api/web/wa-profile/privacy")
async def get_profile_privacy(phone: str = Query(...), username: str = Depends(dashboard_user)):
    return await read_privacy(require_profile_client(username, phone), username, phone)


@router.put("/api/web/wa-profile/preferences")
async def put_profile_preferences(data: ProfilePreferencesPayload, username: str = Depends(dashboard_user)):
    require_profile_client(username, data.phone)
    value = ProfilePreferences(auto_read=data.auto_read, auto_read_scope=data.auto_read_scope)
    save_preferences(username, data.phone, value)
    return {"success": True, "preferences": value.model_dump()}


@router.put("/api/web/wa-profile/privacy")
async def put_profile_privacy(data: ProfilePrivacyPayload, username: str = Depends(dashboard_user)):
    await set_privacy(require_profile_client(username, data.phone), data.setting, data.value)
    return {"success": True, "setting": data.setting, "value": data.value}


@router.get("/api/web/wa-profile")
async def get_profile(phone: str = Query(...), username: str = Depends(dashboard_user)):
    return await read_own_profile(require_profile_client(username, phone), phone)


@router.put("/api/web/wa-profile/name")
async def put_profile_name(data: ProfileNamePayload, username: str = Depends(dashboard_user)):
    client = require_profile_client(username, data.phone)
    await apply_profile_change(client.set_profile_name, data.name)
    return {"success": True, "phone": data.phone, "name": data.name}


@router.put("/api/web/wa-profile/about")
async def put_profile_about(data: ProfileAboutPayload, username: str = Depends(dashboard_user)):
    client = require_profile_client(username, data.phone)
    await apply_profile_change(client.set_status_message, data.about)
    return {"success": True, "phone": data.phone, "about": data.about}


async def prepare_upload(file: UploadFile, mode: str, background: str):
    data = await file.read(MAX_PHOTO_BYTES + 1)
    return await asyncio.to_thread(prepare_profile_photo, data, mode, background)


@router.post("/api/web/wa-profile/photo/preview")
async def preview_profile_photo(
    file: UploadFile = File(...), mode: Literal["cover", "contain", "original"] = Form("contain"),
    background: str = Form("#ffffff"), username: str = Depends(dashboard_user),
):
    prepared = await prepare_upload(file, mode, background)
    prepared.pop("bytes")
    return {"success": True, "sent": False, **prepared}


@router.post("/api/web/wa-profile/photo")
async def put_profile_photo(
    phone: str = Form(...), file: UploadFile = File(...),
    mode: Literal["cover", "contain", "original"] = Form("contain"),
    background: str = Form("#ffffff"), sha256: str = Form(...),
    username: str = Depends(dashboard_user),
):
    client = require_profile_client(username, phone)
    prepared = await prepare_upload(file, mode, background)
    if sha256 != prepared["sha256"]:
        raise HTTPException(409, "Foto atau pilihan sudah berubah. Buat preview terbaru sebelum menyimpan.")
    picture_id = await apply_profile_change(client.set_profile_photo, prepared["bytes"])
    return {"success": True, "phone": phone, "picture_id": picture_id,
            "width": prepared["width"], "height": prepared["height"], "experimental": prepared["experimental"]}
