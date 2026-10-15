"""Own-account profile operations and bounded JPEG preparation."""
import asyncio
import base64
import hashlib
from io import BytesIO
import re
import warnings

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_PIXELS = 20_000_000
PHOTO_SIZE = 640


def prepare_profile_photo(data: bytes, mode: str, background: str = "#ffffff") -> dict:
    if mode not in ("cover", "contain", "original"):
        raise HTTPException(422, "Mode foto tidak dikenali")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        raise HTTPException(422, "Warna latar harus berupa #RRGGBB")
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Foto harus berisi data dan berukuran maksimal 10 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in ("JPEG", "PNG", "WEBP"):
                    raise HTTPException(422, "Gunakan foto JPEG, PNG, atau WebP")
                if source.width * source.height > MAX_PHOTO_PIXELS:
                    raise HTTPException(413, "Resolusi foto maksimal 20 megapiksel")
                if getattr(source, "is_animated", False):
                    raise HTTPException(422, "Gunakan gambar diam, bukan animasi")
                image = ImageOps.exif_transpose(source).convert("RGBA")
        rgb = Image.new("RGB", image.size, background)
        rgb.paste(image, mask=image.getchannel("A"))
        original_size = list(rgb.size)
        if mode == "cover":
            result = ImageOps.fit(rgb, (PHOTO_SIZE, PHOTO_SIZE), method=Image.Resampling.LANCZOS)
        elif mode == "contain":
            fitted = ImageOps.contain(rgb, (PHOTO_SIZE, PHOTO_SIZE), method=Image.Resampling.LANCZOS)
            result = Image.new("RGB", (PHOTO_SIZE, PHOTO_SIZE), background)
            result.paste(fitted, ((PHOTO_SIZE-fitted.width)//2, (PHOTO_SIZE-fitted.height)//2))
        else:
            result = rgb.copy()
            result.thumbnail((PHOTO_SIZE, PHOTO_SIZE), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        result.save(buffer, format="JPEG", quality=90, optimize=True)
        jpeg = buffer.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "File gambar tidak valid atau resolusinya terlalu besar") from exc
    return {"bytes": jpeg, "sha256": hashlib.sha256(jpeg).hexdigest(),
            "width": result.width, "height": result.height, "source_size": original_size,
            "mode": mode, "mime_type": "image/jpeg", "size_bytes": len(jpeg),
            "preview": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
            "experimental": mode == "original" and result.width != result.height}


async def read_own_profile(client, phone: str) -> dict:
    try:
        device = await asyncio.wait_for(client.get_me(), timeout=10)
    except Exception as exc:
        raise HTTPException(502, "Tidak dapat membaca identitas perangkat WhatsApp") from exc
    jid = device.JID
    if not jid.User:
        raise HTTPException(503, "Identitas WhatsApp belum siap. Tunggu koneksi tersinkron.")
    result = {"phone": phone, "jid": f"{jid.User}@{jid.Server}", "name": device.PushName,
              "about": None, "photo_url": None, "warnings": []}
    async def about():
        try:
            records = await asyncio.wait_for(client.get_user_info(jid), timeout=10)
            if records:
                result["about"] = records[0].UserInfo.Status
            else:
                result["warnings"].append("Info/about belum tersedia dari WhatsApp.")
        except Exception:
            result["warnings"].append("Info/about belum dapat dimuat. Coba muat ulang profil.")
    async def photo():
        try:
            info = await asyncio.wait_for(client.get_profile_picture(jid), timeout=10)
            result["photo_url"] = info.URL or None
        except Exception:
            result["warnings"].append("Foto belum tersedia atau belum dapat dimuat.")
    await asyncio.gather(about(), photo())
    return result


async def apply_profile_change(operation, *args):
    try:
        return await asyncio.wait_for(operation(*args), timeout=30)
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, "WhatsApp belum merespons. Perubahan mungkin masih diproses; muat ulang profil sebelum mencoba lagi.") from exc
    except Exception as exc:
        raise HTTPException(502, f"WhatsApp menolak atau gagal memproses perubahan profil: {exc}") from exc
