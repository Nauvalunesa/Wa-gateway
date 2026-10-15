"""Per-account settings and protobuf builders for the Neonize tools page."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
    ContextInfo,
    DisappearingMode,
    ExtendedTextMessage,
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
