"""Per-account settings and protobuf builders for the Neonize tools page."""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import secrets
import socket
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
    ContextInfo,
    DisappearingMode,
    ExtendedTextMessage,
    InteractiveMessage,
    Message,
)


def _settings_path(username: str) -> Path:
    return Path("storage") / username / "config" / "neonize_tools.json"


def get_settings(username: str) -> dict[str, int]:
    try:
        saved = json.loads(_settings_path(username).read_text(encoding="utf-8"))
        duration = max(0, min(int(saved.get("ephemeral_default_seconds", 0)), 604800))
    except (OSError, ValueError, TypeError, AttributeError):
        duration = 0
    return {"ephemeral_default_seconds": duration}


def save_settings(username: str, ephemeral_default_seconds: int) -> dict[str, int]:
    duration = max(0, min(int(ephemeral_default_seconds), 604800))
    path = _settings_path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump({"ephemeral_default_seconds": duration}, target)
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)
    return {"ephemeral_default_seconds": duration}


def _is_public_https_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
        }
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(address.is_global for address in addresses)


class _PublicImageRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        if not _is_public_https_url(new_url):
            return None
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def download_ad_thumbnail(url: str, timeout: float = 8.0) -> bytes | None:
    """Fetch and downsize a public image for WhatsApp's inline ad thumbnail."""
    if not url or not _is_public_https_url(url):
        return None
    request = Request(url, headers={"User-Agent": "Utusan-WaGateway/ad-preview"})
    try:
        with build_opener(_PublicImageRedirectHandler()).open(request, timeout=timeout) as response:
            if not _is_public_https_url(response.geturl()):
                return None
            if int(response.headers.get("Content-Length", "0") or 0) > 5_000_000:
                return None
            data = response.read(5_000_001)
        if len(data) > 5_000_000:
            return None
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 40_000_000:
                return None
            image = image.convert("RGB")
            image.thumbnail((200, 200), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=40, optimize=True)
            return output.getvalue()
    except Exception:
        return None


def build_ad_message(
    *,
    text: str = "",
    thumbnail: bytes | None = None,
    title: str,
    advertiser: str,
    button_text: str = "🌐 Kunjungi Web",
    image_url: str,
    source_url: str,
    source_app: str,
) -> Message:
    """Build the single CTA-URL interactive ad used by the ads.py example."""
    caption = text.strip()
    ad = ContextInfo.ExternalAdReplyInfo(
        title=title,
        body=advertiser,
        mediaType=ContextInfo.ExternalAdReplyInfo.IMAGE if image_url else ContextInfo.ExternalAdReplyInfo.NONE,
        thumbnailURL=image_url,
        mediaURL=image_url,
        originalImageURL=image_url,
        sourceType="ad",
        sourceID=str(secrets.randbelow(100_000_000_000_000)),
        sourceURL=source_url,
        containsAutoReply=True,
        renderLargerThumbnail=True,
        showAdAttribution=True,
        ctwaClid=base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        ref=secrets.token_hex(8),
        clickToWhatsappCall=True,
        adContextPreviewDismissed=False,
        sourceApp=source_app,
        automatedGreetingMessageShown=True,
        greetingMessageBody=caption,
    )
    if thumbnail:
        ad.thumbnail = thumbnail
    button_payload = {
        "display_text": button_text.strip() or "🌐 Kunjungi Web",
        "url": source_url,
        "merchant_url": source_url,
    }
    interactive = InteractiveMessage(
        body=InteractiveMessage.Body(text=caption),
        footer=InteractiveMessage.Footer(text=advertiser),
        nativeFlowMessage=InteractiveMessage.NativeFlowMessage(
            buttons=[
                InteractiveMessage.NativeFlowMessage.NativeFlowButton(
                    name="cta_url",
                    buttonParamsJSON=json.dumps(button_payload, ensure_ascii=False),
                )
            ],
            messageVersion=1,
        ),
        contextInfo=ContextInfo(externalAdReply=ad),
    )
    return Message(interactiveMessage=interactive)


def build_after_read_message(text: str, duration_seconds: int) -> Message:
    context = ContextInfo(
        expiration=0,
        ephemeralSettingTimestamp=time.time_ns() // 1_000_000,
        disappearingMode=DisappearingMode(initiator=0, trigger=1),
        afterReadDuration=duration_seconds,
    )
    return Message(
        extendedTextMessage=ExtendedTextMessage(text=text, contextInfo=context)
    )
